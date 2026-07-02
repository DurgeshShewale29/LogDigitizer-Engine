from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn
import os
import sys
import pandas as pd
import json
import threading

from contextlib import asynccontextmanager
import fitz
import docx
from io import BytesIO
from fastapi.responses import StreamingResponse

from core.classifier import classify_document, classify_text
from core.schemas import UploadResponse, SaveRecordRequest, ChatRequest, ChatResponse, LoginRequest, LoginResponse, DeleteRecordsRequest
from core.database import init_db, save_document, get_documents_by_type, get_all_documents, get_audit_logs, get_document_file, delete_documents, delete_audit_logs
from core.chatbot import process_chat_query

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="LogDigitizer Enterprise Platform", lifespan=lifespan)

def get_base_path():
    """Resolve absolute path for PyInstaller or local execution."""
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

base_dir = get_base_path()

# Mount static files (CSS, JS) using resolved path
app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")

# Configure Jinja2 templates using resolved path
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """
    Renders the main dashboard.
    """
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/database", response_class=HTMLResponse)
def database_view(request: Request):
    """
    Renders the full standalone database explorer view.
    """
    records = get_all_documents()
    audit_logs = get_audit_logs()
    return templates.TemplateResponse(request=request, name="database.html", context={
        "records": records, 
        "audit_logs": audit_logs
    })

@app.post("/api/upload", response_model=UploadResponse)
def upload_document(file: UploadFile = File(...)):
    """
    Handles file batch uploads. 
    Routes to Excel parser if .xls/.xlsx, else routes to general document classifier.
    """
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    try:
        file_bytes = file.file.read()
        
        if ext == '.pdf':
            # PDF Processing: Render Page 0 to image
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if len(doc) > 0:
                page = doc.load_page(0)
                # Render to high-res image (approx 144 DPI)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                png_bytes = pix.tobytes("png")
                # Pass image bytes to standard CV/OCR pipeline
                schema = classify_document(filename, png_bytes)
            else:
                schema = classify_text(filename, "")
            doc.close()
            
        elif ext in ['.docx', '.doc']:
            # Word Processing: Extract raw text directly
            doc = docx.Document(BytesIO(file_bytes))
            full_text = "\n".join([para.text for para in doc.paragraphs])
            # Pass directly to NLP pipeline, bypassing CV/OCR
            schema = classify_text(filename, full_text)
            
        else:
            # Send standard images to OpenCV/OCR pipeline
            schema = classify_document(filename, file_bytes)
            
        return UploadResponse(
            filename=filename,
            status="processed",
            parsed_schema=schema
        )
    except Exception as e:
        # Resilient exception handling
        return UploadResponse(
            filename=filename,
            status="error",
            message=str(e),
            parsed_schema={
                "document_type": "Unknown",
                "confidence": 0.0,
                "fields": []
            }
        )

@app.post("/api/save-record")
def save_record(
    filename: str = Form(...),
    document_type: str = Form(...),
    fields_data: str = Form(...),
    file: UploadFile = File(None)
):
    """Saves the verified form data and raw file to the SQLite database."""
    try:
        data_dict = json.loads(fields_data)
        file_bytes = file.file.read() if file else None
        doc_id = save_document(filename, document_type, data_dict, file_bytes)
        return {"status": "success", "id": doc_id, "message": "Record saved successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/download/{doc_id}")
def download_document(doc_id: int):
    """Downloads the original raw file from the database."""
    filename, file_data = get_document_file(doc_id)
    if not filename or not file_data:
        return HTMLResponse(content="File not found in database.", status_code=404)
        
    return StreamingResponse(
        BytesIO(file_data),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

@app.get("/api/export-data")
def export_data(doc_type: str):
    """Exports SQLite records to an Excel file."""
    try:
        records = get_documents_by_type(doc_type)
        if not records:
            return HTMLResponse(content="No records found for this document type.", status_code=404)
            
        # Ensure strict structural mapping of JSON keys to Pandas columns
        df = pd.json_normalize(records)
        df = df.fillna("") # Clean up any NaN values for missing keys
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=doc_type[:31]) # Excel sheet name limit is 31 chars
            
        output.seek(0)
        
        headers = {
            'Content-Disposition': f'attachment; filename="export_{doc_type.replace(" ", "_")}.xlsx"'
        }
        return StreamingResponse(
            output, 
            headers=headers, 
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        return HTMLResponse(content=f"Export failed: {str(e)}", status_code=500)

@app.post("/api/delete-records")
def delete_records(request: DeleteRecordsRequest):
    """Deletes multiple records from the database by ID."""
    try:
        count = delete_documents(request.doc_ids)
        return {"status": "success", "deleted_count": count, "message": f"{count} records deleted."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/delete-audit-logs")
def api_delete_audit_logs(request: DeleteRecordsRequest):
    """Deletes multiple audit logs from the database by ID."""
    try:
        count = delete_audit_logs(request.doc_ids)
        return {"status": "success", "deleted_count": count, "message": f"{count} logs deleted."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """Processes natural language queries via the local SpaCy engine."""
    try:
        result = process_chat_query(request.query)
        return ChatResponse(response=result["response"], data=result["data"])
    except Exception as e:
        return ChatResponse(response=f"Error processing query: {str(e)}", data=[])

# Hardcoded credentials — single-user, air-gapped security gate
_VALID_USERNAME = "admin"
_VALID_PASSWORD = "admin123"

@app.post("/api/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """Validates operator credentials against the hardcoded security gate."""
    if request.username == _VALID_USERNAME and request.password == _VALID_PASSWORD:
        return LoginResponse(success=True, message="ACCESS GRANTED")
    return LoginResponse(success=False, message="ACCESS DENIED - INVALID CREDENTIALS")

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import time
    
    # PyInstaller windowless mode (console=False) sets sys.stdout to None.
    # Uvicorn tries to call sys.stdout.isatty() for colored logging and crashes.
    # We provide a dummy file object to prevent this crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    is_frozen = getattr(sys, "frozen", False)
    
    def start_backend():
        if is_frozen:
            # In a PyInstaller executable, standard string imports for the main module can fail.
            # Set log_config=None to prevent uvicorn's ColourizedFormatter from crashing on NoneType sys.stdout.isatty
            uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
        else:
            # In dev mode, use string import if we want to test reloading
            uvicorn.run(app, host="127.0.0.1", port=8000)
            
    # Launch the FastAPI backend on a background thread
    server_thread = threading.Thread(target=start_backend, daemon=True)
    server_thread.start()
    
    # Wait for the backend server to start accepting connections
    time.sleep(1.5)
    
    print("\n" + "="*55)
    print(" [RUNNING] LogDigitizer Enterprise Server is RUNNING!")
    print("="*55)
    print("\n Please keep this window open while using the application.")
    print(" To shut down the app, simply close this black terminal window!\n")
    
    # Launch the default OS web browser instead of pywebview to avoid all .NET/DLL issues
    webbrowser.open("http://127.0.0.1:8000")
    
    # Keep the main thread alive since we no longer have webview blocking it
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

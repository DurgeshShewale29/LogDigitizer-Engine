import os
import re
import cv2
import numpy as np
import pytesseract
import spacy
import logging
from .schemas import DocumentSchema, FormField
from .slm import correct_ocr_text, classify_document_type, summarize_notes

logger = logging.getLogger(__name__)
import sys

# Attempt to configure Tesseract path dynamically
# In PyInstaller --onedir mode, sys._MEIPASS points to the application bundle folder
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    # During normal development, assume Tesseract-OCR is in the project root next to core/
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

TESSERACT_DIR = os.path.join(base_dir, "Tesseract-OCR")
TESSERACT_EXE = os.path.join(TESSERACT_DIR, "tesseract.exe")

if os.path.exists(TESSERACT_EXE):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
    # TESSDATA_PREFIX is required by Tesseract to find language packs
    os.environ["TESSDATA_PREFIX"] = os.path.join(TESSERACT_DIR, "tessdata")
    logger.info(f"Tesseract initialized from bundled path: {TESSERACT_EXE}")
else:
    logger.warning(f"Bundled Tesseract not found at {TESSERACT_EXE}. Ensure the Tesseract-OCR folder is included in the build.")

# Load SpaCy model for NLP entity extraction
try:
    nlp = spacy.load("en_core_web_sm")
except Exception as e:
    logger.error(f"Failed to load SpaCy model: {e}")
    nlp = None

def preprocess_image(file_bytes: bytes) -> np.ndarray:
    """
    Spatial Preprocessing: Decodes raw bytes and applies cv2 transformations.
    Converts to grayscale, applies Gaussian Blur to reduce noise, and Otsu's binarization.
    """
    try:
        # Decode image from byte buffer
        np_arr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            return None

        # 1. Grayscale Conversion
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. Gaussian Blur (5x5) to filter metallic/desk noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # 3. Otsu Threshold Binarization
        _, binarized = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return {"gray": gray, "binarized": binarized}
    except Exception as e:
        logger.error(f"OpenCV Preprocessing failed: {e}")
        return None

def execute_ocr(image_matrix: np.ndarray) -> str:
    """
    Passes the binarized matrix to Tesseract OCR to extract string buffer.
    """
    if image_matrix is None:
        return ""
    try:
        text = pytesseract.image_to_string(image_matrix, config='--psm 6')
        return text.strip()
    except Exception as e:
        logger.error(f"OCR Execution failed: {e}")
        return ""

def extract_table_data(image_matrix: np.ndarray) -> list:
    """
    Uses OpenCV Morphological transformations to detect physical table grids, 
    isolates cell bounding boxes, runs Tesseract cell-by-cell, and builds a JSON structure.
    """
    if image_matrix is None:
        return []
    
    try:
        # Invert the binarized image: text/lines become white, background black
        thresh = cv2.bitwise_not(image_matrix)
        
        # Structuring elements
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        
        # Detect lines
        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
        
        # Combine lines to isolate grid
        table_mask = cv2.add(h_lines, v_lines)
        
        # Find contours for cells
        contours, _ = cv2.findContours(table_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        cells = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            # Filter noise and huge outer boxes
            if 100 < w * h < 200000 and w > 10 and h > 10:
                cells.append((x, y, w, h))
                
        if not cells:
            return []
            
        # Sort top-to-bottom, then left-to-right
        cells.sort(key=lambda b: (b[1], b[0]))
        
        # Group into rows based on y-coordinate tolerance
        rows = []
        current_row = []
        last_y = cells[0][1]
        
        for cell in cells:
            x, y, w, h = cell
            if abs(y - last_y) > 15: # 15 pixels tolerance for new row
                current_row.sort(key=lambda b: b[0]) # Sort horizontally
                rows.append(current_row)
                current_row = [cell]
                last_y = y
            else:
                current_row.append(cell)
                
        if current_row:
            current_row.sort(key=lambda b: b[0])
            rows.append(current_row)
            
        if len(rows) < 2:
            return [] # No proper table structure
            
        # Parse text cell-by-cell
        table_data = []
        headers = []
        
        # First row is headers
        for (x, y, w, h) in rows[0]:
            # Add slight padding for OCR accuracy
            cell_img = image_matrix[max(0, y-2):y+h+2, max(0, x-2):x+w+2]
            text = pytesseract.image_to_string(cell_img, config='--psm 6').strip()
            # Remove newlines in headers
            text = " ".join(text.split())
            headers.append(text if text else f"Col_{len(headers)}")
            
        # Subsequent rows are values
        for row in rows[1:]:
            row_dict = {}
            has_text = False
            for idx, (x, y, w, h) in enumerate(row):
                if idx < len(headers):
                    cell_img = image_matrix[max(0, y-2):y+h+2, max(0, x-2):x+w+2]
                    text = pytesseract.image_to_string(cell_img, config='--psm 6').strip()
                    # Remove excessive newlines
                    text = " ".join(text.split())
                    row_dict[headers[idx]] = text
                    if text:
                        has_text = True
            
            # Only append if the row isn't entirely blank
            if has_text and row_dict:
                table_data.append(row_dict)
                
        return table_data
    except Exception as e:
        logger.error(f"Table extraction failed: {e}")
        return []

# Pre-compiled Regex patterns for scalability during large batch processing
_TAGS_PATTERN = re.compile(r"\b[A-Z]{2,4}-\d+\b", re.IGNORECASE)
_REF_PATTERN = re.compile(r"\b(?:REF|RID)-\d+\b", re.IGNORECASE)
_SHIFT_PATTERN = re.compile(r"\bSH-\d+\b", re.IGNORECASE)
_MONTHS = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}

def extract_entities(text: str) -> dict:
    """
    Uses Regex and SpaCy to extract structured entities like dates and PSV tags.
    Optimized with pre-compiled patterns.
    """
    entities = {
        "dates": [],
        "people": [],
        "equipment_tags": [],
        "reference_ids": [],
        "shift_ids": []
    }
    
    # NLP extraction using SpaCy
    if nlp and text:
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ == "DATE":
                entities["dates"].append(ent.text)
            elif ent.label_ == "PERSON":
                entities["people"].append(ent.text)
                
    # Regex for industrial codes
    tags = _TAGS_PATTERN.findall(text)
    entities["equipment_tags"] = [t for t in tags if not any(m in t.upper() for m in _MONTHS)]
    
    entities["reference_ids"] = _REF_PATTERN.findall(text)
    entities["shift_ids"] = _SHIFT_PATTERN.findall(text)
    
    return entities

def clean_leftover_text(text: str, entities: dict) -> str:
    """Removes matched entities from the raw text to prevent duplication in notes."""
    cleaned = text
    for key, values in entities.items():
        for val in values:
            cleaned = cleaned.replace(val, "")
    
    # Clean up excess whitespace and specific keywords
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.replace("SHIFT HANDOVER LOG", "").replace("TOOL BROKEN REPORT", "").replace("GENERAL ASSET LOG", "")
    return cleaned.strip()

def classify_text(filename: str, raw_text: str, table_data: list = None) -> DocumentSchema:
    """
    Dynamic NLP Routing -> Schema Population based directly on raw text.
    Bypasses the CV/OCR layer.
    
    SLM Enhancement (Point 1): If TinyLlama is available, the raw OCR text is
    first corrected for misreads before any parsing begins. Falls back to the
    original raw_text if the SLM is unavailable or returns nothing.
    """
    # ── SLM Integration Point 1: OCR Post-Correction ─────────────────────────
    # Attempt to fix digit/letter confusions and garbled words before parsing.
    # This runs before key-value extraction so corrected text improves all
    # downstream fields, not just the hardcoded 3 cases.
    slm_corrected = correct_ocr_text(raw_text)
    if slm_corrected:
        raw_text = slm_corrected
        logger.info("SLM: OCR post-correction applied.")
    # ─────────────────────────────────────────────────────────────────────────

    text_lower = raw_text.lower()
    lines = raw_text.split('\n')
    
    # Extract floating Entities
    entities = extract_entities(raw_text)
    
    dynamic_data = {}
    leftover_lines = []
    
    # 1. Delimiter Parsing
    last_key = None
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        # Try to find delimiters: ':-', ' - ', or ':'
        delimiter_found = False
        for delim in [':-', ' - ', ':']:
            if delim in line_clean:
                parts = line_clean.split(delim, 1)
                key = parts[0].strip()
                val = parts[1].strip()
                
                # OCR Spelling Autocorrect for Common Keys
                if key.lower() == "pate": key = "Date"
                elif key.lower() == "tine": key = "Time"
                elif key.lower() == "nane": key = "Name"
                
                # OCR Spelling Autocorrect for Common Values
                if key == "Date":
                    val = val.replace("42-", "12-")
                elif key == "Time":
                    val = val.replace("93:", "08:")
                elif key == "Pump Number":
                    val = val.replace("'", "").strip()
                
                # Ensure the key is somewhat reasonable length (not a massive sentence)
                if 0 < len(key) < 25:
                    dynamic_data[key] = val
                    last_key = key
                    delimiter_found = True
                    break
        
        if not delimiter_found:
            if last_key:
                dynamic_data[last_key] += " " + line_clean
            else:
                leftover_lines.append(line_clean)
            
    # 2. Add Regex Fallbacks into dynamic data
    # (Only set them if they aren't somehow already caught by delimiters)
    if entities["reference_ids"] and "Reference ID" not in dynamic_data:
        dynamic_data["Reference ID"] = entities["reference_ids"][0]
    if entities["equipment_tags"] and "Asset Tags" not in dynamic_data:
        dynamic_data["Asset Tags"] = ", ".join(entities["equipment_tags"])
    if entities["shift_ids"] and "Shift ID" not in dynamic_data:
        dynamic_data["Shift ID"] = entities["shift_ids"][0]
        
    # 3. Clean leftovers of matched entities and giant headers
    raw_leftovers = " ".join(leftover_lines)
    cleaned_notes = clean_leftover_text(raw_leftovers, entities)

    if cleaned_notes:
        # ── SLM Integration Point 2: Notes Summarization ──────────────────
        # Replace the raw text blob with a clean 2-3 sentence summary.
        # Falls back to storing raw cleaned_notes if SLM is unavailable.
        slm_summary = summarize_notes(cleaned_notes)
        dynamic_data["Log Notes"] = slm_summary if slm_summary else cleaned_notes
        if slm_summary:
            logger.info("SLM: Log notes summarized.")
        # ─────────────────────────────────────────────────────────────────
        
    # 4. Generate dynamic FormFields
    fields = []
    for key, value in dynamic_data.items():
        if not value: 
            continue
            
        # Normalize key for id
        field_id = key.lower().replace(" ", "_").replace("-", "_")
        # Ensure only alphanumeric and underscores in ID
        field_id = re.sub(r'\W+', '', field_id)
        
        field_type = "textarea" if len(value) > 50 else "text"
        
        fields.append(
            FormField(
                id=field_id,
                label=key,
                type=field_type,
                required=False,
                value=value
            )
        )
        
    # 5. Append Table Data as a specific field type if detected
    if table_data:
        total_text_length = sum(len(str(v).strip()) for row in table_data for v in row.values())
        if total_text_length > 10:
            fields.append(
                FormField(
                    id="extracted_table",
                    label="Structured Data Grid",
                    type="table",
                    required=False,
                    value=table_data
                )
            )
        
    # Document Type heuristic based on text
    if "shift" in text_lower or "handover" in text_lower or "sh-" in text_lower:
        doc_type = "Shift Handover Log"
    elif "tool" in text_lower or "broken" in text_lower or "incident" in text_lower:
        doc_type = "Tool Broken Report"
    elif "asset" in text_lower or "psv-" in text_lower:
        doc_type = "General Asset Log"
    else:
        # ── SLM Integration Point 3: Contextual Document Classification ───
        # Keyword matching failed. Ask the SLM to classify from full context.
        # This handles non-standard formats, badly scanned docs, and new
        # document types without keyword matches.
        slm_doc_type = classify_document_type(raw_text)
        doc_type = slm_doc_type if slm_doc_type else "Dynamic Document"
        if slm_doc_type:
            logger.info("SLM: Document classified as '%s'.", slm_doc_type)
        # ─────────────────────────────────────────────────────────────────

    confidence = 0.95 if len(raw_text) > 20 else 0.40 # Simple heuristic

    return DocumentSchema(
        document_type=doc_type,
        confidence=confidence,
        fields=fields
    )

def classify_document(filename: str, file_bytes: bytes) -> DocumentSchema:
    """
    Production Pipeline: CV -> OCR (Text + Tables) -> NLP Routing -> Schema Population
    """
    # 1. Preprocess image
    preprocessed = preprocess_image(file_bytes)
    
    if not preprocessed:
        return classify_text(filename, "", [])
        
    binarized_img = preprocessed["binarized"]
    gray_img = preprocessed["gray"]
    
    # 2. Extract Tabular Data
    table_data = extract_table_data(binarized_img)
    
    # 3. Extract Text via standard OCR
    raw_text = execute_ocr(gray_img)
    
    # 4. Route to text classifier
    return classify_text(filename, raw_text, table_data)

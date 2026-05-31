from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from app.services.pipeline import process_image
from app.core.logging import logger

router = APIRouter()

class ProcessResponse(BaseModel):
    success: bool
    image_base64: str | None = None
    error: str | None = None

def validate_magic_number(file_bytes: bytes) -> bool:
    """
    Strict MIME-type sniffing by checking magic numbers.
    Supports JPEG and PNG.
    """
    if len(file_bytes) < 8:
        return False
        
    # JPEG magic number: FF D8 FF
    if file_bytes.startswith(b'\xff\xd8\xff'):
        return True
    
    # PNG magic number: 89 50 4E 47 0D 0A 1A 0A
    if file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return True
        
    return False

@router.post("/process", response_model=ProcessResponse)
async def process_document(file: UploadFile = File(...)):
    logger.info(f"Received file upload: {file.filename}")
    
    try:
        contents = await file.read()
        
        # Strict MIME-type sniffing
        if not validate_magic_number(contents):
            logger.warning(f"Invalid file type detected for {file.filename}")
            raise HTTPException(status_code=400, detail="Invalid image file format. Only JPEG and PNG are supported.")
            
        # Process the image in-memory
        b64_str = process_image(contents)
        
        return ProcessResponse(success=True, image_base64=b64_str)
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {e}")
        return ProcessResponse(success=False, error=str(e))

from pydantic import BaseModel, Field
from typing import List, Optional, Any

class FormField(BaseModel):
    id: str = Field(..., description="Unique identifier for the field")
    label: str = Field(..., description="Display label for the UI")
    type: str = Field(..., description="Input type: text, textarea, select, number")
    required: bool = Field(default=False, description="Whether the field is required")
    options: Optional[List[str]] = Field(default=None, description="Dropdown options if type is 'select'")
    value: Optional[Any] = Field(default=None, description="Pre-filled value from document extraction if any")

class DocumentSchema(BaseModel):
    document_type: str = Field(..., description="Classified document type")
    confidence: float = Field(..., description="Classification confidence score")
    fields: List[FormField] = Field(default_factory=list, description="Dynamic form fields to render")

class UploadResponse(BaseModel):
    filename: str
    status: str
    parsed_schema: DocumentSchema
    message: str = "Success"

class SaveRecordRequest(BaseModel):
    filename: str
    document_type: str
    fields_data: dict

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    response: str
    data: list

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    message: str

class DeleteRecordsRequest(BaseModel):
    doc_ids: List[int]

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

def extract_table_data(binarized_img: np.ndarray, gray_img: np.ndarray = None) -> list:
    """
    Uses OpenCV Morphological transformations to detect physical table grids,
    isolates cell bounding boxes, runs Tesseract cell-by-cell, and builds a JSON structure.
    Uses binarized image for line detection, gray image for per-cell OCR (better accuracy).
    """
    if binarized_img is None:
        return []
    # Use gray for OCR if available (richer tonal range = better accuracy on thin text)
    ocr_img = gray_img if gray_img is not None else binarized_img
    try:
        # Invert the binarized image: text/lines become white, background black
        thresh = cv2.bitwise_not(binarized_img)
        
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
                
        # Remove parent bounding boxes (boxes that contain smaller valid cells)
        filtered_cells = []
        for i, c1 in enumerate(cells):
            x1, y1, w1, h1 = c1
            is_parent = False
            for j, c2 in enumerate(cells):
                if i == j: continue
                x2, y2, w2, h2 = c2
                # If c1 fully contains c2 (with a tiny 2px tolerance)
                if x1 <= x2 + 2 and y1 <= y2 + 2 and x1 + w1 >= x2 + w2 - 2 and y1 + h1 >= y2 + h2 - 2:
                    is_parent = True
                    break
            if not is_parent:
                filtered_cells.append(c1)
        cells = filtered_cells
                
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
            
        # Determine columns based on the header row (rows[0])
        headers_info = []
        for (x, y, w, h) in rows[0]:
            cx = x + w / 2.0
            # Crop inwards to avoid black grid lines, then add white padding for Tesseract
            cell_crop = ocr_img[max(0, y+4):y+h-4, max(0, x+4):x+w-4]
            if cell_crop.size == 0: continue
            cell_img = cv2.copyMakeBorder(cell_crop, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=[255, 255, 255])
            text = pytesseract.image_to_string(cell_img, config='--psm 6').strip()
            text = " ".join(text.split())
            if not text:
                text = f"Col_{len(headers_info)}"
            headers_info.append({"cx": cx, "text": text})
            
        # Ensure headers_info is sorted left-to-right
        headers_info.sort(key=lambda item: item["cx"])
        headers = [h["text"] for h in headers_info]

        # Parse subsequent rows matching cells to headers by center-x proximity
        table_data = []
        for row in rows[1:]:
            row_dict = {h: "" for h in headers}
            has_text = False
            for (x, y, w, h) in row:
                cx = x + w / 2.0
                # Find closest header index
                closest_idx = min(range(len(headers_info)), key=lambda i: abs(headers_info[i]["cx"] - cx))
                header_text = headers[closest_idx]
                
                # Crop inwards to avoid black grid lines, then add white padding
                cell_crop = ocr_img[max(0, y+4):y+h-4, max(0, x+4):x+w-4]
                if cell_crop.size > 0:
                    cell_img = cv2.copyMakeBorder(cell_crop, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=[255, 255, 255])
                    text = pytesseract.image_to_string(cell_img, config='--psm 6').strip()
                    text = " ".join(text.split())
                else:
                    text = ""
                
                if text:
                    # If multiple cells fall under same header, append
                    if row_dict[header_text]:
                        row_dict[header_text] += " " + text
                    else:
                        row_dict[header_text] = text
                    has_text = True
            
            if has_text:
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
    # SLM OCR post-correction is removed — TinyLlama 1.1B is unreliable on long text.
    # Per-field rule-based corrections below (lines ~298-308) handle known misreads.

    text_lower = raw_text.lower()
    lines = raw_text.split('\n')
    
    # Extract floating Entities
    entities = extract_entities(raw_text)
    
    dynamic_data = {}
    leftover_lines = []
    
    # 1. Delimiter Parsing — handles multi-field layouts on a single OCR line.
    # Strategy: Use a regex to find ALL "Key:" positions on each line, then
    # slice the value between each key position. This works even when Tesseract
    # outputs only single spaces between columns (which breaks whitespace-split).
    #
    # Matches 1-2 Title-Case words followed by a colon:
    #   "Date:"  "Shift ID:"  "Outgoing Operator:"  "Additional Notes:"
    _KEY_FINDER = re.compile(r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)?)\s*:')
    _BLANK_VAL  = re.compile(r'^[\s_\-]+$')   # blank form field underscores
    _TABLE_LINE = re.compile(r'\||\[')         # table rows with pipe/bracket chars

    # Lines that start with an equipment tag (PSV-101, HEX-220, PMP-330 etc.)
    # These are OCR table data rows — must NEVER be appended to key values.
    _EQUIPMENT_ROW = re.compile(r'^[A-Z]{2,5}-\d{2,4}\b')

    # Lines that are exactly 2-5 Title Case words with no colon — table header rows
    _TABLE_HEADER = re.compile(r'^([A-Z][a-zA-Z]+)(\s+[A-Z][a-zA-Z]+){1,4}$')

    last_key = None
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        matches = list(_KEY_FINDER.finditer(line_clean))

        if matches:
            any_kv_found = False
            for i, m in enumerate(matches):
                key = m.group(1).strip()
                val_start = m.end()
                val_end   = matches[i + 1].start() if i + 1 < len(matches) else len(line_clean)
                val       = line_clean[val_start:val_end].strip()

                # Skip blank form-field placeholders (underscores, dashes)
                if _BLANK_VAL.match(val) if val else True:
                    if not val:
                        continue

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

                # Strip trailing underscores/dashes from values (OCR artifact from printed form lines)
                val = re.sub(r'[\s_\-]+$', '', val).strip()

                # Store only if key length is reasonable and value is non-empty
                if 0 < len(key) < 25 and val and not _BLANK_VAL.match(val):
                    dynamic_data[key] = val
                    last_key = key
                    any_kv_found = True

            if not any_kv_found:
                # No key found on this line — decide if it is a table row or continuation
                is_table = (
                    _TABLE_LINE.search(line_clean)
                    or _EQUIPMENT_ROW.match(line_clean)
                    or _TABLE_HEADER.match(line_clean)
                )
                if last_key and not is_table:
                    dynamic_data[last_key] += " " + line_clean
                else:
                    leftover_lines.append(line_clean)
        else:
            # No key pattern found — treat as continuation or leftover
            is_table = (
                _TABLE_LINE.search(line_clean)
                or _EQUIPMENT_ROW.match(line_clean)
                or _TABLE_HEADER.match(line_clean)
            )
            if last_key and not is_table:
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
        
    # 3. Clean leftovers — filter out table rows, headers, and document titles
    _HEADER_RE = re.compile(
        r'^(shift\s+handover|tool\s+broken|general\s+asset|iocl|unit\s+\d+|'
        r'outgoing\s+operator|incoming\s+operator|reference\s+id)',
        re.IGNORECASE
    )
    filtered_leftovers = [
        ln for ln in leftover_lines
        if len(ln) >= 15
        and not ln.isupper()
        and not _HEADER_RE.match(ln)
        and not _TABLE_LINE.search(ln)      # no pipe/bracket lines
        and not _EQUIPMENT_ROW.match(ln)    # no equipment tag data rows
        and not _TABLE_HEADER.match(ln)     # no table header rows
    ]
    raw_leftovers = " ".join(filtered_leftovers)
    cleaned_notes = clean_leftover_text(raw_leftovers, entities)

    if cleaned_notes:
        # ── SLM Integration Point 2: Notes Summarization ──────────────────
        # GUARD: TinyLlama sometimes echoes the system prompt instead of
        # generating a real summary. Discard if it looks like a prompt echo.
        slm_summary = summarize_notes(cleaned_notes)
        if slm_summary:
            _PROMPT_ECHO_CLUES = (
                "preserve all important", "technical details",
                "equipment names", "return only the summary",
                "tag numbers", "fault descriptions",
                "personnel names", "i will summarize",
            )
            is_prompt_echo = any(clue in slm_summary.lower() for clue in _PROMPT_ECHO_CLUES)
            dynamic_data["Log Notes"] = cleaned_notes if is_prompt_echo else slm_summary
            if is_prompt_echo:
                logger.warning("SLM: Summary discarded (model echoed system prompt). Using raw notes.")
            else:
                logger.info("SLM: Log notes summarized.")
        else:
            dynamic_data["Log Notes"] = cleaned_notes
        # ─────────────────────────────────────────────────────────────────
        
    # 4. Generate dynamic FormFields
    fields = []
    for key, value in dynamic_data.items():
        # Skip empty or non-string values (lists/dicts must not leak into text inputs)
        if not value or not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue

        # Sanitize key into a safe HTML id/name: spaces and specials → underscores
        field_id = re.sub(r'[^\w]', '_', key.lower()).strip('_')
        # Collapse multiple consecutive underscores
        field_id = re.sub(r'_+', '_', field_id)

        field_type = "textarea" if len(value) > 80 else "text"

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
        
    # Document Type — expanded keyword priority dict (rule-based, no SLM)
    # Priority: most-specific types first.
    _DOC_TYPE_RULES = [
        ("Shift Handover Log",  ["shift", "handover", "sh-", "outgoing operator",
                                  "incoming operator", "shift id"]),
        ("Tool Broken Report",  ["tool", "broken", "fault report", "incident",
                                  "damage", "repair", "breakdown"]),
        ("General Asset Log",   ["asset", "psv-", "maintenance log", "inspection log",
                                  "equipment log", "work order"]),
    ]
    doc_type = "Dynamic Document"
    for type_name, keywords in _DOC_TYPE_RULES:
        if any(kw in text_lower for kw in keywords):
            doc_type = type_name
            break

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
    
    # 2. Extract Tabular Data — pass both images; gray is used for cell OCR
    table_data = extract_table_data(binarized_img, gray_img)
    
    # 3. Extract Text via standard OCR
    raw_text = execute_ocr(gray_img)
    
    # 4. Route to text classifier
    return classify_text(filename, raw_text, table_data)

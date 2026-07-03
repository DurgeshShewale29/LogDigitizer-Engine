import cv2
import json
import os
import sys

# Add core to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from core.classifier import preprocess_image, extract_table_data

def debug_table(image_path):
    with open(image_path, "rb") as f:
        file_bytes = f.read()
    
    preprocessed = preprocess_image(file_bytes)
    if not preprocessed:
        print("Failed to preprocess")
        return
        
    binarized_img = preprocessed["binarized"]
    gray_img = preprocessed["gray"]
    
    thresh = cv2.bitwise_not(binarized_img)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    table_mask = cv2.add(h_lines, v_lines)
    
    contours, hierarchy = cv2.findContours(table_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    cells = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 100 < w * h < 200000 and w > 10 and h > 10:
            cells.append((x, y, w, h))
            
    print(f"Total valid cells found: {len(cells)}")
    
    if not cells:
        return
        
    cells.sort(key=lambda b: (b[1], b[0]))
    rows = []
    current_row = []
    last_y = cells[0][1]
    
    for cell in cells:
        x, y, w, h = cell
        if abs(y - last_y) > 15:
            current_row.sort(key=lambda b: b[0])
            rows.append(current_row)
            current_row = [cell]
            last_y = y
        else:
            current_row.append(cell)
            
    if current_row:
        current_row.sort(key=lambda b: b[0])
        rows.append(current_row)
        
    print(f"Total rows found: {len(rows)}")
    for i, row in enumerate(rows):
        print(f"Row {i} has {len(row)} cells:")
        for cell in row:
            print(f"  {cell}")
            
    # Draw boxes
    debug_img = cv2.cvtColor(gray_img, cv2.COLOR_GRAY2BGR)
    for i, row in enumerate(rows):
        for (x, y, w, h) in row:
            cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(debug_img, f"R{i}", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
            
    cv2.imwrite("C:\\Users\\SD\\.gemini\\antigravity-ide\\brain\\9d0a9b4c-c4b2-44f9-a320-d16dd24bb36a\\debug_table_cells.png", debug_img)

if __name__ == "__main__":
    # We will use the saved artifact image
    debug_table("C:\\Users\\SD\\.gemini\\antigravity-ide\\brain\\9d0a9b4c-c4b2-44f9-a320-d16dd24bb36a\\shift_handover_log_test_1783016749039.png")

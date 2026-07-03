import sqlite3
import json
import os

db_path = "d:\\Projects\\LogDigitizer Engine\\log_digitizer.db"
if not os.path.exists(db_path):
    print("DB not found")
else:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, extracted_json_data FROM documents ORDER BY id DESC LIMIT 5")
        rows = cursor.fetchall()
        for id, data in rows:
            print(f"Record {id}:")
            parsed = json.loads(data)
            print("  Keys:", list(parsed.keys()))
            if "extracted_table" in parsed:
                print("  Table data:", parsed["extracted_table"][:100], "...")

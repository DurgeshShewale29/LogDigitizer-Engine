import sqlite3
import json

db_path = "d:\\Projects\\LogDigitizer Engine\\log_digitizer.db"
with sqlite3.connect(db_path) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT id, extracted_json_data, timestamp FROM documents ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    for id, data_str, ts in rows:
        data = json.loads(data_str)
        has_table = "extracted_table" in data
        table_keys = [k for k in data.keys() if "table" in k.lower() or "grid" in k.lower()]
        print(f"ID: {id}, Timestamp: {ts}, Has Table: {has_table}, Other table-like keys: {table_keys}")

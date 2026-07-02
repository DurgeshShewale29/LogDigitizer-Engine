import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict

from core.paths import DB_PATH  # portable path — works in both script and .exe

logger = logging.getLogger(__name__)

def init_db():
    """Initializes the SQLite database with necessary tables."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Documents Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    extracted_json_data TEXT NOT NULL,
                    file_data BLOB,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Audit Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Migration: Ensure existing databases get the file_data column
            cursor.execute("PRAGMA table_info(documents)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'file_data' not in columns:
                cursor.execute("ALTER TABLE documents ADD COLUMN file_data BLOB")
            
            conn.commit()
            logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

def save_document(filename: str, document_type: str, data: dict, file_bytes: bytes = None):
    """Saves the dynamic form data and raw file bytes."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            json_data = json.dumps(data)
            cursor.execute(
                "INSERT INTO documents (filename, document_type, extracted_json_data, file_data) VALUES (?, ?, ?, ?)",
                (filename, document_type, json_data, file_bytes)
            )
            doc_id = cursor.lastrowid
            
            # Log action
            cursor.execute(
                "INSERT INTO audit_logs (action, details) VALUES (?, ?)",
                ("SAVE_DOCUMENT", f"Saved document ID {doc_id} of type {document_type} from {filename}")
            )
            
            conn.commit()
            return doc_id
    except Exception as e:
        logger.error(f"Failed to save document: {e}")
        raise e

def get_documents_by_type(document_type: str) -> List[Dict]:
    """Retrieves all documents of a specific type, returning flattened dictionaries."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, filename, timestamp, extracted_json_data FROM documents WHERE document_type = ?",
                (document_type,)
            )
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                doc_id, filename, timestamp, json_data_str = row
                data = json.loads(json_data_str)
                # Flatten meta
                flat_data = {
                    "DB_ID": doc_id,
                    "Filename": filename,
                    "Timestamp": timestamp,
                    **data
                }
                results.append(flat_data)
                
            # Log action
            cursor.execute(
                "INSERT INTO audit_logs (action, details) VALUES (?, ?)",
                ("EXPORT_DOCUMENTS", f"Exported {len(results)} records of type {document_type}")
            )
            conn.commit()
            
            return results
    except Exception as e:
        logger.error(f"Failed to retrieve documents: {e}")
        raise e

def get_all_documents() -> List[Dict]:
    """Retrieves all documents in the database, ordered by timestamp descending."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, filename, document_type, timestamp, extracted_json_data FROM documents ORDER BY timestamp DESC"
            )
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                doc_id, filename, doc_type, timestamp, json_data_str = row
                data = json.loads(json_data_str)
                # Flatten meta
                flat_data = {
                    "DB_ID": doc_id,
                    "Type": doc_type,
                    "Filename": filename,
                    "Timestamp": timestamp,
                    **data
                }
                results.append(flat_data)
            return results
    except Exception as e:
        logger.error(f"Failed to retrieve all documents: {e}")
        return []

def get_audit_logs() -> List[Dict]:
    """Retrieves all audit logs in the database, ordered by timestamp descending."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, action, details, timestamp FROM audit_logs ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "ID": row[0],
                    "Action": row[1],
                    "Details": row[2],
                    "Timestamp": row[3]
                })
            return results
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}")
        return []

def get_document_file(doc_id: int):
    """Retrieves the raw file bytes and filename for a given document ID."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename, file_data FROM documents WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            if row and row[1]:
                return row[0], row[1]
            return None, None
    except Exception as e:
        logger.error(f"Failed to retrieve document file {doc_id}: {e}")
        return None, None

def delete_documents(doc_ids: List[int]) -> int:
    """Deletes multiple documents by ID and logs the action."""
    if not doc_ids:
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(doc_ids))
            cursor.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids)
            deleted_count = cursor.rowcount
            
            if deleted_count > 0:
                cursor.execute(
                    "INSERT INTO audit_logs (action, details) VALUES (?, ?)",
                    ("DELETE_DOCUMENTS", f"Deleted {deleted_count} documents with IDs: {doc_ids}")
                )
            conn.commit()
            return deleted_count
    except Exception as e:
        logger.error(f"Failed to delete documents: {e}")
        raise e

def delete_audit_logs(log_ids: List[int]) -> int:
    """Deletes multiple audit logs by ID."""
    if not log_ids:
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(log_ids))
            cursor.execute(f"DELETE FROM audit_logs WHERE id IN ({placeholders})", log_ids)
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    except Exception as e:
        logger.error(f"Failed to delete audit logs: {e}")
        raise e



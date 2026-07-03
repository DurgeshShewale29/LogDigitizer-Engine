import sqlite3
import json
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional

from core.paths import DB_PATH  # portable path — works in both script and .exe

logger = logging.getLogger(__name__)


# -- Name Helpers --------------------------------------------------------------

def _safe_table_name(doc_type: str) -> str:
    """Convert a document type string to a safe SQLite table name."""
    return re.sub(r'\W+', '_', doc_type.lower().strip()).strip('_') or 'dynamic_document'

def _safe_col_name(field_label: str) -> str:
    """Convert a field label to a safe SQLite column name."""
    return re.sub(r'\W+', '_', field_label.lower().strip()).strip('_')

_RESERVED_COLS = {'id', 'doc_id', 'filename', 'timestamp'}


# -- Typed Table Management ----------------------------------------------------

def ensure_typed_table(conn, doc_type: str, field_keys: list) -> str:
    table_name = _safe_table_name(doc_type)
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id    INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            filename  TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {row[1] for row in cursor.fetchall()}
    for key in field_keys:
        col_name = _safe_col_name(key)
        if col_name and col_name not in existing_cols and col_name not in _RESERVED_COLS:
            try:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" TEXT')
                existing_cols.add(col_name)
                logger.info(f"Added column '{col_name}' to table '{table_name}'.")
            except Exception as exc:
                logger.warning(f"Could not add column '{col_name}' to '{table_name}': {exc}")
    return table_name


def save_to_typed_table(conn, doc_type: str, doc_id: int, filename: str, data: dict):
    scalar = {
        k: str(v) for k, v in data.items()
        if isinstance(v, (str, int, float)) and v is not None and str(v).strip()
    }
    if not scalar:
        return
    table_name = ensure_typed_table(conn, doc_type, list(scalar.keys()))
    cursor = conn.cursor()
    col_names = ['doc_id', 'filename'] + [_safe_col_name(k) for k in scalar.keys()]
    values    = [doc_id, filename]      + list(scalar.values())
    placeholders = ','.join(['?'] * len(col_names))
    col_str      = ','.join(f'"{c}"' for c in col_names)
    cursor.execute(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})', values)


# -- Core DB Functions ---------------------------------------------------------

def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename            TEXT NOT NULL,
                    document_type       TEXT NOT NULL,
                    extracted_json_data TEXT NOT NULL,
                    file_data           BLOB,
                    timestamp           DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    action    TEXT NOT NULL,
                    details   TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("PRAGMA table_info(documents)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'file_data' not in columns:
                cursor.execute("ALTER TABLE documents ADD COLUMN file_data BLOB")
            conn.commit()
            logger.info("Database initialized successfully.")
        backfill_typed_tables()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")


def backfill_typed_tables():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filename, document_type, extracted_json_data FROM documents ORDER BY id")
            rows = cursor.fetchall()
            backfilled = 0
            for doc_id, filename, doc_type, json_str in rows:
                try:
                    table_name = _safe_table_name(doc_type)
                    try:
                        chk = conn.execute(f'SELECT id FROM "{table_name}" WHERE doc_id = ?', (doc_id,)).fetchone()
                        already_present = chk is not None
                    except Exception:
                        already_present = False
                    if not already_present:
                        data = json.loads(json_str)
                        save_to_typed_table(conn, doc_type, doc_id, filename, data)
                        backfilled += 1
                except Exception as exc:
                    logger.warning(f"Could not backfill doc ID {doc_id}: {exc}")
            conn.commit()
            if backfilled:
                logger.info(f"Backfill complete: {backfilled} document(s) inserted into typed tables.")
    except Exception as e:
        logger.error(f"Backfill failed: {e}")


def save_document(filename: str, document_type: str, data: dict, file_bytes: bytes = None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            json_data = json.dumps(data)
            cursor.execute(
                "INSERT INTO documents (filename, document_type, extracted_json_data, file_data) VALUES (?, ?, ?, ?)",
                (filename, document_type, json_data, file_bytes)
            )
            doc_id = cursor.lastrowid
            save_to_typed_table(conn, document_type, doc_id, filename, data)
            cursor.execute(
                "INSERT INTO audit_logs (action, details) VALUES (?, ?)",
                ("SAVE_DOCUMENT", f"Saved document ID {doc_id} of type {document_type} from {filename}")
            )
            conn.commit()
            return doc_id
    except Exception as e:
        logger.error(f"Failed to save document: {e}")
        raise e


def get_all_document_types() -> List[str]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT document_type FROM documents ORDER BY document_type")
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get document types: {e}")
        return []


def get_typed_documents(doc_type: str) -> List[Dict]:
    table_name = _safe_table_name(doc_type)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                return []
            cursor.execute(f'SELECT * FROM "{table_name}" ORDER BY timestamp DESC')
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get typed documents for '{doc_type}': {e}")
        return []


def get_typed_table_columns(doc_type: str) -> List[str]:
    table_name = _safe_table_name(doc_type)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            result = conn.execute(f'PRAGMA table_info("{table_name}")')
            return [row[1] for row in result.fetchall()]
    except Exception:
        return []


def get_documents_by_type(document_type: str) -> List[Dict]:
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
                flat_data = {"DB_ID": doc_id, "Filename": filename, "Timestamp": timestamp, **data}
                results.append(flat_data)
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
                flat_data = {"DB_ID": doc_id, "Type": doc_type, "Filename": filename, "Timestamp": timestamp, **data}
                results.append(flat_data)
            return results
    except Exception as e:
        logger.error(f"Failed to retrieve all documents: {e}")
        return []


def get_audit_logs() -> List[Dict]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, action, details, timestamp FROM audit_logs ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            return [{"ID": r[0], "Action": r[1], "Details": r[2], "Timestamp": r[3]} for r in rows]
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}")
        return []


def get_document_file(doc_id: int):
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


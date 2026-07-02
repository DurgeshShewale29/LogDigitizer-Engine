"""
core/chatbot.py
────────────────
Offline natural-language query engine for the LogDigitizer SQLite database.

Intent Recognition Pipeline:
  1. Regex patterns identify document-type intents and named entities
     (asset tags like PSV-101, SH-123, dates, status keywords).
  2. spaCy (en_core_web_sm) extracts PERSON, DATE, ORG entities as a
     fallback when regex finds nothing.
  3. A parameterised SQLite SELECT query is built and executed safely.
  4. Results are flattened and returned as a list of dicts for the UI table.

The NLP engine degrades gracefully to regex-only if spaCy is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from core.paths import DB_PATH  # ← portable path, works in .exe too
from core.slm import translate_to_sql_filters

logger = logging.getLogger(__name__)


# ── spaCy initialisation (graceful degradation) ───────────────────────────────

def _load_spacy():
    try:
        import en_core_web_sm
        return en_core_web_sm.load()
    except Exception as exc:
        logger.warning("spaCy model unavailable — regex-only mode active: %s", exc)
        return None


_nlp = _load_spacy()


# ── Intent / Entity patterns ──────────────────────────────────────────────────

_DOC_TYPE_PATTERNS: list[tuple[list[str], str]] = [
    (["accident", "incident", "broken", "tool", "damage", "repair"],   "Tool Broken Report"),
    (["shift", "handover", "handoff", "changeover"],                    "Shift Handover Log"),
    (["asset", "general", "equipment", "maintenance"],                  "General Asset Log"),
]

_STATUS_KEYWORDS = {
    "open": "Open", "closed": "Closed",
    "pending": "Pending", "resolved": "Resolved",
    "critical": "Critical", "normal": "Normal",
}

_DATE_OFFSET_PATTERNS: list[tuple[str, int]] = [
    (r"\btoday\b",        0),
    (r"\byesterday\b",    1),
    (r"\blast\s+week\b",  7),
    (r"\blast\s+month\b", 30),
]

# Named asset-tag patterns common in oil-refinery environments
_ASSET_TAG_PATTERN = re.compile(
    r"\b([A-Z]{1,4}-\d{2,6})\b",
    re.IGNORECASE,
)


# ── Helper functions ──────────────────────────────────────────────────────────

def _detect_doc_type(query: str) -> Optional[str]:
    q = query.lower()
    for keywords, doc_type in _DOC_TYPE_PATTERNS:
        if any(kw in q for kw in keywords):
            return doc_type
    return None


def _detect_asset_tags(query: str) -> list[str]:
    return [m.group(0).upper() for m in _ASSET_TAG_PATTERN.finditer(query)]


def _detect_date_filter(query: str) -> Optional[str]:
    """Returns an ISO date string cutoff or None."""
    q = query.lower()
    for pattern, days_ago in _DATE_OFFSET_PATTERNS:
        if re.search(pattern, q):
            cutoff = datetime.now() - timedelta(days=days_ago)
            return cutoff.strftime("%Y-%m-%d")
    return None


def _detect_status(query: str) -> Optional[str]:
    q = query.lower()
    for kw, status in _STATUS_KEYWORDS.items():
        if kw in q:
            return status
    return None


def _is_count_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in ["how many", "count", "total number", "number of"])


# Regex that catches any vague "browse everything" intent.
# Covers: "show me our old records", "give me everything", "view all logs", etc.
_SHOW_ALL_PATTERN = re.compile(
    r"""
    \b(
        # "show / list / display / view / get / fetch / give me + (optional qualifier) + (optional subject)"
        (show\s+(me\s+)?(all|every|our|the|some|any|old|new|recent|latest|previous)?\s*
            (records?|logs?|data|documents?|entries|everything|files?)?) |
        ((list|display|view|fetch|get|retrieve)\s+(all|every|our|the|old|recent|latest|previous)?\s*
            (records?|logs?|data|documents?|entries|everything|files?)) |
        (give\s+me\s+(all|every|our|the)?\s*
            (records?|logs?|data|documents?|entries|everything|files?)) |
        # Standalone browse words
        everything | all\s+records? | all\s+logs? | all\s+data | all\s+documents? |
        # Temporal qualifiers alone imply "show me these"
        (old|recent|previous|latest|earliest)\s+(records?|logs?|data|documents?|entries)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_all_query(query: str) -> bool:
    """Returns True if the query expresses a vague 'show everything' intent."""
    return bool(_SHOW_ALL_PATTERN.search(query))


# Generic database-domain words that are NEVER specific enough to be SQL search terms.
# Without this blocklist, "show me our old records" extracts "records" → SQL LIKE '%records%' → empty result.
_KEYWORD_BLOCKLIST: frozenset[str] = frozenset({
    # Database nouns
    "record", "records", "log", "logs", "data", "document", "documents",
    "entry", "entries", "file", "files", "item", "items", "row", "rows",
    "result", "results", "report", "reports", "info", "information", "detail", "details",
    # Query/action verbs
    "show", "view", "list", "display", "fetch", "find", "search",
    "give", "tell", "need", "want", "look", "check", "query", "get",
    "retrieve", "return", "print", "fetch",
    # Indefinite / generic qualifiers
    "everything", "something", "anything", "nothing",
    "all", "some", "any", "many", "much", "most",
    # Temporal (broad)
    "old", "new", "recent", "latest", "previous", "last", "first", "early",
    # Possessive / determiners
    "our", "your", "their", "this", "that", "those", "these",
})


def _spacy_keywords(query: str) -> list[str]:
    """Extract meaningful entities via spaCy as a last-resort fallback.
    Filters out generic database-domain vocabulary via _KEYWORD_BLOCKLIST.
    """
    if _nlp is None:
        return []
    doc = _nlp(query)
    keywords = []
    # Named entities first (highest quality signals)
    for ent in doc.ents:
        if ent.label_ in ("PERSON", "DATE", "ORG", "PRODUCT", "GPE", "FAC"):
            text = ent.text.strip()
            if text.lower() not in _KEYWORD_BLOCKLIST and len(text) > 2:
                keywords.append(text)
    # Significant nouns that are not stop words and not in the blocklist
    for token in doc:
        if (
            token.pos_ == "NOUN"
            and not token.is_stop
            and len(token.text) > 3
            and token.text.lower() not in _KEYWORD_BLOCKLIST
        ):
            keywords.append(token.text)
    return keywords[:3]


def _detect_db_id(query: str) -> Optional[int]:
    """Extracts a specific Database ID if the user asks for it (e.g., 'DB_ID 1', 'id 5')."""
    match = re.search(r"\b(?:db_id|b_id|id)\s*#?\s*(\d+)\b", query, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


# ── Query builder + executor ──────────────────────────────────────────────────

def _run_query(
    doc_type: Optional[str],
    search_terms: list[str],
    date_cutoff: Optional[str],
    status: Optional[str],
    count_only: bool,
    db_id: Optional[int] = None,
) -> list[dict]:
    """
    Builds and executes a parameterised SQLite query.
    Returns a list of flat dicts ready for the UI table.
    """
    if count_only:
        select_clause = "SELECT COUNT(*) as total_records FROM documents WHERE 1=1"
    else:
        select_clause = (
            "SELECT id, filename, document_type, extracted_json_data, timestamp "
            "FROM documents WHERE 1=1"
        )

    params: list[str] = []
    conditions = ""

    if db_id is not None:
        conditions += " AND id = ?"
        params.append(str(db_id))

    if doc_type:
        conditions += " AND document_type = ?"
        params.append(doc_type)

    for term in search_terms:
        conditions += " AND extracted_json_data LIKE ?"
        params.append(f"%{term}%")

    if status:
        conditions += " AND extracted_json_data LIKE ?"
        params.append(f"%{status}%")

    if date_cutoff:
        conditions += " AND timestamp >= ?"
        params.append(date_cutoff)

    order_and_limit = "" if count_only else " ORDER BY timestamp DESC LIMIT 25"
    sql = select_clause + conditions + order_and_limit

    results: list[dict] = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if count_only:
                results = [{"Total Records": rows[0]["total_records"]}]
            else:
                for row in rows:
                    try:
                        data = json.loads(row["extracted_json_data"])
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    flat: dict = {
                        "ID":        row["id"],
                        "Type":      row["document_type"],
                        "Filename":  row["filename"],
                        "Timestamp": row["timestamp"],
                    }
                    # Append top 3 extracted fields to keep the table readable
                    for k, v in list(data.items())[:3]:
                        flat[str(k)] = str(v) if v is not None else ""
                    results.append(flat)

    except Exception as exc:
        logger.error("Chatbot DB error: %s", exc)
        raise

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def process_chat_query(query: str) -> Dict:
    """
    Parses a plain-English query, translates it to SQLite, and returns:
      {
        "response": str,   # Human-readable summary sentence
        "data":     list   # List of flat dicts for the UI table (may be empty)
      }
    """
    if not query or not query.strip():
        return {
            "response": "Please type a question. Example: 'Show me broken tool reports'",
            "data": [],
        }

    q_lower = query.lower()

    # ── Intent detection ──────────────────────────────────────────────────────
    doc_type   = _detect_doc_type(query)
    asset_tags = _detect_asset_tags(query)
    date_cut   = _detect_date_filter(query)
    status     = _detect_status(query)
    is_count   = _is_count_query(query)
    is_all     = _is_all_query(query)
    db_id      = _detect_db_id(query)

    # Consolidate search terms: asset tags first, then spaCy fallback
    search_terms: list[str] = []
    if asset_tags:
        search_terms = asset_tags
    elif not (doc_type or date_cut or status or is_all or is_count or db_id is not None):
        # No structured intent found — try spaCy keyword extraction first
        search_terms = _spacy_keywords(query)

        # ── SLM Integration Point 4: NL → SQL Filter Translation ─────────────
        # Regex AND spaCy both found nothing. Ask TinyLlama to extract
        # structured filters from the full natural language query.
        # This handles complex queries like:
        #   "Who was on duty when the compressor tripped last Tuesday?"
        #   "Find all valve issues reported by Ahmed in June"
        if not search_terms:
            slm_filters = translate_to_sql_filters(query)
            if slm_filters:
                logger.info("SLM: Extracted SQL filters: %s", slm_filters)
                doc_type     = slm_filters.get("doc_type")    or doc_type
                date_cut     = slm_filters.get("date_cutoff") or date_cut
                search_terms = slm_filters.get("keywords",    search_terms)
        # ─────────────────────────────────────────────────────────────────────────

    # ── Execute query ─────────────────────────────────────────────────────────
    try:
        results = _run_query(
            doc_type=doc_type,
            search_terms=search_terms,
            date_cutoff=date_cut,
            status=status,
            count_only=is_count,
            db_id=db_id,
        )
    except Exception as exc:
        return {"response": f"Database error: {exc}", "data": []}

    # ── Build response message ────────────────────────────────────────────────
    if is_count:
        count_val = results[0].get("Total Records", 0) if results else 0
        filter_desc = f" of type '{doc_type}'" if doc_type else ""
        return {
            "response": f"Total records{filter_desc} in database: {count_val}",
            "data": results,
        }

    if not results:
        what = " ".join(filter(None, [
            f"DB_ID {db_id}" if db_id is not None else None,
            doc_type,
            ", ".join(asset_tags) if asset_tags else None,
            f"status={status}" if status else None,
            f"since {date_cut}" if date_cut else None,
            " ".join(search_terms) if search_terms else None,
            "your query" if not any([doc_type, asset_tags, status, date_cut, search_terms, db_id is not None]) else None,
        ]))
        return {
            "response": f"No records found matching: '{what}'. Try a different keyword.",
            "data": [],
        }

    # Summarise what was found
    parts = [f"Found {len(results)} record(s)"]
    if db_id is not None: parts.append(f"with DB_ID {db_id}")
    if doc_type:      parts.append(f"of type '{doc_type}'")
    if asset_tags:    parts.append(f"mentioning {', '.join(asset_tags)}")
    if status:        parts.append(f"with status '{status}'")
    if date_cut:      parts.append(f"since {date_cut}")
    if search_terms and not asset_tags:
        parts.append(f"matching '{', '.join(search_terms)}'")

    return {"response": " ".join(parts) + ":", "data": results}

"""
core/slm.py
───────────
Offline SLM engine for LogDigitizer Enterprise.

Uses llama-server.exe (pre-built binary from llama.cpp) launched as a
background subprocess. Identical delivery concept to Tesseract-OCR/:
  - No installation required on company PCs
  - No admin rights needed
  - No Python packages needed
  - Just copy the folder and run

Expected folder layout:
    TinyLlama/
    ├── llama-server.exe                           (downloaded from llama.cpp releases)
    └── tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf     (already present)

Where to get llama-server.exe:
    https://github.com/ggerganov/llama.cpp/releases
    Download: llama-bXXXX-bin-win-avx2-x64.zip  (latest release)
    Extract:  llama-server.exe  into the TinyLlama/ folder

llama-server exposes a local OpenAI-compatible REST API on port 8080.
slm.py starts it as a hidden subprocess on app startup and shuts it
down cleanly on app exit via atexit.

Graceful Degradation:
    All public functions return None if:
      - llama-server.exe is missing from TinyLlama/
      - The GGUF model file is missing
      - The server fails to start or times out
      - Any inference error occurs
    Callers MUST handle None and fall back to existing rule-based logic.

Public API:
    is_available()               -> bool
    correct_ocr_text(raw_text)   -> Optional[str]
    classify_document_type(text) -> Optional[str]
    summarize_notes(raw_notes)   -> Optional[str]
    translate_to_sql_filters(q)  -> Optional[dict]
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Path Resolution (same pattern as Tesseract-OCR in classifier.py) ──────────

if getattr(sys, "frozen", False):
    _BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    _BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_TINYLLAMA_DIR    = os.path.join(_BASE_DIR, "TinyLlama")
_TINYLLAMA_MODEL  = os.path.join(_TINYLLAMA_DIR, "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")
_LLAMA_SERVER_EXE = os.path.join(_TINYLLAMA_DIR, "llama-server.exe")

_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 8080
_BASE_URL    = f"http://{_SERVER_HOST}:{_SERVER_PORT}"

_INFERENCE_TIMEOUT = 15  # seconds per request (lowered for faster uploads on CPU)


# ── Subprocess Management ─────────────────────────────────────────────────────

_slm_available  = False
_server_process: Optional[subprocess.Popen] = None


def _stop_server() -> None:
    """Gracefully terminates the llama-server subprocess. Registered with atexit."""
    global _server_process, _slm_available
    if _server_process and _server_process.poll() is None:
        logger.info("SLM: Shutting down llama-server...")
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None
    _slm_available = False


def _start_server() -> None:
    """
    Launches llama-server.exe as a hidden background subprocess.
    Polls /health until the server is ready (up to 20 seconds).
    Called once at module import.
    """
    global _server_process, _slm_available

    # Pre-flight: check both files exist
    if not os.path.exists(_LLAMA_SERVER_EXE):
        logger.warning(
            "SLM: llama-server.exe not found at: %s\n"
            "  → SLM features are DISABLED.\n"
            "  → Download from: https://github.com/ggerganov/llama.cpp/releases\n"
            "  → Get: llama-bXXXX-bin-win-avx2-x64.zip → extract llama-server.exe → place in TinyLlama/",
            _LLAMA_SERVER_EXE,
        )
        return

    if not os.path.exists(_TINYLLAMA_MODEL):
        logger.warning(
            "SLM: GGUF model not found at: %s\n"
            "  → SLM features are DISABLED.",
            _TINYLLAMA_MODEL,
        )
        return

    try:
        cmd = [
            _LLAMA_SERVER_EXE,
            "--model",    _TINYLLAMA_MODEL,
            "--host",     _SERVER_HOST,
            "--port",     str(_SERVER_PORT),
            "--ctx-size", "2048",
            "--threads",  str(max(1, (os.cpu_count() or 4) - 1)),
        ]

        # CREATE_NO_WINDOW prevents a black console from appearing on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        _server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        logger.info(
            "SLM: llama-server starting (loading model into RAM — please wait ~10s)..."
        )

        # Poll /health endpoint until ready or timeout
        for attempt in range(40):       # 40 × 0.5s = 20s max wait
            time.sleep(0.5)

            # Check if process crashed
            if _server_process.poll() is not None:
                logger.error("SLM: llama-server.exe crashed on startup. SLM disabled.")
                _server_process = None
                return

            try:
                with urllib.request.urlopen(
                    f"{_BASE_URL}/health", timeout=1
                ) as resp:
                    if resp.status == 200:
                        _slm_available = True
                        atexit.register(_stop_server)
                        logger.info(
                            "SLM: llama-server ready after %ds. SLM features ENABLED.",
                            int((attempt + 1) * 0.5),
                        )
                        return
            except Exception:
                continue  # Still starting up

        # Timeout
        logger.warning(
            "SLM: llama-server did not respond within 20s. SLM features DISABLED."
        )
        _stop_server()

    except FileNotFoundError:
        logger.error(
            "SLM: Cannot run llama-server.exe — file may be corrupt or not executable."
        )
    except Exception as exc:
        logger.error("SLM: Unexpected error starting llama-server: %s", exc)


# Start server at module import
_start_server()


# ── Inference ─────────────────────────────────────────────────────────────────

def _chat(system: str, user: str, max_tokens: int = 256, temperature: float = 0.1) -> Optional[str]:
    """
    Sends a chat request to llama-server's OpenAI-compatible endpoint.
    Returns the assistant's reply text, or None on any error.
    """
    if not _slm_available:
        return None

    payload = json.dumps({
        "model": "tinyllama",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{_BASE_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_INFERENCE_TIMEOUT) as resp:
            data  = json.loads(resp.read().decode())
            text  = data["choices"][0]["message"]["content"].strip()
            return text if text else None
    except urllib.error.URLError as exc:
        logger.error("SLM: Request failed (server down?): %s", exc)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("SLM: Unexpected response format: %s", exc)
        return None
    except Exception as exc:
        logger.error("SLM: Inference error: %s", exc)
        return None


def _chat_json(system: str, user: str, max_tokens: int = 150) -> Optional[dict]:
    """
    Like _chat() but requests constrained JSON output via llama.cpp
    response_format. Parses and returns a dict, or None on any error.
    Requires llama-server build >= b3000 for response_format support.
    """
    if not _slm_available:
        return None

    payload = json.dumps({
        "model":    "tinyllama",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens":      max_tokens,
        "temperature":     0.05,
        "stream":          False,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{_BASE_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_INFERENCE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            text = data["choices"][0]["message"]["content"].strip()
            if not text:
                return None
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            return json.loads(text[start:end])
    except Exception as exc:
        logger.error("SLM: JSON chat error: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Returns True if llama-server is running and ready for inference."""
    return _slm_available


def correct_ocr_text(raw_text: str) -> Optional[str]:
    """
    DEPRECATED — Full-text OCR correction is unreliable with TinyLlama 1.1B.
    Per-field rule-based corrections in classifier.py handle common misreads.
    Retained for API compatibility. Always returns None.
    """
    return None


def classify_document_type(text: str) -> Optional[str]:
    """
    DEPRECATED — Replaced by expanded keyword heuristic in classifier.py.
    TinyLlama 1.1B was unreliable for structural/classification decisions.
    Retained for API compatibility. Always returns None.
    """
    return None


def summarize_notes(raw_notes: str) -> Optional[str]:
    """
    Uses the SLM to distil unstructured log notes into a clean summary.
    Uses constrained JSON output (response_format=json_object) so TinyLlama
    is forced to emit {"summary": "..."} — prevents hallucination wrapping.
    Returns the summary string, or None if SLM unavailable / too short.
    """
    if not _slm_available or not raw_notes or len(raw_notes.strip()) < 30:
        return None

    system = (
        "You are a technical log summarizer for an industrial plant. "
        "Summarize the following notes in 2-3 concise sentences. "
        "Keep all equipment tags, personnel names, and action details. "
        'Return ONLY valid JSON in this exact format: {"summary": "<your summary here>"}'
    )
    user = f"Notes:\n\n{raw_notes[:500]}"

    result = _chat_json(system, user, max_tokens=120)
    if not result:
        return None
    summary = str(result.get("summary", "")).strip()
    return summary if len(summary) > 20 else None


def translate_to_sql_filters(query: str) -> Optional[Dict]:
    """
    Uses the SLM to extract structured database search filters from a
    plain-English query. Fallback when Regex + SpaCy both find nothing.

    Returns a dict with keys: doc_type, date_cutoff, keywords.
    Returns None if SLM unavailable or JSON parsing fails.
    """
    if not _slm_available or not query or len(query.strip()) < 5:
        return None

    system = (
        "You are a Text-to-SQL filter extractor for an industrial log database. "
        "Extract search filters from the user query and return a JSON object with:\n"
        '  "doc_type":    one of "Shift Handover Log", "Tool Broken Report", '
        '"General Asset Log", or null\n'
        '  "date_cutoff": an ISO date string like "2024-06-01" if a date is implied, or null\n'
        '  "keywords":    a JSON array of specific search terms (equipment tags, '
        "names, codes), or []\n"
        "Return ONLY the raw JSON object. No explanation. No markdown."
    )
    user = f'Extract search filters from this query: "{query}"'
    raw = _chat(system, user, max_tokens=150, temperature=0.0)

    if not raw:
        return None

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("SLM: No JSON found in filter response: %r", raw)
            return None

        parsed = json.loads(raw[start:end])

        _VALID_TYPES = {"Shift Handover Log", "Tool Broken Report", "General Asset Log"}
        doc_type = parsed.get("doc_type")
        if doc_type and doc_type not in _VALID_TYPES:
            doc_type = None

        kw_raw   = parsed.get("keywords", [])
        keywords: List[str] = (
            [str(k) for k in kw_raw if k]
            if isinstance(kw_raw, list) else []
        )

        return {
            "doc_type":    doc_type,
            "date_cutoff": parsed.get("date_cutoff"),
            "keywords":    keywords,
        }
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("SLM: JSON parse failed: %s | Raw: %r", exc, raw)
        return None

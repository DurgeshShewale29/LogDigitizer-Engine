"""
build_exe.py
─────────────
Pre-flight checks + automated PyInstaller build script for
LogDigitizer Enterprise Platform.

Usage (with venv active):
    python build_exe.py

What it does:
  1. Verifies all critical Python dependencies are importable.
  2. Checks that the spaCy en_core_web_sm model is downloaded.
  3. Verifies templates/ and static/ directories exist.
  4. Runs PyInstaller with the logdigitizer.spec file.
  5. Reports the output path and estimated size on success.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()

# ── Text helpers ──────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"

def ok(msg: str)   -> None: print(f"{GREEN}  [OK]{RESET}  {msg}")
def warn(msg: str) -> None: print(f"{YELLOW}  [!!]{RESET}  {msg}")
def fail(msg: str) -> None: print(f"{RED}  [FAIL]{RESET} {msg}")
def info(msg: str) -> None: print(f"        {msg}")


# ── Pre-flight checks ─────────────────────────────────────────────────────────

REQUIRED_PACKAGES = [
    ("fastapi",           "FastAPI"),
    ("uvicorn",           "Uvicorn"),
    ("jinja2",            "Jinja2"),
    ("pydantic",          "Pydantic"),
    ("cv2",               "OpenCV"),
    ("numpy",             "NumPy"),
    ("fitz",              "PyMuPDF"),
    ("docx",              "python-docx"),
    ("spacy",             "spaCy"),
    ("pandas",            "Pandas"),
    ("openpyxl",          "OpenPyXL"),
    ("pytesseract",       "Pytesseract"),
    ("PyInstaller",       "PyInstaller"),
    ("python_multipart",  "python-multipart"),
]

REQUIRED_DIRS = [
    PROJECT_ROOT / "templates",
    PROJECT_ROOT / "static",
    PROJECT_ROOT / "core",
]

REQUIRED_FILES = [
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "logdigitizer.spec",
    PROJECT_ROOT / "core" / "chatbot.py",
    PROJECT_ROOT / "core" / "database.py",
    PROJECT_ROOT / "core" / "paths.py",
]


def check_imports() -> bool:
    print("\n── Checking Python dependencies ───────────────────────────────")
    all_ok = True
    for module, name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(module)
            ok(f"{name}")
        except ImportError:
            fail(f"{name} is NOT installed.  Run: pip install {module}")
            all_ok = False
    return all_ok


def check_spacy_model() -> bool:
    print("\n────────────────────────────────────────────────────────────────")
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        ok(f"en_core_web_sm loaded  (spaCy {spacy.__version__})")
        return True
    except OSError:
        fail("en_core_web_sm model not found.")
        info("Fix: python -m spacy download en_core_web_sm")
        return False


def check_slm_model() -> bool:
    """Checks llama-server.exe + GGUF model file. Warns but does NOT block build."""
    print("\n── Checking SLM (llama-server + TinyLlama) ───────────────────")
    tinyllama_dir    = PROJECT_ROOT / "TinyLlama"
    tinyllama_model  = tinyllama_dir / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    llama_server_exe = tinyllama_dir / "llama-server.exe"

    # Check 1: TinyLlama folder
    if not tinyllama_dir.is_dir():
        warn("TinyLlama/ folder not found in project root. SLM will be disabled.")
        info("Fix: Create the TinyLlama/ folder in the project root.")
        return False
    ok("TinyLlama/ folder found")

    # Check 2: llama-server.exe
    if not llama_server_exe.is_file():
        warn("llama-server.exe not found in TinyLlama/")
        info("Fix: Download from https://github.com/ggerganov/llama.cpp/releases")
        info("     Get: llama-bXXXX-bin-win-avx2-x64.zip")
        info("     Extract llama-server.exe into TinyLlama/")
        return False
    ok("llama-server.exe found")

    # Check 3: GGUF model file
    if not tinyllama_model.is_file():
        warn("GGUF model not found: TinyLlama/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")
        info("Fix: Download from https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF")
        return False
    size_mb = tinyllama_model.stat().st_size / (1024 ** 2)
    ok(f"GGUF model found  ({size_mb:.0f} MB)")
    return True


def check_directories() -> bool:
    print("\n── Checking project structure ─────────────────────────────────")
    all_ok = True
    for d in REQUIRED_DIRS:
        if d.is_dir():
            ok(str(d.relative_to(PROJECT_ROOT)))
        else:
            fail(f"Missing directory: {d.relative_to(PROJECT_ROOT)}")
            all_ok = False
    for f in REQUIRED_FILES:
        if f.is_file():
            ok(str(f.relative_to(PROJECT_ROOT)))
        else:
            fail(f"Missing file: {f.relative_to(PROJECT_ROOT)}")
            all_ok = False
    return all_ok


def run_pyinstaller() -> bool:
    print("\n── Running PyInstaller ────────────────────────────────────────")
    spec_path = PROJECT_ROOT / "logdigitizer.spec"
    cmd = [sys.executable, "-m", "PyInstaller", str(spec_path), "--clean", "--noconfirm"]
    info(f"Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode == 0


def report_output() -> None:
    dist_dir = PROJECT_ROOT / "dist" / "LogDigitizer"
    exe_path  = dist_dir / "LogDigitizer.exe"
    print("\n── Build output ───────────────────────────────────────────────")
    if exe_path.is_file():
        # Calculate folder size
        total_bytes = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
        size_mb = total_bytes / (1024 ** 2)
        ok(f"Executable: {exe_path}")
        ok(f"Package size: {size_mb:.1f} MB")
        info("")
        info("=== DEPLOYMENT INSTRUCTIONS ===================================")
        info(f"1. Copy the entire folder:  dist/LogDigitizer/")
        info(f"   (Copy the FOLDER, not just the .exe)")
        info(f"2. On the target PC, double-click:  LogDigitizer.exe")
        info(f"3. A console window will open. Wait for:")
        info(f"   'Application startup complete.'")
        info(f"4. Open any browser and go to:  http://127.0.0.1:8000")
        info(f"   The log_digitizer.db file will be created automatically")
        info(f"   next to the .exe on first run.")
        info(f"================================================================")
    else:
        fail(f"Expected exe not found at: {exe_path}")
        info("Check the PyInstaller output above for errors.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  LogDigitizer Enterprise — Build Script")
    print("=" * 60)

    preflight_passed = True
    preflight_passed &= check_imports()
    preflight_passed &= check_spacy_model()
    preflight_passed &= check_directories()

    # SLM check: warns only, does not block the build
    slm_ready = check_slm_model()
    if not slm_ready:
        print(f"\n{YELLOW}  [!!]{RESET}  SLM pre-flight failed. "
              f"Build will continue but TinyLlama features will be DISABLED in the .exe.")

    if not preflight_passed:
        print(f"\n{RED}[ABORT]{RESET} Pre-flight checks failed. Fix the issues above first.\n")
        sys.exit(1)

    print(f"\n{GREEN}All pre-flight checks passed.{RESET} Starting PyInstaller...\n")

    if run_pyinstaller():
        report_output()
        print(f"\n{GREEN}Build complete!{RESET}\n")
    else:
        print(f"\n{RED}Build FAILED.{RESET} Review PyInstaller errors above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

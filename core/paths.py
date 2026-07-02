"""
core/paths.py
─────────────
Single source of truth for all runtime path resolution.

When running as a normal Python script:
  BASE_DIR  → project root (parent of this file's directory)
  DB_PATH   → <project_root>/log_digitizer.db

When running as a PyInstaller .exe:
  Templates/static → inside sys._MEIPASS (bundled read-only data)
  DB_PATH          → next to the .exe file (persistent, writable)
"""
import os
import sys


def get_base_dir() -> str:
    """
    Returns the base directory for bundled assets (templates, static).
    - When frozen (PyInstaller): sys._MEIPASS (temp extraction dir)
    - When running as script:    project root (parent of core/)
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    # Running as script: go up one level from core/ to project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_db_path() -> str:
    """
    Returns the absolute path to the SQLite database file.
    CRITICAL: The DB must live NEXT TO the .exe so it persists across runs.
    PyInstaller's _MEIPASS is a temp dir that gets deleted on exit — never
    store the database there.
    """
    if getattr(sys, "frozen", False):
        # Running as .exe: store DB next to the executable, not in _MEIPASS
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, "log_digitizer.db")
    # Running as script: store in project root
    return os.path.join(get_base_dir(), "log_digitizer.db")


# Singleton constants — import these everywhere
BASE_DIR = get_base_dir()
DB_PATH = get_db_path()

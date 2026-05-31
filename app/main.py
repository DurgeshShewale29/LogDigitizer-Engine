import os
import sys
import multiprocessing
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.logging import logger
from app.api.endpoints import router as api_router

# Initialize FastAPI
app = FastAPI(title=settings.app_name, version=settings.version)

# Base directory resolution for MEIPASS compatibility
base_dir = settings.base_dir
templates_dir = os.path.join(base_dir, "app", "templates")
static_dir = os.path.join(base_dir, "app", "static")

logger.info(f"Base Directory: {base_dir}")
logger.info(f"Templates Directory: {templates_dir}")
logger.info(f"Static Directory: {static_dir}")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Include routers
app.include_router(api_router, prefix="/api")

@app.get("/")
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

if __name__ == "__main__":
    # Required for PyInstaller compatibility with multiprocessing (used by Uvicorn)
    multiprocessing.freeze_support()
    logger.info("Starting up LogDigitizer Engine...")
    
    # Run programmatically to allow packaging with PyInstaller
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False, workers=1)

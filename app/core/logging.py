import os
import logging
from logging.handlers import RotatingFileHandler
from app.core.config import settings

def setup_logging():
    os.makedirs(settings.log_dir, exist_ok=True)
    log_file = os.path.join(settings.log_dir, "app.log")

    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO if not settings.debug else logging.DEBUG)

    # Rotating file handler: max 10MB per file, keep 5 backups
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    
    # Also output to console (useful during dev)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Prevent duplicating logs if setup_logging is called multiple times
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
    return logger

logger = setup_logging()

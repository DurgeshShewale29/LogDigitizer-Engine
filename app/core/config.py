import os
import sys
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "LogDigitizer Engine"
    version: str = "1.0.0"
    debug: bool = False
    
    # Base directory resolution (handles PyInstaller _MEIPASS)
    @property
    def base_dir(self) -> str:
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        # __file__ is app/core/config.py -> project root is three dirs up
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Use a logs directory relative to the executable for air-gapped deployments
    @property
    def log_dir(self) -> str:
        if getattr(sys, 'frozen', False):
            # If frozen, place logs next to the .exe
            exe_dir = os.path.dirname(sys.executable)
            return os.path.join(exe_dir, "logs")
        return os.path.join(os.path.dirname(self.base_dir), "logs")

settings = Settings()

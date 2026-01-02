# backend/core/config.py
import os

class Settings:
    PROJECT_NAME: str = "Truth Engine"
    VERSION: str = "1.0.0"
    
    # 1. Find the path of the 'backend' folder automatically
    # (This ensures it works on your laptop, my laptop, or a cloud server)
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 2. Define the Uploads folder relative to backend
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Create a single instance to use everywhere
settings = Settings()
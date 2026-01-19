from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from services.transcriber import transcribe_video
from services.llm_engine import analyze_text
from core.config import settings
import shutil
import os

router = APIRouter()

# USE THE SETTING
UPLOAD_DIR = settings.UPLOAD_DIR 
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Schema for text-only analysis
class TextAnalysisRequest(BaseModel):
    text: str

@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    file_path = f"{UPLOAD_DIR}/{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    transcript = transcribe_video(file_path)
    result = analyze_text(transcript)

    return {
        "filename": file.filename,
        "message": "File received successfully!",
        "saved_at": file_path,
        "transcript": transcript,
        "verdict": result
    }

@router.post("/analyze-text")
async def analyze_text_only(request: TextAnalysisRequest):
    """
    Endpoint for direct text analysis without video upload.
    Bypasses the Whisper transcription model.
    """
    transcript = request.text
    result = analyze_text(transcript)

    return {
        "message": "Text analysis completed!",
        "transcript": transcript,
        "verdict": result
    }

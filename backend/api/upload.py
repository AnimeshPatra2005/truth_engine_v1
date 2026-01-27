from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from pydantic import BaseModel
from services.transcriber import transcribe_video
from services.llm_engine import analyze_text
from core.config import settings
import shutil
import os
import uuid
import time
from typing import Dict, Any

router = APIRouter()

# Global storage for job results
# In production, use Redis or a database
job_results: Dict[str, Dict[str, Any]] = {}

# USE THE SETTING
UPLOAD_DIR = settings.UPLOAD_DIR 
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Schema for text-only analysis
class TextAnalysisRequest(BaseModel):
    text: str

def run_analysis_background(job_id: str, transcript: str = None, file_path: str = None):
    """Background task handler for analysis workflow"""
    try:
        if file_path:
            job_results[job_id]["progress"] = "Transcribing video..."
            job_results[job_id]["logs"].append("Started transcription...")
            start_time = time.time()
            
            # Transcribe
            transcript = transcribe_video(file_path)
            
            if transcript.startswith("Error"):
                raise Exception(transcript)
                
            elapsed = time.time() - start_time
            job_results[job_id]["logs"].append(f"Transcription complete in {elapsed:.1f}s")
            job_results[job_id]["transcript"] = transcript

        # Analysis Phase
        job_results[job_id]["progress"] = "Decomposing claims and verifying facts..."
        job_results[job_id]["logs"].append("Starting LLM analysis...")
        
        # Run actual analysis
        result = analyze_text(transcript)
        
        # Store success result
        job_results[job_id]["status"] = "complete"
        job_results[job_id]["result"] = result
        job_results[job_id]["progress"] = "Analysis complete"
        job_results[job_id]["logs"].append("Analysis finished successfully")

    except Exception as e:
        print(f"Job {job_id} failed: {e}")
        job_results[job_id]["status"] = "error"
        job_results[job_id]["error"] = str(e)
        job_results[job_id]["progress"] = "Failed"


@router.post("/upload-video")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    file_path = f"{UPLOAD_DIR}/{file.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job state
    job_results[job_id] = {
        "status": "processing",
        "progress": "Queued for processing...",
        "logs": ["File upload received"],
        "filename": file.filename,
        "transcript": None,
        "result": None
    }
    
    # Start background task
    background_tasks.add_task(run_analysis_background, job_id, file_path=file_path)

    return {
        "job_id": job_id,
        "filename": file.filename,
        "status": "processing",
        "message": "Video accepted. Analysis started in background."
    }

@router.post("/analyze-text")
async def analyze_text_only(background_tasks: BackgroundTasks, request: TextAnalysisRequest):
    """
    Endpoint for direct text analysis without video upload.
    Returns a job_id immediately.
    """
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job state
    job_results[job_id] = {
        "status": "processing",
        "progress": "Queued for processing...",
        "logs": ["Text request received"],
        "transcript": request.text,
        "result": None
    }
    
    # Start background task
    background_tasks.add_task(run_analysis_background, job_id, transcript=request.text)

    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Text analysis started in background."
    }

@router.get("/status/{job_id}")
async def check_job_status(job_id: str):
    """Check the status of a long-running analysis job"""
    if job_id not in job_results:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    return job_results[job_id]

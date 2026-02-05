from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from pydantic import BaseModel
from services.media_engine import process_video
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
        visual_analysis = None
        
        if file_path:
            job_results[job_id]["progress"] = "Processing video with Gemini..."
            job_results[job_id]["logs"].append("Starting Gemini video processing...")
            start_time = time.time()
            
            # Use new Gemini-powered media engine
            media_result = process_video(file_path)
            
            if media_result.get("error"):
                raise Exception(media_result["transcript"])
            
            transcript = media_result["transcript"]
            visual_analysis = media_result.get("visual_analysis")
            
            elapsed = time.time() - start_time
            job_results[job_id]["logs"].append(f"Video processing complete in {elapsed:.1f}s")
            job_results[job_id]["transcript"] = transcript
            
            if visual_analysis:
                job_results[job_id]["logs"].append(f"Visual integrity: {visual_analysis.get('overall_visual_integrity', 'unknown')}")
            
            # Clean up the uploaded file after processing
            try:
                os.remove(file_path)
                job_results[job_id]["logs"].append("Cleaned up uploaded file")
            except Exception as cleanup_error:
                print(f"Could not delete file {file_path}: {cleanup_error}")

        # Analysis Phase
        job_results[job_id]["progress"] = "Decomposing claims and verifying facts..."
        job_results[job_id]["logs"].append("Starting LLM analysis...")
        
        # Run actual analysis
        result = analyze_text(transcript)
        
        # Store success result
        # Extract case_id if present and add it to top level
        case_id = result.get('case_id') if isinstance(result, dict) else None
        
        job_results[job_id]["status"] = "complete"
        job_results[job_id]["result"] = {
            "verdict": result,
            "case_id": case_id,  # Add case_id at top level for frontend
            "visual_analysis": visual_analysis  # NEW: Include visual correlation data
        }
        job_results[job_id]["progress"] = "Analysis complete"
        job_results[job_id]["logs"].append("Analysis finished successfully")

    except Exception as e:
        print(f"Job {job_id} failed: {e}")
        import traceback
        traceback.print_exc()  
        
        job_results[job_id]["status"] = "error"
        job_results[job_id]["error"] = str(e)
        job_results[job_id]["progress"] = "Failed"
        job_results[job_id]["logs"].append(f"Error: {str(e)}")


@router.post("/upload-video")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    # Validate file type
    allowed_extensions = {'.mp4', '.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac', '.avi', '.mov', '.mkv'}
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file format: {file_extension}. Supported formats: {', '.join(allowed_extensions)}"
        )
    
    # Generate job ID first
    job_id = str(uuid.uuid4())
    
    # Create unique filename to avoid conflicts
    unique_filename = f"{job_id}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    try:
        # Save the uploaded file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Validate file was saved correctly
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise Exception("File upload resulted in empty file")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    finally:
        file.file.close()  # Close the uploaded file (NOT await)
    
    # Initialize job state with all required fields
    job_results[job_id] = {
        "status": "processing",
        "progress": "Queued for processing...",
        "logs": ["File upload received"],
        "filename": file.filename,
        "transcript": None,
        "result": None,
        "error": None
    }
    
    # Start background task - MUST pass transcript=None explicitly
    background_tasks.add_task(run_analysis_background, job_id, transcript=None, file_path=file_path)

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
        "result": None,
        "error": None
    }
    
    # Start background task
    background_tasks.add_task(run_analysis_background, job_id, transcript=request.text, file_path=None)

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
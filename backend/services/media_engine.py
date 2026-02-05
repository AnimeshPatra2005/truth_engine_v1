"""
Media Engine - Gemini-powered video/audio processing.

This module handles:
1. Uploading media files to Gemini's File API
2. Transcribing audio/video using Gemini's native capabilities
3. Analyzing visual content for context correlation
"""

import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Initialize the Gemini client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Model to use for media processing
MEDIA_MODEL = "gemini-2.0-flash"


def upload_to_gemini(file_path: str) -> types.File:
    """
    Upload a video/audio file to Gemini's File API.
    
    Args:
        file_path: Path to the media file
        
    Returns:
        File object containing URI and metadata
    """
    print(f" Uploading file to Gemini: {file_path}")
    
    try:
        uploaded_file = client.files.upload(file=file_path)
        print(f"Upload complete: {uploaded_file.name}")
        return uploaded_file
    except Exception as e:
        print(f"Upload failed: {e}")
        raise


def wait_for_processing(file_obj: types.File, timeout: int = 300) -> types.File:
    """
    Wait for Gemini to finish processing the uploaded file.
    
    Args:
        file_obj: The uploaded file object
        timeout: Maximum seconds to wait
        
    Returns:
        Updated file object with ACTIVE state
    """
    print(f"Waiting for Gemini to process file...")
    start_time = time.time()
    
    while True:
        file_status = client.files.get(name=file_obj.name)
        
        if file_status.state == types.FileState.ACTIVE:
            print(f"File ready for processing")
            return file_status
        elif file_status.state == types.FileState.FAILED:
            raise Exception(f"File processing failed: {file_status.error}")
        
        if time.time() - start_time > timeout:
            raise Exception(f"Timeout waiting for file processing after {timeout}s")
        
        print(f"   State: {file_status.state}, waiting...")
        time.sleep(2)


def transcribe_video(file_path: str) -> str:
    """
    Transcribe a video/audio file using Gemini.
    
    This replaces the Whisper-based transcription with Gemini's native
    audio understanding capabilities.
    
    Args:
        file_path: Path to the media file
        
    Returns:
        Transcribed text content
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return "Error: Uploaded file is empty (0 bytes)."
    
    print(f" Transcribing video: {file_path} ({file_size / 1024:.1f} KB)")
    start_time = time.time()
    
    try:
        # Upload and wait for processing
        uploaded_file = upload_to_gemini(file_path)
        processed_file = wait_for_processing(uploaded_file)
        
        # Request transcription from Gemini
        response = client.models.generate_content(
            model=MEDIA_MODEL,
            contents=[
                processed_file,
                """Transcribe ALL spoken content in this video/audio accurately.
                
Rules:
- Output ONLY the transcription, no commentary
- Include all spoken words exactly as said
- Do not add timestamps or speaker labels unless clearly different speakers
- If there's no speech, respond with: [NO SPEECH DETECTED]"""
            ]
        )
        
        transcript = response.text.strip()
        duration = time.time() - start_time
        print(f"Transcription complete in {duration:.1f}s")
        
        if not transcript or transcript == "[NO SPEECH DETECTED]":
            return "Error: No speech detected in the uploaded file."
        
        return transcript
        
    except Exception as e:
        print(f" Transcription error: {e}")
        return f"Error processing file: {str(e)}"


def analyze_visual_correlation(file_path: str, transcript: str) -> dict:
    """
    Analyze if visuals in the video correlate with the spoken content.
    
    This detects:
    - Stock photos used out of context
    - Images that don't match the narration
    - Potentially misleading visuals
    
    Args:
        file_path: Path to the video file
        transcript: The transcribed content
        
    Returns:
        Dictionary with visual analysis results
    """
    print(f"Analyzing visual correlation...")
    
    try:
        # Upload file (or reuse if already uploaded)
        uploaded_file = upload_to_gemini(file_path)
        processed_file = wait_for_processing(uploaded_file)
        
        # Prompt for visual analysis
        prompt = f"""Analyze the visual content of this video and compare it to the transcript below.

TRANSCRIPT:
{transcript}

TASK:
1. Identify each distinct image, chart, graphic, or visual element shown in the video
2. Note the approximate timestamp (MM:SS format) when each visual appears
3. Describe what each visual depicts
4. Evaluate if each visual MATCHES or CONTRADICTS the spoken content at that moment
5. Flag any visuals that appear to be:
   - Generic stock photos unrelated to the topic
   - Misleading or out-of-context images
   - Images that could deceive viewers about the content

Respond in this JSON format:
{{
    "visual_elements": [
        {{
            "timestamp": "MM:SS",
            "description": "What the visual shows",
            "matches_content": true/false,
            "concern": "null or description of why this might be misleading"
        }}
    ],
    "overall_visual_integrity": "high/medium/low",
    "summary": "Brief overall assessment of visual-content alignment"
}}"""

        response = client.models.generate_content(
            model=MEDIA_MODEL,
            contents=[processed_file, prompt]
        )
        
        # Parse response as JSON
        import json
        from json_repair import repair_json
        
        result_text = response.text.strip()
        # Clean markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        
        result = json.loads(repair_json(result_text))
        
        # --- NEW: Semantic Reverse Search Verification ---
        from services.tools import search_web
        
        print("Verifying flagged visuals with semantic search...")
        
        for visual in result.get("visual_elements", []):
            # Only check items that are flagged as mismatched or have concerns
            if not visual.get("matches_content") or visual.get("concern"):
                search_query = f"origin of image showing {visual['description']}"
                print(f"Searching origin for: {visual['description']}")
                
                # Perform search
                search_results = search_web(search_query, intent="verification")
                
                if search_results:
                    # Update the visual element with search findings
                    visual["verification_notes"] = f"Found {len(search_results)} potential sources. Top match: {search_results[0]['title']} ({search_results[0]['url']})"
                    visual["possible_source"] = search_results[0]['url']
                else:
                    visual["verification_notes"] = "No clear online source found for this specific visual description."
            else:
                visual["verification_notes"] = "Visual matches content context, no external verification needed."

        print("Visual analysis complete")
        return result
        
    except Exception as e:
        print(f"Visual analysis error: {e}")
        return {
            "visual_elements": [],
            "overall_visual_integrity": "unknown",
            "summary": f"Analysis failed: {str(e)}",
            "error": True
        }


def process_video(file_path: str) -> dict:
    """
    Complete video processing pipeline.
    
    1. Transcribes the video
    2. Analyzes visual-content correlation
    
    Args:
        file_path: Path to the video file
        
    Returns:
        Dictionary with transcript and visual analysis
    """
    print(f"\n{'='*50}")
    print(f"PROCESSING VIDEO: {os.path.basename(file_path)}")
    print(f"{'='*50}\n")
    
    # Step 1: Transcribe
    transcript = transcribe_video(file_path)
    
    if transcript.startswith("Error"):
        return {
            "transcript": transcript,
            "visual_analysis": None,
            "error": True
        }
    
    # Step 2: Visual correlation (only for video files, not audio)
    video_extensions = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
    file_ext = os.path.splitext(file_path)[1].lower()
    
    visual_analysis = None
    if file_ext in video_extensions:
        visual_analysis = analyze_visual_correlation(file_path, transcript)
    else:
        print(f"Audio-only file, skipping visual analysis")
    
    return {
        "transcript": transcript,
        "visual_analysis": visual_analysis,
        "error": False
    }


# --- TEST BLOCK ---
if __name__ == "__main__":
    print("--- Testing Media Engine ---")
    test_path = input("Paste path to test video: ").strip('"').strip("'")
    
    result = process_video(test_path)
    
    print("\n" + "="*50)
    print("RESULT:")
    print("="*50)
    print(f"\nTranscript:\n{result['transcript'][:500]}...")
    
    if result.get('visual_analysis'):
        import json
        print(f"\nVisual Analysis:\n{json.dumps(result['visual_analysis'], indent=2)}")

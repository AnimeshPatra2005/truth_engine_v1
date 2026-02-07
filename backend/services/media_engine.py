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
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_SEARCH"))

# Model to use for media processing
MEDIA_MODEL = "gemini-3-flash-preview"


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


def transcribe_video(file_obj: types.File) -> str:
    """
    Transcribe a video/audio file using Gemini.
    
    Args:
        file_obj: The processed file object from Gemini
        
    Returns:
        Transcribed text content
    """
    print(f" Requesting transcription from Gemini...")
    start_time = time.time()
    
    try:
        # Request transcription from Gemini
        response = client.models.generate_content(
            model=MEDIA_MODEL,
            contents=[
                file_obj,
                """Transcribe ALL spoken content in this video/audio accurately.
                
Rules:
- Output ONLY the transcription, no commentary
- Include all spoken words exactly as said
- If you recognize a famous public figure (politician, celebrity, etc.), prefix their speech with their name like: [Joe Biden]: "quote here"
- If multiple unknown speakers exist, just transcribe without labels - do NOT use generic labels like "Speaker 1" or "Narrator"
- Do NOT add timestamps
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


def analyze_visual_correlation(file_obj: types.File, transcript: str) -> dict:
    """
    Analyze if visuals in the video correlate with the spoken content.
    Includes retry logic for 503 errors.
    
    Args:
        file_obj: The processed file object from Gemini
        transcript: The transcribed content
        
    Returns:
        Dictionary with visual analysis results
    """
    print(f"Analyzing visual correlation...")
    
    # Prompt for visual analysis
    prompt = f"""Analyze the visual content of this video and compare it to the transcript below.

TRANSCRIPT:
{transcript}

TASK:
1. Identify each distinct image, chart, graphic, or visual element shown in the video
2. Note the approximate timestamp (MM:SS format) when each visual appears
3. Describe what each visual depicts
4. Evaluate if each visual MATCHES, CONTRADICTS, or is UNCLEAR relative to the spoken content

IMPORTANT RULES:
- If you cannot determine with HIGH CONFIDENCE whether an image matches or contradicts, mark it as "unclear"
- Do NOT give false positives - only flag as "contradicts" if you are CERTAIN
- Stock photos that could reasonably illustrate the topic are acceptable
- Only flag images that CLEARLY misrepresent the content

Respond in this JSON format:
{{
    "visual_elements": [
        {{
            "timestamp": "MM:SS",
            "description": "What the visual shows",
            "status": "matches" | "contradicts" | "unclear",
            "concern": "null if matches, otherwise explanation of the issue or uncertainty"
        }}
    ],
    "overall_visual_integrity": "high/medium/low/unknown",
    "summary": "Brief overall assessment of visual-content alignment"
}}"""

    # Retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MEDIA_MODEL,
                contents=[file_obj, prompt]
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
            
            print("Visual analysis complete")
            return result
            
        except Exception as e:
            print(f"Visual analysis attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                print(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                return {
                    "visual_elements": [],
                    "overall_visual_integrity": "unknown",
                    "summary": f"Analysis failed after {max_retries} retries: {str(e)}",
                    "error": True
                }


def process_video(file_path: str, enable_visual_analysis: bool = True) -> dict:
    """
    Complete video processing pipeline.
    Optimized to upload file only once.
    
    1. Uploads file to Gemini
    2. Transcribes the video
    3. Analyzes visual-content correlation (if enabled)
    
    Args:
        file_path: Path to the video file
        enable_visual_analysis: Whether to run visual analysis (default True)
        
    Returns:
        Dictionary with transcript and visual analysis
    """
    print(f"\n{'='*50}")
    print(f"PROCESSING VIDEO: {os.path.basename(file_path)}")
    print(f"Visual Analysis: {'ENABLED' if enable_visual_analysis else 'DISABLED'}")
    print(f"{'='*50}\n")
    
    try:
        if not os.path.exists(file_path):
            return {"transcript": f"Error: File not found at {file_path}", "error": True}
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return {"transcript": "Error: Uploaded file is empty.", "error": True}

        # Step 1: Upload and wait for processing (ONCE)
        uploaded_file = upload_to_gemini(file_path)
        processed_file = wait_for_processing(uploaded_file)
        
        # Step 2: Transcribe
        transcript = transcribe_video(processed_file)
        
        if transcript.startswith("Error"):
            return {
                "transcript": transcript,
                "visual_analysis": None,
                "error": True
            }
        
        # Step 3: Visual correlation (only for video files AND if enabled)
        video_extensions = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
        file_ext = os.path.splitext(file_path)[1].lower()
        
        visual_analysis = None
        if enable_visual_analysis and file_ext in video_extensions:
            visual_analysis = analyze_visual_correlation(processed_file, transcript)
            print(f"DEBUG: Visual Analysis Result: {visual_analysis}")
        else:
            print(f"Audio-only file, skipping visual analysis")
        
        return {
            "transcript": transcript,
            "visual_analysis": visual_analysis,
            "error": False
        }
        
    except Exception as e:
        print(f"Critical pipeline error: {e}")
        return {
            "transcript": f"Processing failed: {str(e)}",
            "visual_analysis": None,
            "error": True
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

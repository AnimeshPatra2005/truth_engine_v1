import whisper 
import os 
import time 
#Loading model outsode the function so that whisper model gets loaded up when the sever starts hence not causing delay for the users
print("Loading Whisper Model")
try:
    model=whisper.load_model("base")
    print("Whisper Model loaded")
except Exception as e:
    print(f"Failed to load whisper:{e}")
    model=None

def transcribe_video(file_path:str)->str:
    if not model:
        return "Error:Whisper model not loaded."
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"
    
    # Validate file size
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return "Error: Uploaded file is empty (0 bytes). Please upload a valid video/audio file."
    
    if file_size < 1000:  # Less than 1KB
        return f"Error: File too small ({file_size} bytes). This may be a corrupted or invalid file."
    
    print(f"Transcribing:{file_path} ({file_size / 1024:.1f} KB)...")
    start_time=time.time()

    try:
        result=model.transcribe(file_path)
        duration=time.time()-start_time
        print(f"Done in {duration:.2f} seconds")
        
        transcript_text = result["text"].strip()
        
        # Validate transcription result
        if not transcript_text:
            return "Error: No speech detected in the uploaded file. Please upload a video with clear audio."
        
        return transcript_text
        
    except RuntimeError as e:
        error_msg = str(e)
        if "reshape tensor" in error_msg or "0 elements" in error_msg:
            return "Error: The uploaded file contains no audio or the audio format is unsupported. Please try a different file format (MP4, MP3, WAV recommended)."
        return f"Error processing file:{error_msg}"
    except Exception as e:
        print(f"Transcription Error :{e}")
        return f"Error processing file:{str(e)}"

if __name__=="__main__":
    test_path=input("Please paste the full path to your video file:")
    test_path=test_path.strip('"').strip("'")
    transcript=transcribe_video(test_path)
    print("RESULT")
    print(transcript)


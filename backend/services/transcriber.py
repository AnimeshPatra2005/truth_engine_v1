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
    print(f"Transcribing:{file_path}...")
    start_time=time.time()

    try:
        result=model.transcribe(file_path)
        duration=time.time()-start_time
        print(f"Done in {duration:.2f} seconds")
        return result["text"].strip()
    except Exception as e:
        print(f"Transcription Error :{e}")
        return f"Error processing file:{str(e)}"

if __name__=="__main__":
    test_path=input("Please paste the full path to your video file:")
    test_path=test_path.strip('"').strip("'")
    transcript=transcribe_video(test_path)
    print("RESULT")
    print(transcript)


# run_pipeline.py
import time
from services.transcriber import transcribe_video
from services.llm_engine import app, API_CALL_DELAY, MODEL_NAME, api_call_count

def run_full_pipeline(video_path: str):
    """Complete workflow: Transcribe → Verify"""
    
    # Step 1: Transcribe
    print("="*60)
    print("STEP 1: VIDEO TRANSCRIPTION")
    print("="*60)
    transcript = transcribe_video(video_path)
    
    if transcript.startswith("Error"):
        print(f"❌ Transcription failed: {transcript}")
        return None
    
    print(f"✅ Transcription: '{transcript[:150]}...'")
    
    # Step 2: Run Agent System
    print("\n" + "="*60)
    print("STEP 2: FACT VERIFICATION")
    print("="*60)
    print(f"🚀 ENGINE STARTING: '{transcript}'")
    print(f"⏱️ Rate Limiting: {API_CALL_DELAY}s delay")
    print(f"📊 Model: {MODEL_NAME}")
    
    try:
        start_time = time.time()
        result = app.invoke({"transcript": transcript})
        elapsed = time.time() - start_time
        
        v = result.get('final_verdict')
        
        print("\n" + "="*60)
        print("🏆 FINAL VERDICT REPORT")
        print("="*60)
        print(f"⏱️ Total runtime: {elapsed / 60:.1f} minutes")
        print(f"📊 Total API calls made: {api_call_count}")
        
        if v:
            verdict_val = v.get('verdict') if isinstance(v, dict) else v.verdict
            summary_val = v.get('summary') if isinstance(v, dict) else v.summary
            verifications = v.get('verifications') if isinstance(v, dict) else v.verifications

            print(f"\n⚖️ JUDGEMENT: {verdict_val.upper()}")
            print(f"📝 SUMMARY:\n{summary_val}")
            
            if verifications:
                print("\n🔍 DETAILED EVIDENCE LOG:")
                for i, check in enumerate(verifications):
                    c_claim = check.get('claim') if isinstance(check, dict) else check.claim
                    c_status = check.get('status') if isinstance(check, dict) else check.status
                    c_method = check.get('method_used') if isinstance(check, dict) else check.method_used
                    c_details = check.get('details') if isinstance(check, dict) else check.details
                    
                    print(f"\n   #{i+1} CLAIM: \"{c_claim}\"")
                    print(f"      📍 METHOD:  {c_method}")
                    print(f"      ✅ STATUS:  {c_status}")
                    print(f"      📜 PROOF:   {c_details}")
                    print("      " + "-"*30)
        else:
            print("❌ No verdict generated.")
            
        return result

    except Exception as e:
        print(f"\n💥 SYSTEM FAILURE: {e}")
        print(f"📊 API calls completed before failure: {api_call_count}")
        return None

if __name__ == "__main__":
    # Interactive mode
    video_path = input("📹 Enter video file path: ").strip('"').strip("'")
    run_full_pipeline(video_path)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.upload import router as upload_router
from services.run_pipeline import run_full_pipeline
import uvicorn

app = FastAPI()

# --- CORS Middleware (Fixed syntax) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include your upload router
app.include_router(upload_router, prefix="/api")

@app.get("/")
def health_check():
    return {"status": "Truth Engine is Online 🚀"}


if __name__ == "__main__":
    print("\n🚀 Truth Engine - Choose Mode:")
    print("1. API Server (FastAPI)")
    print("2. CLI Pipeline (Video Upload)")
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    if choice == "1":
        print("Starting Truth Engine Server...")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    elif choice == "2":
        video_path = input("📹 Enter video file path: ").strip('"').strip("'")
        run_full_pipeline(video_path)
    else:
        print("Invalid choice. Exiting.")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.upload import router as upload_router
from api.chat import router as chat_router
from services.run_pipeline import run_full_pipeline
from db.case_store import init_collection
import uvicorn
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Vector DB on startup (Whisper removed - using Gemini now)
    init_collection()
    print("✓ Vector DB initialized")
    yield
    # Clean up if needed
    print("Shutting down...")

app = FastAPI(lifespan=lifespan)

# --- CORS Middleware (Fixed syntax) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost",
        "https://truth-engine-v1.vercel.app",
        "https://truth-engine-v1-animeshpatra2005s-projects.vercel.app",  # Full Vercel domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload_router, prefix="/api")
app.include_router(chat_router, prefix="/api")

@app.get("/")
def health_check():
    return {"status": "Truth Engine is Online"}


if __name__ == "__main__":
    print("\nTruth Engine - Starting Web Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
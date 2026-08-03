from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.upload import router as upload_router
from api.chat import router as chat_router
from api.compass import router as compass_router
from db.case_store import init_collection
from services.deepfake_engine import load_deepfake_model
from services.compass_engine import load_knowledge_base
import uvicorn
import os
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Vector DB on startup (Whisper removed - using Gemini now)
    init_collection()
    print("✓ Vector DB initialized")
    load_deepfake_model()
    print("✓ Deepfake model loaded")
    load_knowledge_base()
    print("✓ Compass knowledge base loaded")
    yield
    # Clean up if needed
    print("Shutting down...")

app = FastAPI(lifespan=lifespan)

# --- CORS Middleware (Configured for universal frontend access) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(compass_router, prefix="/api")

@app.get("/")
def health_check():
    return {"status": "Truth Engine is Online"}


if __name__ == "__main__":
    print("\nTruth Engine - Starting Web Server...")
    # Bind explicitly to 7860 for Hugging Face Spaces
    port = 7860
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

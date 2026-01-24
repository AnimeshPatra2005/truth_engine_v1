from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.upload import router as upload_router
from services.run_pipeline import run_full_pipeline
import uvicorn

app = FastAPI()

# --- CORS Middleware (Fixed syntax) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost",
        "https://truth-engine-v1.vercel.app",
        "https://*.vercel.app"  # For preview deployments
    ],
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
    print("\n🚀 Truth Engine - Starting Web Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from backend.api.upload import router as upload_router
import uvicorn
import shutil
import os
import backend.core


app = FastAPI()
# --- SECURITY PASS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router,prefix="/api")

@app.get("/")
def health_check():
    return {"status": "Truth Engine is Online 🚀"}


if __name__ == "__main__":
    # We change 'app' to "main:app" string to fix that Reload Warning
    print("Starting Truth Engine Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
# truth_engine_v1/Dockerfile

# 1. Base Image
FROM python:3.11-slim

# 2. System Dependencies (ffmpeg for video processing)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Set Working Directory
WORKDIR /app

# 4. Configure pip with increased timeout and retries
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=5

# 5. Install PyTorch CPU-Only FIRST (Force lightweight version)
# We do this before copying requirements to ensure it doesn't look for the GPU version
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 6. Install Whisper (It will use the torch we just installed)
RUN pip install --no-cache-dir openai-whisper

# 6b. Install deepfake detection stack AFTER torch is already pinned CPU-only.
#     deepguard pulls in ultralytics (YOLO face detector) and transformers.
#     Installing here prevents pip from re-resolving torch to a GPU build.
RUN pip install --no-cache-dir timm transformers deepguard albumentations

# 7. Copy and install the rest of the requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 8. Copy the entire project
COPY . .

# 9. Create uploads and chroma_db directories, and set full write permissions for Hugging Face's non-root user (User 1000)
RUN mkdir -p backend/uploads chroma_db && chmod -R 777 /app

# 10. Run the App
CMD ["python", "backend/main.py"]


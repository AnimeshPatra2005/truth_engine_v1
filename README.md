# Truth Engine (SATYA)

Truth Engine (SATYA) is an advanced AI-powered video analysis and fact-checking platform. It is designed to verify the authenticity of video content by analyzing transcripts, images, and cross-referencing information with trusted sources using a tiered verification system.

## Key Features

- **Video & Text Analysis**: Upload video files, provide YouTube links, or simply enter a text query for comprehensive analysis and fact-checking.
- **AI Processing**: Utilizes advanced AI models for image analysis, transcript generation, and detailed content understanding.
- **Fact-Checking**: Implements a robust tiered verification system:
    - **Tier 1**: Verification using Google Fact Check API.
    - **Tier 2**: Domain Trust verification based on a list of trusted domains identified by Gemini for each claim.
    - **Tier 3**: Consensus check against multiple sources.
- **Real-Time Knowledge**: Integrates Google Search grounding for up-to-date information verification.
- **Expert Chatbot**: Interactive chatbot for querying analysis results and asking follow-up questions.
- **Task-Specific Embeddings**: Uses specialized embeddings for accurate information retrieval.

## Technology Stack

### Backend
- **Framework**: FastAPI (Python)
- **AI & LLM**: Google Gemini (1.5/2.0/3.0), LangChain
- **Database**: ChromaDB (Vector Store)
- **Search**: Tavily Search API, Google Search Grounding
- **Video Processing**: yt-dlp

### Frontend
- **Framework**: React (Vite)
- **Styling**: CSS
- **State Management**: React Hooks

### Deployment & Tools
- **Containerization**: Docker
- **Environment Management**: Python venv, dotenv

## Prerequisites

Before running the project, ensure you have the following installed:
- Python 3.10+
- Node.js & npm
- Docker (optional, for containerized deployment)

You will also need the following API keys:
- **Google Gemini API**:
  - `GEMINI_API_KEY_ANALYSIS`: Targeted key for analysis tasks (load balancing).
  - `GEMINI_API_KEY_SEARCH`: Targeted key for search operations (load balancing).
- **Tavily API**:
  - `TAVILY_API_KEY`: For research and browsing capabilities.
- **Google Fact Check Tools API**:
  - `GOOGLE_FACT_CHECK_API_KEY`: For accessing the Fact Check Tools API.

## Installation

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r ../requirements.txt
   ```

4. Create a `.env` file in the root directory and add your API keys:
   ```env
   GEMINI_API_KEY_ANALYSIS=your_key_here
   GEMINI_API_KEY_SEARCH=your_key_here
   TAVILY_API_KEY=your_key_here
   GOOGLE_FACT_CHECK_API_KEY=your_key_here

   ```

5. Run the server:
   ```bash
   uvicorn main:app --reload
   ```
   The backend will be available at `http://localhost:8000`.

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Run the development server:
   ```bash
   npm run dev
   ```
   The frontend will be available at `http://localhost:5173`.

## Usage

1. Open the frontend application in your browser.
2. Upload a video file or paste a YouTube link in the input area. Alternatively, you can write a text query directly.
3. The system will process the input, analyze the content, and provide a comprehensive fact-checking report.
4. Use the chat interface to ask specific questions about the results or continue the investigation.

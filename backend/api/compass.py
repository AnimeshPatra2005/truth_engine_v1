"""
Compass API endpoints for Regulatory Compass chatbot.

Endpoints:
  POST /api/compass/analyze  — Initial message analysis (full pipeline)
  POST /api/compass/chat     — Follow-up conversation
"""
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from services.compass_engine import analyze_message, generate_followup, load_knowledge_base

router = APIRouter()

# In-memory session storage (same pattern as job_results in upload.py)
# Key: session_id, Value: {conversation_history, analysis, original_message}
compass_sessions: Dict[str, Dict[str, Any]] = {}

MAX_SESSIONS = 50  # Limit to prevent memory bloat


# ==============================================================================
# REQUEST/RESPONSE SCHEMAS
# ==============================================================================

class CompassAnalyzeRequest(BaseModel):
    message: str


class CompassChatRequest(BaseModel):
    session_id: str
    message: str


class CompassAnalyzeResponse(BaseModel):
    session_id: str
    overall_risk: str
    risk_parameters: Dict[str, Dict]
    response: str
    citations: List[Dict]
    actionable_steps: List[str]
    demands: List[Dict]


class CompassChatResponse(BaseModel):
    response: str
    citations: List[Dict]


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@router.post("/compass/analyze", response_model=CompassAnalyzeResponse)
async def compass_analyze(request: CompassAnalyzeRequest):
    """
    Analyze a suspicious message/email through the full Compass pipeline.
    Returns structured risk assessment with citations and actionable steps.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        # Run the full analysis pipeline
        result = analyze_message(request.message.strip())

        # Create session for follow-up
        session_id = str(uuid.uuid4())

        # Clean demands for JSON serialization (remove non-serializable data)
        clean_demands = []
        for d in result.get("demands", []):
            clean_demand = {
                "ask": d.get("ask", ""),
                "entity_claimed": d.get("entity_claimed", ""),
                "type": d.get("type", ""),
                "amount_mentioned": d.get("amount_mentioned"),
                "information_requested": d.get("information_requested"),
                "urgency_level": d.get("urgency_level", "medium"),
            }
            if d.get("matched_rule"):
                clean_demand["matched_rule"] = {
                    "rule": d["matched_rule"]["rule"],
                    "severity": d["matched_rule"]["severity"],
                    "proof_links": d["matched_rule"]["proof_links"],
                }
            clean_demands.append(clean_demand)

        # Store session
        compass_sessions[session_id] = {
            "original_message": request.message.strip(),
            "analysis": result,
            "conversation_history": [
                {"role": "user", "content": request.message.strip()},
                {"role": "assistant", "content": result["response"]},
            ],
        }

        # Evict oldest sessions if over limit
        if len(compass_sessions) > MAX_SESSIONS:
            oldest_key = next(iter(compass_sessions))
            del compass_sessions[oldest_key]

        return CompassAnalyzeResponse(
            session_id=session_id,
            overall_risk=result["overall_risk"],
            risk_parameters=result.get("risk_parameters", {}),
            response=result["response"],
            citations=result["citations"],
            actionable_steps=result["actionable_steps"],
            demands=clean_demands,
        )

    except Exception as e:
        print(f"Compass analyze error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/compass/chat", response_model=CompassChatResponse)
async def compass_chat(request: CompassChatRequest):
    """
    Handle follow-up questions in a Compass session.
    Uses full conversation history for context.
    """
    if request.session_id not in compass_sessions:
        raise HTTPException(status_code=404, detail="Session not found. Please start a new analysis.")

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        session = compass_sessions[request.session_id]

        # Generate follow-up response
        result = generate_followup(session, request.message.strip())

        # Update conversation history
        session["conversation_history"].append(
            {"role": "user", "content": request.message.strip()}
        )
        session["conversation_history"].append(
            {"role": "assistant", "content": result["response"]}
        )

        return CompassChatResponse(
            response=result["response"],
            citations=result.get("citations", []),
        )

    except Exception as e:
        print(f"Compass chat error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

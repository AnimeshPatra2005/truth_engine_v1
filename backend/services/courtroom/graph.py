"""
Courtroom Graph - LangGraph Workflow Assembly.
Orchestrates the fact-checking pipeline with Evidence Enrichment Loop.

FLOW:
  Decomposer → [claims < 5?] → Advocate (with extras) → Lead Promoter → Advocate (standard) → Fact Checker → Judge → Archive
              → [claims >= 5] → Advocate (standard) → Fact Checker → Judge → Archive
"""
import uuid
from langgraph.graph import StateGraph, END, START

from .schemas import CourtroomState
from .nodes.query_generator import claim_decomposer_node
from .nodes.advocate import evidence_extraction_with_extras, evidence_extraction_standard
from .nodes.lead_promoter import lead_promoter_node
from .nodes.verifier import three_tier_fact_check_node_batched
from .nodes.judge import final_analysis_node

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from db.case_store import save_case


# ==============================================================================
# ROUTING LOGIC
# ==============================================================================

def route_after_decompose(state: CourtroomState) -> str:
    """Route based on claim count: < 5 needs enrichment, >= 5 goes standard."""
    decomposed = state.get('decomposed_data')
    if decomposed and len(decomposed.claims) < 5:
        print(f"\n   ROUTING: {len(decomposed.claims)} claims < 5 → Enrichment Path (with extras)")
        return "advocate_with_extras"
    else:
        claim_count = len(decomposed.claims) if decomposed else 0
        print(f"\n   ROUTING: {claim_count} claims >= 5 → Standard Path")
        return "advocate_standard"


def archive_case_node(state: CourtroomState):
    """Save case to Vector DB after analysis completes"""
    final_verdict = state.get('final_verdict')
    case_id = state.get('case_id')  # Use pre-generated case_id
    
    if final_verdict and case_id:
        try:
            verdict_dict = final_verdict.dict() if hasattr(final_verdict, 'dict') else final_verdict
            verdict_dict['case_id'] = case_id  # Ensure case_id is in verdict
            saved_id = save_case(verdict_dict, case_id)  # Pass existing case_id
            print(f"\n   ARCHIVED: Case saved to Vector DB with ID {saved_id}")
            return {"case_id": saved_id}
        except Exception as e:
            print(f"\n   ARCHIVE ERROR: Failed to save case - {e}")
            return {}
    return {}


# ==============================================================================
# WORKFLOW DEFINITION
# ==============================================================================

workflow = StateGraph(CourtroomState)

# Add nodes
workflow.add_node("claim_decomposer", claim_decomposer_node)
workflow.add_node("advocate_with_extras", evidence_extraction_with_extras)
workflow.add_node("lead_promoter", lead_promoter_node)
workflow.add_node("advocate_standard", evidence_extraction_standard)
workflow.add_node("fact_checker", three_tier_fact_check_node_batched)
workflow.add_node("final_analyzer", final_analysis_node)
workflow.add_node("archive_case", archive_case_node)

# Define edges
workflow.add_edge(START, "claim_decomposer")

# Conditional routing after decomposition
workflow.add_conditional_edges(
    "claim_decomposer",
    route_after_decompose,
    {
        "advocate_with_extras": "advocate_with_extras",
        "advocate_standard": "advocate_standard"
    }
)

# Enrichment path: extras → promoter → standard
workflow.add_edge("advocate_with_extras", "lead_promoter")
workflow.add_edge("lead_promoter", "advocate_standard")

# Both paths converge to fact checker → judge → archive
workflow.add_edge("advocate_standard", "fact_checker")
workflow.add_edge("fact_checker", "final_analyzer")
workflow.add_edge("final_analyzer", "archive_case")
workflow.add_edge("archive_case", END)

# Compile the graph
app = workflow.compile()


# ==============================================================================
# WRAPPER FUNCTION FOR API USAGE
# ==============================================================================

def analyze_text(transcript: str) -> dict:
    """Wrapper function to analyze transcript and return verdict result with case_id"""
    try:
        # Generate case_id upfront so it's available throughout pipeline
        case_id = str(uuid.uuid4())
        print(f"\n   PIPELINE START: Generated case_id {case_id}")
        
        result = app.invoke({"transcript": transcript, "case_id": case_id})
        verdict = result.get('final_verdict', {})
        final_case_id = result.get('case_id', case_id)
        
        if final_case_id:
            if isinstance(verdict, dict):
                verdict['case_id'] = final_case_id
            else:
                verdict_dict = verdict.dict() if hasattr(verdict, 'dict') else {}
                verdict_dict['case_id'] = final_case_id
                return verdict_dict
        
        return verdict
    except Exception as e:
        print(f"Error analyzing text: {e}")
        return {"error": str(e)}

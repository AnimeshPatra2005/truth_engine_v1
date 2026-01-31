"""
Courtroom Graph - LangGraph Workflow Assembly.
Orchestrates the fact-checking pipeline with Evidence Enrichment Loop.

FLOW:
  Decomposer → [claims < 5?] → Advocate (with extras) → Lead Promoter → Advocate (standard) → Fact Checker → Judge
              → [claims >= 5] → Advocate (standard) → Fact Checker → Judge
"""
from langgraph.graph import StateGraph, END, START

from .schemas import CourtroomState
from .nodes.query_generator import claim_decomposer_node
from .nodes.advocate import evidence_extraction_with_extras, evidence_extraction_standard
from .nodes.lead_promoter import lead_promoter_node
from .nodes.verifier import three_tier_fact_check_node_batched
from .nodes.judge import final_analysis_node


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

# Both paths converge to fact checker
workflow.add_edge("advocate_standard", "fact_checker")
workflow.add_edge("fact_checker", "final_analyzer")
workflow.add_edge("final_analyzer", END)

# Compile the graph
app = workflow.compile()


# ==============================================================================
# WRAPPER FUNCTION FOR API USAGE
# ==============================================================================

def analyze_text(transcript: str) -> dict:
    """Wrapper function to analyze transcript and return verdict result"""
    try:
        result = app.invoke({"transcript": transcript})
        return result.get('final_verdict', {})
    except Exception as e:
        print(f"Error analyzing text: {e}")
        return {"error": str(e)}

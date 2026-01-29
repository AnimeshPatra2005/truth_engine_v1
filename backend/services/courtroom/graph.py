"""
Courtroom Graph - LangGraph Workflow Assembly.
Orchestrates the fact-checking pipeline.
"""
from langgraph.graph import StateGraph, END, START

from .schemas import CourtroomState
from .nodes.query_generator import claim_decomposer_node
from .nodes.advocate import evidence_extraction_node
from .nodes.verifier import three_tier_fact_check_node_batched
from .nodes.judge import final_analysis_node


# ==============================================================================
# WORKFLOW DEFINITION
# ==============================================================================

workflow = StateGraph(CourtroomState)

# Add nodes
workflow.add_node("claim_decomposer", claim_decomposer_node)
workflow.add_node("evidence_extractor", evidence_extraction_node)
workflow.add_node("fact_checker", three_tier_fact_check_node_batched)
workflow.add_node("final_analyzer", final_analysis_node)

# Define edges
workflow.add_edge(START, "claim_decomposer")
workflow.add_edge("claim_decomposer", "evidence_extractor")
workflow.add_edge("evidence_extractor", "fact_checker")
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

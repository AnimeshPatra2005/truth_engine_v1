"""
LLM Engine - Façade for the Courtroom Fact-Checking Pipeline.

This file provides backward compatibility by re-exporting all public
APIs from the modular courtroom package.

The actual implementation has been refactored into:
- courtroom/schemas.py     - Pydantic data models
- courtroom/config.py      - Configuration and trusted domains
- courtroom/llm_setup.py   - LLM initialization
- courtroom/utils.py       - Helper functions
- courtroom/nodes/         - Pipeline nodes (query_generator, advocate, verifier, judge)
- courtroom/graph.py       - LangGraph workflow
"""

# ==============================================================================
# RE-EXPORTS FROM MODULAR PACKAGE
# ==============================================================================

# Schemas
from services.courtroom.schemas import (
    ClaimUnit,
    DecomposedClaims,
    Evidence,
    ClaimEvidence,
    VerifiedEvidence,
    ClaimAnalysis,
    FinalVerdict,
    CourtroomState,
)

# Configuration
from services.courtroom.config import (
    TRUSTED_DOMAINS,
    extract_domain,
    get_domain_trust_level,
    is_trusted_domain,
)

# LLM Setup
from services.courtroom.llm_setup import (
    MODEL_NAME,
    API_CALL_DELAY,
    MAX_RETRIES_ON_QUOTA,
    llm_decomposer,
    llm_analyzer,
    llm_judge,
    llm_fallback,
    get_llm_for_task,
    get_balanced_llm,
    api_call_count,
)

# Utilities
from services.courtroom.utils import (
    clean_llm_json,
    safe_invoke_json,
    safe_invoke_json_array,
    search_web_with_count,
    check_google_fact_check_tool,
    consensus_search_tool,
)

# Nodes
from services.courtroom.nodes.query_generator import claim_decomposer_node
from services.courtroom.nodes.advocate import evidence_extraction_node
from services.courtroom.nodes.verifier import (
    three_tier_fact_check_node,
    three_tier_fact_check_node_batched,
    analyze_consensus_with_gemini,
    analyze_consensus_batch,
)
from services.courtroom.nodes.judge import (
    final_analysis_node,
    print_verdict_report,
)

# Graph & Workflow
from services.courtroom.graph import (
    workflow,
    app,
    analyze_text,
)


# ==============================================================================
# LEGACY COMPATIBILITY
# ==============================================================================
# Any code importing from llm_engine will continue to work unchanged.
# Example:
#   from services.llm_engine import analyze_text, print_verdict_report
#   result = analyze_text("Some claim to fact-check")
#   print_verdict_report(result)

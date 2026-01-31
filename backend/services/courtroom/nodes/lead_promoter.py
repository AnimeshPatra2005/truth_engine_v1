"""
Lead Promoter Node - Convert Extra Evidence to New Claims.
PHASE 2.5 of the Courtroom Pipeline (Enrichment Loop).

Collects extra_evidence from all claims, deduplicates, selects top X,
and converts them into new ClaimUnit objects for investigation.
"""
from typing import List
from pydantic import BaseModel, Field

from ..schemas import CourtroomState, ClaimUnit, DecomposedClaims
from ..utils import safe_invoke_json
from ..llm_setup import get_llm_for_task


class PromotedClaims(BaseModel):
    """LLM output for selected claims to promote."""
    selected_claims: List[ClaimUnit] = Field(description="List of new claims derived from extra evidence")


def lead_promoter_node(state: CourtroomState):
    """
    Collect all extra_evidence, select top X, convert to ClaimUnits.
    
    X = 5 - original_claim_count (to reach minimum 5 claims)
    """
    print("\nLEAD PROMOTER: Converting Extra Evidence to New Claims...")
    
    decomposed = state.get('decomposed_data')
    all_evidence = state.get('all_claim_evidence') or []
    
    if not decomposed or not all_evidence:
        print("   No data to process. Skipping.")
        return {}
    
    original_claim_count = len(decomposed.claims)
    x = max(0, 5 - original_claim_count)
    
    if x == 0:
        print(f"   Already have {original_claim_count} claims. No promotion needed.")
        return {}
    
    # Collect all extra evidence
    all_extras = []
    for claim_ev in all_evidence:
        if hasattr(claim_ev, 'extra_evidence') and claim_ev.extra_evidence:
            for extra in claim_ev.extra_evidence:
                extra_obj = extra if isinstance(extra, dict) else extra
                fact = extra_obj.get('key_fact') if isinstance(extra_obj, dict) else extra_obj.key_fact
                url = extra_obj.get('source_url') if isinstance(extra_obj, dict) else extra_obj.source_url
                all_extras.append({
                    "fact": fact,
                    "source_url": url
                })
    
    if not all_extras:
        print("   No extra evidence found. Skipping promotion.")
        return {}
    
    # Deduplicate by fact text (simple)
    seen_facts = set()
    unique_extras = []
    for extra in all_extras:
        fact_lower = extra['fact'].lower()[:100]  # First 100 chars for comparison
        if fact_lower not in seen_facts:
            seen_facts.add(fact_lower)
            unique_extras.append(extra)
    
    print(f"   Found {len(all_extras)} extras, {len(unique_extras)} unique")
    print(f"   Need to promote: {x} extras to new claims")
    
    # Build extras text for LLM
    extras_text = "\n".join([
        f"{i+1}. [{e['source_url'][:50]}...] {e['fact']}"
        for i, e in enumerate(unique_extras)
    ])
    
    # Get the next claim ID
    max_id = max(c.id for c in decomposed.claims)
    
    prompt = f"""
    You have {len(unique_extras)} extra evidence items that were found tangentially during fact-checking.
    Select the TOP {x} most important ones and convert them into new claims for investigation.
    
    IMPLICATION BEING VERIFIED: "{decomposed.implication}"
    
    EXTRA EVIDENCE ITEMS:
    {extras_text}
    
    TASK:
    1. Select the {x} most relevant items that would help verify the overall implication
    2. Convert each into a proper claim with prosecutor and defender queries
    3. Assign sequential IDs starting from {max_id + 1}
    
    OUTPUT FORMAT:
    Return a JSON object:
    {{
      "selected_claims": [
        {{
          "id": {max_id + 1},
          "claim_text": "Clear, testable statement derived from the extra evidence",
          "topic_category": "Appropriate category",
          "prosecutor_query": "Query to find evidence DISPROVING this AND (debunked) AND (supporting evidence)",
          "defender_query": "Query to find evidence SUPPORTING this AND (verified) AND (supporting evidence)"
        }}
      ]
    }}
    
    CRITICAL: Create exactly {x} new claims. Each must be testable and specific.
    """
    
    result = safe_invoke_json(get_llm_for_task("decompose"), prompt, PromotedClaims)
    
    if result and result.get('selected_claims'):
        new_claims = [ClaimUnit(**c) for c in result['selected_claims']]
        
        # Append new claims to decomposed_data
        updated_claims = list(decomposed.claims) + new_claims
        updated_decomposed = DecomposedClaims(
            implication=decomposed.implication,
            claims=updated_claims
        )
        
        print(f"   Promoted {len(new_claims)} extras to new claims")
        for claim in new_claims:
            print(f"      [{claim.id}] {claim.claim_text[:60]}...")
        
        return {"decomposed_data": updated_decomposed}
    else:
        print("   Lead promotion failed. Continuing without new claims.")
        return {}

"""
Judge Node - Final Analysis and Verdict.
PHASE 4 of the Courtroom Pipeline.

Synthesizes all verified evidence to produce:
- Individual claim analyses with verdicts
- Overall implication connection
- Final verdict (True/False/Partially True/Unverified)
"""
from ..schemas import CourtroomState, FinalVerdict, ClaimAnalysis
from ..utils import safe_invoke_json
from ..llm_setup import get_llm_for_task


def final_analysis_node(state: CourtroomState):
    """
    PHASE 4: Judge Analysis - Single API Call for ALL Claims + Final Verdict
    Takes all verified evidence and produces:
    - Individual claim analyses with verdicts
    - Overall implication connection

    Target: 1 API call total
    """
    print("\nFINAL ANALYSIS: Judge Writing Verdict...")
    print("TARGET: 1 API call for all claims + implication")

    decomposed = state.get('decomposed_data')
    verified_evidence = state.get('verified_evidence', [])

    if not decomposed or not verified_evidence:
        print("Insufficient data for final analysis. Skipping.")
        return {"final_verdict": None}

    # Build comprehensive evidence summary
    all_claims_summary = ""

    for verified_claim in verified_evidence:
        claim_id = verified_claim['claim_id']
        
        # Find the original claim
        original_claim = None
        for claim in decomposed.claims:
            if claim.id == claim_id:
                original_claim = claim
                break
        
        if not original_claim:
            continue
        
        all_claims_summary += f"\n{'='*70}\n"
        all_claims_summary += f"CLAIM #{claim_id}: {original_claim.claim_text}\n"
        all_claims_summary += f"CATEGORY: {original_claim.topic_category}\n"
        all_claims_summary += f"{'='*70}\n"
        
        # Prosecutor Evidence
        all_claims_summary += "\nPROSECUTOR EVIDENCE (Contradicting):\n"
        for i, evidence in enumerate(verified_claim['verified_prosecutor'], 1):
            ev_obj = evidence if isinstance(evidence, dict) else evidence
            ev_fact = ev_obj.get('key_fact') if isinstance(ev_obj, dict) else ev_obj.key_fact
            ev_url = ev_obj.get('source_url') if isinstance(ev_obj, dict) else ev_obj.source_url
            ev_trust = ev_obj.get('trust_score') if isinstance(ev_obj, dict) else ev_obj.trust_score
            ev_method = ev_obj.get('verification_method') if isinstance(ev_obj, dict) else ev_obj.verification_method
            ev_details = ev_obj.get('verification_details') if isinstance(ev_obj, dict) else ev_obj.verification_details
            
            all_claims_summary += f"\n  [{i}] FACT: {ev_fact}\n"
            all_claims_summary += f"      SOURCE: {ev_url}\n"
            all_claims_summary += f"      TRUST: {ev_trust}\n"
            all_claims_summary += f"      VERIFICATION: {ev_method}\n"
            all_claims_summary += f"      DETAILS: {ev_details}\n"
        
        if not verified_claim['verified_prosecutor']:
            all_claims_summary += "  No contradicting evidence found.\n"
        
        # Defender Evidence
        all_claims_summary += "\nDEFENDER EVIDENCE (Supporting):\n"
        for i, evidence in enumerate(verified_claim['verified_defender'], 1):
            ev_obj = evidence if isinstance(evidence, dict) else evidence
            ev_fact = ev_obj.get('key_fact') if isinstance(ev_obj, dict) else ev_obj.key_fact
            ev_url = ev_obj.get('source_url') if isinstance(ev_obj, dict) else ev_obj.source_url
            ev_trust = ev_obj.get('trust_score') if isinstance(ev_obj, dict) else ev_obj.trust_score
            ev_method = ev_obj.get('verification_method') if isinstance(ev_obj, dict) else ev_obj.verification_method
            ev_details = ev_obj.get('verification_details') if isinstance(ev_obj, dict) else ev_obj.verification_details
            
            all_claims_summary += f"\n  [{i}] FACT: {ev_fact}\n"
            all_claims_summary += f"      SOURCE: {ev_url}\n"
            all_claims_summary += f"      TRUST: {ev_trust}\n"
            all_claims_summary += f"      VERIFICATION: {ev_method}\n"
            all_claims_summary += f"      DETAILS: {ev_details}\n"
        
        if not verified_claim['verified_defender']:
            all_claims_summary += "  No supporting evidence found.\n"
        
        all_claims_summary += "\n"

    # Create analysis prompt
    analysis_prompt = f"""
    You are the Supreme Court Chief Justice delivering the FINAL COMPREHENSIVE VERDICT.

    CORE IMPLICATION UNDER REVIEW:
    "{decomposed.implication}"

    ALL CLAIMS WITH VERIFIED EVIDENCE:
    {all_claims_summary}

    YOUR TASK:
    Analyze ALL claims and produce a complete verdict structure.

    FOR EACH CLAIM:
    1. Determine status: "Verified", "Debunked", or "Unclear"
       - "Verified" if supporting evidence is stronger and from high-trust sources
       - "Debunked" if contradicting evidence is stronger and from high-trust sources
       - "Unclear" if evidence is balanced, low-trust, or insufficient

    2. Write your analysis in 2-4 SHORT PARAGRAPHS (total 150-250 words):
       - FIRST paragraph: State verdict clearly and explain main reasoning
       - SECOND paragraph: Cite specific supporting evidence with source names
       - THIRD paragraph (if needed): Cite contradicting evidence with source names
       - FOURTH paragraph (if needed): Final weighing of evidence quality
       
       IMPORTANT RULES:
       - DO NOT use "Claim #1", "Evidence #1", "Prosecutor Evidence #2" etc.
       - Instead, describe evidence naturally: "According to Wikipedia...", "A BBC report states..."
       - Mention source names (Wikipedia, BBC, WHO) inline, not numbered references
       - Keep each paragraph 2-4 sentences max for readability

    FOR OVERALL IMPLICATION:
    1. Determine overall verdict:
       - "True" if implication supported by verified claims
       - "False" if implication contradicted by debunked claims
       - "Partially True" if some claims verified, others debunked
       - "Unverified" if most claims unclear or insufficient evidence

    2. Write your analysis in 2-4 SHORT PARAGRAPHS (total 200-300 words):
       - FIRST paragraph: State overall verdict and core reasoning
       - SECOND paragraph: Summarize what the supporting evidence shows
       - THIRD paragraph: Summarize what the contradicting evidence shows
       - FOURTH paragraph: Final conclusion on whether the implication holds
       
       DO NOT use "Claim #1 is verified" - instead say "The claim about X was verified..."

    OUTPUT FORMAT:
    Return JSON object with this structure:
    {{
      "overall_verdict": "True" | "False" | "Partially True" | "Unverified",
      "implication_connection": "Your 2-4 paragraph analysis (200-300 words total)...",
      "claim_analyses": [
        {{
          "claim_id": 1,
          "claim_text": "The claim text",
          "status": "Verified" | "Debunked" | "Unclear",
          "detailed_paragraph": "Your 2-4 paragraph analysis (150-250 words total)...",
          "prosecutor_evidence": [...],
          "defender_evidence": [...]
        }}
      ]
    }}

    WRITING STYLE:
    - Professional, balanced, objective
    - Cite sources by NAME (Wikipedia, BBC, WHO), not by number
    - Never use internal jargon (Tier 1, Tier 2, prosecutor, defender)
    - Write for a general audience, not technical reviewers
    - Each paragraph should be scannable (2-4 sentences)

    CRITICAL: Include ALL claims in claim_analyses array. Each claim MUST have a detailed analysis.
    """

    # Use HIGH thinking for deep reasoning on final verdict
    final_verdict_data = safe_invoke_json(get_llm_for_task("judge"), analysis_prompt, FinalVerdict)

    if final_verdict_data:
        # Ensure verified evidence is properly attached to each claim analysis
        for i, analysis in enumerate(final_verdict_data.get('claim_analyses', [])):
            analysis_id = analysis.get('claim_id')
            
            # Find matching verified evidence
            for verified_claim in verified_evidence:
                if verified_claim['claim_id'] == analysis_id:
                    # Attach verified evidence if not already present
                    if not analysis.get('prosecutor_evidence'):
                        analysis['prosecutor_evidence'] = verified_claim['verified_prosecutor']
                    if not analysis.get('defender_evidence'):
                        analysis['defender_evidence'] = verified_claim['verified_defender']
                    break
        
        final_verdict = FinalVerdict(**final_verdict_data)
        
        print(f"    Final Analysis Complete")
        print(f"    Overall Verdict: {final_verdict.overall_verdict}")
        print(f"    Total Claims Analyzed: {len(final_verdict.claim_analyses)}")
        print(f"    API Calls: 1")
        
        return {"final_verdict": final_verdict}
    else:
        print(f"    Final analysis generation failed")
        # Create fallback verdict
        fallback_analyses = []
        for verified_claim in verified_evidence:
            fallback_analyses.append(ClaimAnalysis(
                claim_id=verified_claim['claim_id'],
                claim_text="Claim analysis unavailable",
                status="Unclear",
                detailed_paragraph="Unable to complete analysis due to system error.",
                prosecutor_evidence=verified_claim['verified_prosecutor'][:2],
                defender_evidence=verified_claim['verified_defender'][:2]
            ))
        
        fallback_verdict = FinalVerdict(
            overall_verdict="Unverified",
            implication_connection=f"Unable to reach a final verdict on the implication '{decomposed.implication}' due to analysis errors.",
            claim_analyses=fallback_analyses
        )
        return {"final_verdict": fallback_verdict}


# ==============================================================================
# PRETTY PRINTER FOR RESULTS
# ==============================================================================

def _get_trust_indicator(trust: str) -> str:
    """Return a colored indicator for trust level."""
    trust_lower = trust.lower() if trust else "unknown"
    if trust_lower == "high":
        return "[HIGH ✓]"
    elif trust_lower == "medium":
        return "[MEDIUM ~]"
    elif trust_lower == "low":
        return "[LOW ⚠]"
    return "[UNKNOWN]"

def print_verdict_report(verdict_dict):
    """Pretty print the final verdict"""
    if not verdict_dict:
        print("No verdict data to display")
        return
    
    v = verdict_dict

    print("\n" + "="*80)
    print("FINAL VERDICT REPORT")
    print("="*80)

    # Overall Verdict
    overall = v.get('overall_verdict') if isinstance(v, dict) else v.overall_verdict
    print(f"\nOVERALL VERDICT: {overall.upper()}")
    print("="*80)

    # Implication Connection
    connection = v.get('implication_connection') if isinstance(v, dict) else v.implication_connection
    print(f"\nANALYSIS:\n")
    print(connection)

    # Individual Claim Analyses
    analyses = v.get('claim_analyses') if isinstance(v, dict) else v.claim_analyses

    if analyses:
        print("\n" + "="*80)
        print("CLAIM-BY-CLAIM BREAKDOWN")
        print("="*80)
        
        for analysis in analyses:
            a_text = analysis.get('claim_text') if isinstance(analysis, dict) else analysis.claim_text
            a_status = analysis.get('status') if isinstance(analysis, dict) else analysis.status
            a_para = analysis.get('detailed_paragraph') if isinstance(analysis, dict) else analysis.detailed_paragraph
            a_pros = analysis.get('prosecutor_evidence') if isinstance(analysis, dict) else analysis.prosecutor_evidence
            a_def = analysis.get('defender_evidence') if isinstance(analysis, dict) else analysis.defender_evidence
            
            print(f"\n{'='*80}")
            print(f"CLAIM: {a_text}")
            print(f"STATUS: {a_status.upper()}")
            print(f"{'='*80}")
            
            print(f"\n{a_para}")
            
            # Build sources list with indices
            all_sources = []
            
            # Contradicting Evidence
            if a_pros:
                print(f"\n📛 Contradicting Evidence:")
                for fact in a_pros:
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    
                    idx = len(all_sources) + 1
                    all_sources.append({"index": idx, "url": f_url, "trust": f_trust})
                    
                    trust_indicator = _get_trust_indicator(f_trust)
                    print(f"\n   • {f_key} [{idx}] {trust_indicator}")
            
            # Supporting Evidence
            if a_def:
                print(f"\n✅ Supporting Evidence:")
                for fact in a_def:
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    
                    idx = len(all_sources) + 1
                    all_sources.append({"index": idx, "url": f_url, "trust": f_trust})
                    
                    trust_indicator = _get_trust_indicator(f_trust)
                    print(f"\n   • {f_key} [{idx}] {trust_indicator}")
            
            # Print sources list
            if all_sources:
                print(f"\n📚 Sources:")
                for src in all_sources:
                    print(f"   [{src['index']}] {src['url']} ({src['trust']} Trust)")

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
       - "Verified" if defender evidence is stronger, from high-trust sources
       - "Debunked" if prosecutor evidence is stronger, from high-trust sources
       - "Unclear" if evidence is balanced, low-trust, or insufficient

    2. Write a DETAILED PARAGRAPH (150-250 words) that:
       - States verdict clearly in opening sentence
       - Explains reasoning behind verdict
       - References SPECIFIC evidence from both sides
       - Compares quality and credibility of sources
       - Addresses trust scores and verification methods
       - Includes specific facts, numbers, dates, citations from evidence
       - Makes reasoning crystal clear

    FOR OVERALL IMPLICATION:
    1. Determine overall verdict:
       - "True" if implication supported by verified claims
       - "False" if implication contradicted by debunked claims
       - "Partially True" if some claims verified, others debunked
       - "Unverified" if most claims unclear or insufficient evidence

    2. Write LONG DETAILED PARAGRAPH (200-300 words) that:
       - Opens with clear overall verdict statement
       - Explains HOW implication relates to individual claims
       - Connects dots between verified/debunked/unclear claims
       - Addresses SELECTIVE USE OF FACTS if applicable
       - Explains what evidence collectively reveals
       - Discusses correlation vs causation where relevant
       - Provides comprehensive, nuanced conclusion
       - References specific claims by number

    OUTPUT FORMAT:
    Return JSON object with this structure:
    {{
      "overall_verdict": "True" | "False" | "Partially True" | "Unverified",
      "implication_connection": "Your 200-300 word comprehensive paragraph...",
      "claim_analyses": [
        {{
          "claim_id": 1,
          "claim_text": "The claim text",
          "status": "Verified" | "Debunked" | "Unclear",
          "detailed_paragraph": "Your 150-250 word analysis...",
          "prosecutor_evidence": [...],
          "defender_evidence": [...]
        }}
      ]
    }}

    WRITING STYLE:
    - Professional, balanced, objective
    - Reference specific evidence with sources
    - Compare evidence quality explicitly
    - Explain trust scores and verification tiers
    - Make connections explicit and clear

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
    print(f"\nIMPLICATION ANALYSIS:\n")
    print(connection)

    # Individual Claim Analyses
    analyses = v.get('claim_analyses') if isinstance(v, dict) else v.claim_analyses

    if analyses:
        print("\n" + "="*80)
        print("DETAILED CLAIM-BY-CLAIM ANALYSIS")
        print("="*80)
        
        for analysis in analyses:
            a_id = analysis.get('claim_id') if isinstance(analysis, dict) else analysis.claim_id
            a_text = analysis.get('claim_text') if isinstance(analysis, dict) else analysis.claim_text
            a_status = analysis.get('status') if isinstance(analysis, dict) else analysis.status
            a_para = analysis.get('detailed_paragraph') if isinstance(analysis, dict) else analysis.detailed_paragraph
            a_pros = analysis.get('prosecutor_evidence') if isinstance(analysis, dict) else analysis.prosecutor_evidence
            a_def = analysis.get('defender_evidence') if isinstance(analysis, dict) else analysis.defender_evidence
            
            print(f"\n{'='*80}")
            print(f"CLAIM #{a_id}: {a_text}")
            print(f"STATUS: {a_status}")
            print(f"{'='*80}")
            
            print(f"\n{a_para}")
            
            # Prosecutor Facts
            if a_pros:
                print(f"\nPROSECUTOR FACTS (Contradicting):")
                for i, fact in enumerate(a_pros, 1):
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    f_method = fact.get('verification_method') if isinstance(fact, dict) else fact.verification_method
                    f_details = fact.get('verification_details') if isinstance(fact, dict) else fact.verification_details
                    
                    print(f"\n   {i}. {f_key}")
                    print(f"       Source: {f_url}")
                    print(f"       Trust: {f_trust}")
                    print(f"       Verification: {f_method}")
                    print(f"       Details: {f_details}")
            else:
                print(f"\nPROSECUTOR FACTS: No contradicting evidence found")
            
            # Defender Facts
            if a_def:
                print(f"\nDEFENDER FACTS (Supporting):")
                for i, fact in enumerate(a_def, 1):
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    f_method = fact.get('verification_method') if isinstance(fact, dict) else fact.verification_method
                    f_details = fact.get('verification_details') if isinstance(fact, dict) else fact.verification_details
                    
                    print(f"\n   {i}. {f_key}")
                    print(f"       Source: {f_url}")
                    print(f"       Trust: {f_trust}")
                    print(f"       Verification: {f_method}")
                    print(f"       Details: {f_details}")
            else:
                print(f"\nDEFENDER FACTS: No supporting evidence found")

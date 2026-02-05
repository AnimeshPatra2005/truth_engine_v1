"""
Advocate Node - Evidence Extraction for Prosecutor & Defender.
PHASE 2 of the Courtroom Pipeline.

Handles evidence collection for BOTH sides in a single efficient pass:
- Prosecutor: Searches for evidence CONTRADICTING the claim
- Defender: Searches for evidence SUPPORTING the claim

DUAL-PROMPT SYSTEM:
- Prompt A (first pass, claims < 5): Extract 2P + 2D + 2 extras (for implication)
- Prompt B (standard): Extract 2P + 2D only
"""
from ..schemas import CourtroomState, ClaimEvidence, Evidence, DecomposedClaims
from ..utils import safe_invoke_json, search_web_with_count
from ..llm_setup import get_llm_for_task


def _build_evidence_text(prosecutor_results: list, defender_results: list) -> str:
    """Build combined evidence text from search results.
    
    NOTE: We intentionally DO NOT label sources as prosecutor/defender.
    The LLM should analyze each source's content and decide whether it
    contradicts or supports the claim - regardless of which search query
    returned it. A "defender query" might return contradicting evidence!
    """
    # Combine all results into a single unlabeled pool
    all_results = []
    if prosecutor_results:
        all_results.extend(prosecutor_results)
    if defender_results:
        all_results.extend(defender_results)
    
    if not all_results:
        return ""
    
    all_evidence_text = "\n[SEARCH RESULTS - Analyze each source to determine if it CONTRADICTS or SUPPORTS the claim]\n"
    
    for i, result in enumerate(all_results):
        all_evidence_text += f"\nSource {i+1}:\n"
        all_evidence_text += f"URL: {result.get('url', 'unknown')}\n"
        all_evidence_text += f"Title: {result.get('title', 'Untitled')}\n"
        all_evidence_text += f"Content: {result.get('snippet', '')[:2000]}\n"
        all_evidence_text += "-" * 60 + "\n"
    
    return all_evidence_text


def _get_extraction_prompt(claim, all_evidence_text: str, implication: str, include_extras: bool) -> str:
    """Generate extraction prompt - with or without extra evidence."""
    
    base_rules = """
        YOUR TASK:
        Analyze ALL provided search results and extract facts that either CONTRADICT or SUPPORT the claim.
        You must determine the stance of each fact based on its CONTENT, not which search returned it.
        
        EXTRACTION RULES:
        1. Extract UP TO 2 PROSECUTOR facts - facts that CONTRADICT or cast doubt on the claim
        2. Extract UP TO 2 DEFENDER facts - facts that SUPPORT or validate the claim
        3. Analyze EACH source carefully - a source may contain BOTH contradicting AND supporting facts
        
        CRITICAL - QUALITY OVER QUANTITY:
        - If NO sources contain relevant CONTRADICTING evidence, return EMPTY prosecutor_facts: []
        - If NO sources contain relevant SUPPORTING evidence, return EMPTY defender_facts: []
        - Do NOT fabricate, stretch, or force-fit evidence that doesn't genuinely match the side
        - It is PERFECTLY ACCEPTABLE to return 0, 1, or 2 facts per side based on what actually exists
        - A one-sided result (only support OR only contradiction) is a valid outcome
        
        4. Each fact MUST contain SPECIFIC, CHECKABLE information:
           - Numbers, percentages, statistics
           - Dates, years, time periods
           - Names of people, organizations, studies
           - Citations to research, court cases, laws, scriptures
           - Direct quotes from authorities
        
        5. NO OVERLAP between facts - each fact must be unique and information-rich
        6. NO vague statements like:
            "Experts disagree"
            "Studies show"
            "According to sources"
            "It is believed"
        
        7. ONLY concrete facts like:
            "CDC study of 1.2M children found no MMR-autism link (JAMA, 2015)"
            "Wakefield's 1998 paper retracted by The Lancet in 2010 for data fraud"
            "Supreme Court ruling 2018/SC/1234 banned firecrackers in Delhi NCR"
        
        8. For EACH fact you extract, suggest 3-5 trusted domains for verification based on the claim category:
           - Science/Technology: nature.com, science.org, arxiv.org, ieee.org, nasa.gov
           - Law/Policy (India): indiankanoon.org, supremecourtofindia.nic.in, livelaw.in
           - Health/Medicine: who.int, cdc.gov, nih.gov, pubmed.ncbi.nlm.nih.gov
           - News/Viral: reuters.com, apnews.com, bbc.com, snopes.com
           - General: britannica.com, wikipedia.org, reuters.com, bbc.com
        
        9. SKIP extraction entirely for a side if:
           - No source genuinely contradicts/supports the claim
           - Sources only contain opinions without verifiable facts
           - Evidence is too weak or tangential to be useful
    """
    
    if include_extras:
        extra_rules = f"""
        
        9. ADDITIONALLY, extract EXACTLY 2 EXTRA EVIDENCE items:
           - These are TANGENTIAL facts that help verify the OVERALL IMPLICATION, not this specific claim
           - IMPLICATION: "{implication}"
           - Look for: names, dates, laws, studies, organizations mentioned in passing
           - These should be DIFFERENT from the prosecutor/defender facts
           - Set "side" to "prosecutor" or "defender" based on whether they challenge or support the implication
        """
        
        output_format = f"""
        OUTPUT FORMAT:
        Return a JSON object:
        {{
          "claim_id": {claim.id},
          "prosecutor_facts": [
            {{
              "source_url": "https://...",
              "key_fact": "Specific fact with numbers/dates/names/citations",
              "side": "prosecutor",
              "suggested_trusted_domains": ["domain1.com", "domain2.com", "domain3.com"]
            }}
          ],
          "defender_facts": [
            {{
              "source_url": "https://...",
              "key_fact": "Specific fact with numbers/dates/names/citations",
              "side": "defender",
              "suggested_trusted_domains": ["domain1.com", "domain2.com", "domain3.com"]
            }}
          ],
          "extra_evidence": [
            {{
              "source_url": "https://...",
              "key_fact": "Tangential fact that helps verify the implication",
              "side": "prosecutor" or "defender",
              "suggested_trusted_domains": ["domain1.com", "domain2.com", "domain3.com"]
            }}
          ]
        }}
        """
    else:
        extra_rules = ""
        output_format = f"""
        OUTPUT FORMAT:
        Return a JSON object:
        {{
          "claim_id": {claim.id},
          "prosecutor_facts": [
            {{
              "source_url": "https://...",
              "key_fact": "Specific fact with numbers/dates/names/citations",
              "side": "prosecutor",
              "suggested_trusted_domains": ["domain1.com", "domain2.com", "domain3.com"]
            }}
          ],
          "defender_facts": [
            {{
              "source_url": "https://...",
              "key_fact": "Specific fact with numbers/dates/names/citations",
              "side": "defender",
              "suggested_trusted_domains": ["domain1.com", "domain2.com", "domain3.com"]
            }}
          ]
        }}
        """
    
    prompt = f"""
        Extract evidence from search results for fact-checking.
        
        CLAIM TO ANALYZE: "{claim.claim_text}"
        CLAIM CATEGORY: {claim.topic_category}
        
        SEARCH RESULTS:
        {all_evidence_text}
        
        {base_rules}
        {extra_rules}
        {output_format}
        
        CRITICAL: 
        - QUALITY over QUANTITY - empty arrays are BETTER than garbage evidence
        - Each fact must be NON-OVERLAPPING and INFORMATION-RICH
        - If sources don't genuinely support a side, return [] for that side
        - No fabricated, stretched, or force-fit evidence allowed
    """
    
    return prompt


def evidence_extraction_node(state: CourtroomState, include_extras: bool = True):
    """
    PHASE 2: Search and Extract Evidence for ALL claims
    
    Args:
        state: Current pipeline state
        include_extras: If True, use Prompt A (with extras). If False, use Prompt B (standard).
    
    For each claim:
    - Run prosecutor query -> top 2 results
    - Run defender query -> top 2 results
    - Extract 2 prosecutor facts + 2 defender facts (+ 2 extras if include_extras)
    """
    mode = "WITH EXTRAS" if include_extras else "STANDARD"
    print(f"\nEVIDENCE EXTRACTION ({mode}): Searching and Extracting Facts...")
    
    decomposed = state.get('decomposed_data')
    if not decomposed:
        print("No claims to investigate. Skipping.")
        return {"all_claim_evidence": []}

    # Get existing evidence to avoid re-processing (idempotency for loop)
    existing_evidence = state.get('all_claim_evidence') or []
    processed_claim_ids = {e.claim_id for e in existing_evidence if hasattr(e, 'claim_id')}
    
    implication = decomposed.implication
    all_claim_evidence = list(existing_evidence)  # Start with existing
    extraction_api_calls = 0

    for claim in decomposed.claims:
        # Skip already processed claims (idempotency)
        if claim.id in processed_claim_ids:
            print(f"\n   Skipping Claim #{claim.id} (already processed)")
            continue
            
        print(f"\n   {'='*70}")
        print(f"    PROCESSING CLAIM #{claim.id}")
        print(f"   {'='*70}")
        print(f"   Claim: '{claim.claim_text}'")
        print(f"   Category: {claim.topic_category}")
        
        # 1. Web Search (No API calls)
        print(f"\n       STEP 1: Web Search (No API calls)")
        
        # Prosecutor Search
        print(f"       Prosecutor Query: {claim.prosecutor_query}")
        try:
            raw_pros_results = search_web_with_count(claim.prosecutor_query, num_results=5, intent="prosecutor")
            prosecutor_results = raw_pros_results if raw_pros_results and isinstance(raw_pros_results, list) else []
            print(f"          Retrieved {len(prosecutor_results)} prosecutor sources (using ALL)")
        except Exception as e:
            print(f"          Prosecutor search failed: {e}")
            prosecutor_results = []
        
        # Defender Search
        print(f"       Defender Query: {claim.defender_query}")
        try:
            raw_def_results = search_web_with_count(claim.defender_query, num_results=5, intent="defender")
            defender_results = raw_def_results if raw_def_results and isinstance(raw_def_results, list) else []
            print(f"          Retrieved {len(defender_results)} defender sources (using ALL)")
        except Exception as e:
            print(f"          Defender search failed: {e}")
            defender_results = []
        
       
        
        # 2. Extract Evidence (1 API call)
        print(f"\n       STEP 2: Extract Evidence {'+ Extras' if include_extras else '(Standard)'}")
        
        all_evidence_text = _build_evidence_text(prosecutor_results, defender_results)
        
        if not all_evidence_text:
            print(f"          No evidence found for this claim")
            all_claim_evidence.append(ClaimEvidence(
                claim_id=claim.id,
                prosecutor_facts=[],
                defender_facts=[],
                extra_evidence=[]
            ))
            continue
        
        extract_prompt = _get_extraction_prompt(claim, all_evidence_text, implication, include_extras)
        evidence_data = safe_invoke_json(get_llm_for_task("decompose"), extract_prompt, ClaimEvidence)
        
        if evidence_data:
            claim_evidence = ClaimEvidence(**evidence_data)
            all_claim_evidence.append(claim_evidence)
            
            extraction_api_calls += 1
            
            print(f"          Extracted {len(claim_evidence.prosecutor_facts)} prosecutor facts")
            print(f"          Extracted {len(claim_evidence.defender_facts)} defender facts")
            if include_extras:
                print(f"          Extracted {len(claim_evidence.extra_evidence)} extra evidence items")
        else:
            print(f"          Evidence extraction failed for claim {claim.id}")
            all_claim_evidence.append(ClaimEvidence(
                claim_id=claim.id,
                prosecutor_facts=[],
                defender_facts=[],
                extra_evidence=[]
            ))

    print(f"\n   {'='*70}")
    print(f"    EVIDENCE EXTRACTION COMPLETE ({mode})")
    print(f"   {'='*70}")
    print(f"   Total API calls for extraction: {extraction_api_calls}")

    return {"all_claim_evidence": all_claim_evidence}


# Wrapper functions for graph nodes
def evidence_extraction_with_extras(state: CourtroomState):
    """First pass: Extract 2P + 2D + 2 extras per claim."""
    return evidence_extraction_node(state, include_extras=True)


def evidence_extraction_standard(state: CourtroomState):
    """Second pass: Extract 2P + 2D only (no extras)."""
    return evidence_extraction_node(state, include_extras=False)

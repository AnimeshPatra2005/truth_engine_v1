"""
Advocate Node - Evidence Extraction for Prosecutor & Defender.
PHASE 2 of the Courtroom Pipeline.

Handles evidence collection for BOTH sides in a single efficient pass:
- Prosecutor: Searches for evidence CONTRADICTING the claim
- Defender: Searches for evidence SUPPORTING the claim
"""
from ..schemas import CourtroomState, ClaimEvidence, Evidence
from ..utils import safe_invoke_json, search_web_with_count
from ..llm_setup import get_llm_for_task


def evidence_extraction_node(state: CourtroomState):
    """
    PHASE 2: Search and Extract Evidence for ALL claims
    
    For each claim:
    - Run prosecutor query -> top 2 results
    - Run defender query -> top 2 results
    - Extract 2 prosecutor facts + 2 defender facts
    - Assign suggested trusted domains to each fact
    
    Target: 1 API call per claim (for extraction)
    """
    print("\nEVIDENCE EXTRACTION: Searching and Extracting Facts...")
    
    decomposed = state.get('decomposed_data')
    if not decomposed:
        print("No claims to investigate. Skipping.")
        return {"all_claim_evidence": []}

    all_claim_evidence = []
    extraction_api_calls = 0

    for claim in decomposed.claims:
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
            # Get 5 results, use top 2
            raw_pros_results = search_web_with_count(claim.prosecutor_query, num_results=5, intent="prosecutor")
            prosecutor_results = raw_pros_results[:2] if raw_pros_results and isinstance(raw_pros_results, list) else []
            print(f"          Retrieved {len(prosecutor_results)} prosecutor sources (from {len(raw_pros_results)} total)")
        except Exception as e:
            print(f"          Prosecutor search failed: {e}")
            prosecutor_results = []
        
        # Defender Search
        print(f"       Defender Query: {claim.defender_query}")
        try:
            # Get 5 results, use top 2
            raw_def_results = search_web_with_count(claim.defender_query, num_results=5, intent="defender")
            defender_results = raw_def_results[:2] if raw_def_results and isinstance(raw_def_results, list) else []
            print(f"          Retrieved {len(defender_results)} defender sources (from {len(raw_def_results)} total)")
        except Exception as e:
            print(f"          Defender search failed: {e}")
            defender_results = []
        
        # 2. Extract Evidence (1 API call)
        print(f"\n       STEP 2: Extract Evidence with Suggested Domains")
        
        # Build combined evidence text
        all_evidence_text = ""
        
        if prosecutor_results:
            all_evidence_text += "\n[PROSECUTOR SOURCES - Contradicting the claim]\n"
            for i, result in enumerate(prosecutor_results):
                all_evidence_text += f"\nSource {i+1}:\n"
                all_evidence_text += f"URL: {result.get('url', 'unknown')}\n"
                all_evidence_text += f"Title: {result.get('title', 'Untitled')}\n"
                all_evidence_text += f"Content: {result.get('snippet', '')[:800]}\n"
                all_evidence_text += "-" * 60 + "\n"
        
        if defender_results:
            all_evidence_text += "\n[DEFENDER SOURCES - Supporting the claim]\n"
            for i, result in enumerate(defender_results):
                all_evidence_text += f"\nSource {i+1}:\n"
                all_evidence_text += f"URL: {result.get('url', 'unknown')}\n"
                all_evidence_text += f"Title: {result.get('title', 'Untitled')}\n"
                all_evidence_text += f"Content: {result.get('snippet', '')[:800]}\n"
                all_evidence_text += "-" * 60 + "\n"
        
        if not all_evidence_text:
            print(f"          No evidence found for this claim")
            all_claim_evidence.append(ClaimEvidence(
                claim_id=claim.id,
                prosecutor_facts=[],
                defender_facts=[]
            ))
            continue
        
        # Single API call to extract all evidence
        extract_prompt = f"""
        Extract evidence from search results for fact-checking.
        
        CLAIM TO ANALYZE: "{claim.claim_text}"
        CLAIM CATEGORY: {claim.topic_category}
        
        SEARCH RESULTS:
        {all_evidence_text}
        
        EXTRACTION RULES:
        1. Extract EXACTLY 2 PROSECUTOR facts (contradicting the claim) from prosecutor sources
        2. Extract EXACTLY 2 DEFENDER facts (supporting the claim) from defender sources
        3. Each fact MUST contain SPECIFIC, CHECKABLE information:
           - Numbers, percentages, statistics
           - Dates, years, time periods
           - Names of people, organizations, studies
           - Citations to research, court cases, laws, scriptures
           - Direct quotes from authorities
        
        4. NO OVERLAP between facts - each fact must be unique and information-rich
        5. NO vague statements like:
            "Experts disagree"
            "Studies show"
            "According to sources"
            "It is believed"
        
        6. ONLY concrete facts like:
            "CDC study of 1.2M children found no MMR-autism link (JAMA, 2015)"
            "Wakefield's 1998 paper retracted by The Lancet in 2010 for data fraud"
            "Supreme Court ruling 2018/SC/1234 banned firecrackers in Delhi NCR"
            "Skanda Purana (Chapter 5, Verse 12) describes 'akash deepa' ritual"
            "Archaeological Survey of India Report 2010 shows no firecracker evidence before 1400 CE"
        
        7. For EACH fact, suggest 3-5 trusted domains for verification based on the claim category:
           - Science/Technology: nature.com, science.org, arxiv.org, ieee.org, nasa.gov
           - Law/Policy (India): indiankanoon.org, supremecourtofindia.nic.in, livelaw.in, barandbench.com
           - Law/Policy (Global): justia.com, law.cornell.edu, oecd.org, un.org
           - Politics/Geopolitics: mea.gov.in, un.org, cfr.org, brookings.edu, bbc.com
           - Mythology/Religion: sacred-texts.com, britannica.com, jstor.org, vedicheritage.gov.in, oxfordreference.com
           - History/Culture: britannica.com, jstor.org, asi.nic.in, nationalarchives.gov.in, oxfordreference.com
           - Health/Medicine: who.int, cdc.gov, nih.gov, pubmed.ncbi.nlm.nih.gov, mayoclinic.org
           - Environment/Climate: ipcc.ch, noaa.gov, epa.gov, climate.nasa.gov, nature.com
           - News/Viral: reuters.com, apnews.com, bbc.com, thehindu.com, altnews.in, snopes.com
           - General: britannica.com, wikipedia.org, reuters.com, bbc.com, snopes.com
        
        8. If insufficient evidence exists (less than 2 facts per side), extract what's available
        
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
        
        CRITICAL: Each fact must be NON-OVERLAPPING and INFORMATION-RICH. No general claims allowed.
        """
        # Use LOW thinking for structured evidence extraction
        evidence_data = safe_invoke_json(get_llm_for_task("decompose"), extract_prompt, ClaimEvidence)
        
        if evidence_data:
            claim_evidence = ClaimEvidence(**evidence_data)
            all_claim_evidence.append(claim_evidence)
            
            extraction_api_calls += 1
            
            print(f"          Extracted {len(claim_evidence.prosecutor_facts)} prosecutor facts")
            for i, fact in enumerate(claim_evidence.prosecutor_facts, 1):
                fact_obj = fact if isinstance(fact, dict) else fact
                fact_text = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
                source_url = fact_obj.get('source_url') if isinstance(fact_obj, dict) else fact_obj.source_url
                print(f"             {i}. [{source_url[:30]}...] {fact_text[:100]}...")
            
            print(f"          Extracted {len(claim_evidence.defender_facts)} defender facts")
            for i, fact in enumerate(claim_evidence.defender_facts, 1):
                fact_obj = fact if isinstance(fact, dict) else fact
                fact_text = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
                source_url = fact_obj.get('source_url') if isinstance(fact_obj, dict) else fact_obj.source_url
                print(f"             {i}. [{source_url[:30]}...] {fact_text[:100]}...")
        else:
            print(f"          Evidence extraction failed for claim {claim.id}")
            all_claim_evidence.append(ClaimEvidence(
                claim_id=claim.id,
                prosecutor_facts=[],
                defender_facts=[]
            ))

    print(f"\n   {'='*70}")
    print(f"    EVIDENCE EXTRACTION COMPLETE")
    print(f"   {'='*70}")
    print(f"   Total API calls for extraction: {extraction_api_calls}")

    return {"all_claim_evidence": all_claim_evidence}

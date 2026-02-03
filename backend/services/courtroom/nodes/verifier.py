"""
Verifier Node - Three-Tier Fact-Checking.
PHASE 3 of the Courtroom Pipeline.

Verifies each piece of evidence using:
- Tier 1: Google Fact Check API
- Tier 2: Domain Trust Scoring
- Tier 3: Web Consensus Analysis (with batching)
"""
from typing import Literal, List
from pydantic import BaseModel, Field

from ..schemas import CourtroomState, VerifiedEvidence
from ..config import get_domain_trust_level, is_trusted_domain, extract_domain, TRUSTED_DOMAINS
from ..utils import (
    safe_invoke_json, safe_invoke_json_array,
    check_google_fact_check_tool, consensus_search_tool
)
from ..llm_setup import get_llm_for_task


# ==============================================================================
# CONSENSUS ANALYSIS HELPERS
# ==============================================================================

class ConsensusAnalysis(BaseModel):
    supports: int = Field(description="Number of sources supporting the claim")
    contradicts: int = Field(description="Number of sources contradicting the claim")
    neutral: int = Field(description="Number of neutral/unclear sources")
    confidence: Literal["High", "Medium", "Low"] = Field(description="Confidence level based on agreement percentage")
    reasoning: str = Field(description="Brief explanation of consensus pattern")
    majority_urls: List[str] = Field(default=[], description="URLs of sources that voted in the majority")


def analyze_consensus_with_gemini(claim: str, search_results: list) -> dict:
    """
    Analyzes search results using Gemini to determine consensus.
    
    Returns:
        {
            "supports": int,  # Number of sources supporting the claim
            "contradicts": int,  # Number of sources contradicting
            "neutral": int,  # Number of neutral/unclear sources
            "confidence": "High" | "Medium" | "Low",
            "reasoning": str
        }
    """
    if not search_results:
        return {
            "supports": 0,
            "contradicts": 0,
            "neutral": 0,
            "confidence": "Low",
            "reasoning": "No search results available for consensus analysis"
        }
    
    # Build summary of all search results
    results_text = ""
    for i, result in enumerate(search_results, 1):
        results_text += f"\n--- SOURCE {i} ---\n"
        results_text += f"Title: {result.get('title', 'Untitled')}\n"
        results_text += f"URL: {result.get('url', 'unknown')}\n"
        results_text += f"Content: {result.get('snippet', '')[:500]}\n"
        results_text += f"Relevance Score: {result.get('score', 0)}\n"
    
    prompt = f"""
    Analyze these {len(search_results)} search results to determine web consensus on a claim.
    
    CLAIM TO VERIFY: "{claim}"
    
    SEARCH RESULTS:
    {results_text}
    
    YOUR TASK:
    For EACH of the {len(search_results)} sources, determine if it:
    - SUPPORTS the claim (agrees, confirms, provides evidence for)
    - CONTRADICTS the claim (disagrees, debunks, provides evidence against)
    - NEUTRAL (doesn't clearly support or contradict, or is ambiguous)
    
    Count carefully and provide:
    1. Number supporting
    2. Number contradicting
    3. Number neutral
    4. Overall confidence level:
       - "High" if 70%+ agree (7+ out of 10 support OR contradict)
       - "Medium" if 50-69% agree (5-6 out of 10)
       - "Low" if less than 50% agree (4 or fewer, or conflicting results)
    5. Brief reasoning (2-3 sentences)
    6. **majority_urls**: List of URLs that voted in the MAJORITY (if 6 support, list those 6 URLs)
    
    OUTPUT FORMAT (JSON):
    {{
      "supports": <number>,
      "contradicts": <number>,
      "neutral": <number>,
      "confidence": "High" | "Medium" | "Low",
      "reasoning": "Brief explanation of the consensus pattern",
      "majority_urls": ["url1", "url2", ...]
    }}
    
    IMPORTANT: 
    - The numbers MUST add up to {len(search_results)}
    - Be strict - only count clear support/contradiction
    - When in doubt, mark as neutral
    - In majority_urls, include ONLY the URLs that voted with the majority (supports OR contradicts, whichever is larger)
    """
    
    # Use MEDIUM thinking for consensus pattern recognition
    analysis = safe_invoke_json(get_llm_for_task("analyze"), prompt, ConsensusAnalysis)
    
    if not analysis:
        return {
            "supports": 0,
            "contradicts": 0,
            "neutral": len(search_results),
            "confidence": "Low",
            "reasoning": "Failed to analyze consensus"
        }
    
    return analysis


class SingleConsensusAnalysis(BaseModel):
    evidence_id: str
    supports: int
    contradicts: int
    neutral: int
    confidence: Literal["High", "Medium", "Low"]
    reasoning: str
    majority_urls: List[str] = Field(default=[], description="URLs of sources that voted in the majority")


def analyze_consensus_batch(evidence_list: list, search_results_map: dict) -> dict:
    """
    Batch analyze multiple evidence items using Gemini to determine consensus.
    Uses alternating API keys for load balancing.
    
    Args:
        evidence_list: List of dicts with {claim_id, evidence_id, fact_text, side}
        search_results_map: Dict mapping evidence_id to search results
    
    Returns:
        Dict mapping evidence_id to consensus analysis
    """
    if not evidence_list:
        return {}
    
    # Build structured input for Gemini
    batch_input = ""
    for i, evidence in enumerate(evidence_list, 1):
        evidence_id = evidence['evidence_id']
        fact_text = evidence['fact_text']
        side = evidence['side']
        
        batch_input += f"\n{'='*70}\n"
        batch_input += f"EVIDENCE #{i} (ID: {evidence_id}, Side: {side})\n"
        batch_input += f"{'='*70}\n"
        batch_input += f"FACT TO VERIFY: {fact_text}\n\n"
        
        # Add search results
        search_results = search_results_map.get(evidence_id, [])
        if search_results:
            batch_input += f"SEARCH RESULTS ({len(search_results)} sources):\n"
            for j, result in enumerate(search_results, 1):
                batch_input += f"\n--- SOURCE {j} ---\n"
                batch_input += f"Title: {result.get('title', 'Untitled')}\n"
                batch_input += f"URL: {result.get('url', 'unknown')}\n"
                batch_input += f"Content: {result.get('snippet', '')[:400]}\n"
        else:
            batch_input += "SEARCH RESULTS: None available\n"
        
        batch_input += "\n"
    
    prompt = f"""
    Analyze web consensus for MULTIPLE evidence items in a BATCH.
    
    You will receive {len(evidence_list)} different evidence items, each with its own search results.
    For EACH evidence item, determine if the search results support or contradict it.
    
    {batch_input}
    
    YOUR TASK:
    For EACH evidence item above, analyze its search results and determine:
    
    1. **supports**: Number of sources that SUPPORT the fact (agree, confirm, provide evidence for)
    2. **contradicts**: Number of sources that CONTRADICT the fact (disagree, debunk, provide evidence against)
    3. **neutral**: Number of sources that are NEUTRAL (unclear, ambiguous, or irrelevant)
    4. **confidence**: Overall confidence level:
       - "High" if 70%+ of sources agree (support OR contradict)
       - "Medium" if 50-69% agree
       - "Low" if <50% agree or conflicting results
    5. **reasoning**: Brief 2-3 sentence explanation
    6. **majority_urls**: List of URLs from the search results that voted in the MAJORITY
    
    IMPORTANT CONTEXT:
    - "Prosecutor" evidence = facts that CONTRADICT the original claim
    - "Defender" evidence = facts that SUPPORT the original claim
    
    For Prosecutor evidence:
    - If search results CONTRADICT the original claim → they SUPPORT this evidence
    - If search results SUPPORT the original claim → they CONTRADICT this evidence
    
    For Defender evidence:
    - If search results SUPPORT the original claim → they SUPPORT this evidence
    - If search results CONTRADICT the original claim → they CONTRADICT this evidence
    
    OUTPUT FORMAT (JSON):
    Return an array where each element corresponds to one evidence item:
    
    [
      {{
        "evidence_id": "evidence_1",
        "supports": <number>,
        "contradicts": <number>,
        "neutral": <number>,
        "confidence": "High" | "Medium" | "Low",
        "reasoning": "Brief explanation",
        "majority_urls": ["url1", "url2", ...]
      }},
      {{
        "evidence_id": "evidence_2",
        ...
      }}
    ]
    
    CRITICAL:
    - Return exactly {len(evidence_list)} analysis objects
    - Each analysis must have the correct evidence_id
    - Numbers must add up to the total number of search results for that evidence
    - Be strict - only count CLEAR support/contradiction
    - In majority_urls, include ONLY the URLs that voted with the majority verdict
    """
    
    # Use MEDIUM thinking for consensus pattern recognition
    analyses = safe_invoke_json_array(get_llm_for_task("analyze"), prompt, SingleConsensusAnalysis)
    
    if not analyses:
        # Fallback: return empty analysis for each evidence
        return {
            ev['evidence_id']: {
                "supports": 0,
                "contradicts": 0,
                "neutral": len(search_results_map.get(ev['evidence_id'], [])),
                "confidence": "Low",
                "reasoning": "Failed to analyze consensus"
            }
            for ev in evidence_list
        }
    
    # Convert list to dict mapping evidence_id to analysis
    return {
        analysis['evidence_id']: {
            "supports": analysis['supports'],
            "contradicts": analysis['contradicts'],
            "neutral": analysis['neutral'],
            "confidence": analysis['confidence'],
            "reasoning": analysis['reasoning'],
            "majority_urls": analysis.get('majority_urls', [])
        }
        for analysis in analyses
    }


# ==============================================================================
# MAIN VERIFIER NODE (BATCHED)
# ==============================================================================

def three_tier_fact_check_node_batched(state: CourtroomState):
    """
    PHASE 3: Three-Tier Fact-Checking with BATCHED Tier 3 Consensus
    
    Improvements:
    - Batch consensus checks in groups of 4
    - Alternate between API keys for load balancing
    - Reduce API calls from N to N/4 for Tier 3
    """
    print("\nTHREE-TIER FACT-CHECKING (BATCHED): Verifying All Evidence...")

    all_claim_evidence = state.get('all_claim_evidence')
    if not all_claim_evidence:
        print("No evidence to verify. Skipping.")
        return {}

    verified_claims = []
    
    # Collect all evidence that needs Tier 3 consensus check
    tier3_queue = []  # Will store: {evidence_id, claim_id, fact, url, side, suggested_domains}
    tier3_search_results = {}  # Will store search results for each evidence_id
    
    evidence_id_counter = 0

    # PASS 1: Tier 1 & 2 checks, queue Tier 3 items
    for claim_evidence in all_claim_evidence:
        claim_id = claim_evidence.claim_id if hasattr(claim_evidence, 'claim_id') else claim_evidence.get('claim_id')
        print(f"\n   {'='*70}")
        print(f"    PROCESSING CLAIM #{claim_id} - TIER 1 & 2")
        print(f"   {'='*70}")
        
        verified_prosecutor = []
        verified_defender = []
        
        # Process both prosecutor and defender facts
        for side_name, facts_list in [
            ('prosecutor', claim_evidence.prosecutor_facts if hasattr(claim_evidence, 'prosecutor_facts') else claim_evidence.get('prosecutor_facts', [])),
            ('defender', claim_evidence.defender_facts if hasattr(claim_evidence, 'defender_facts') else claim_evidence.get('defender_facts', []))
        ]:
            verified_list = verified_prosecutor if side_name == 'prosecutor' else verified_defender
            
            for fact in facts_list:
                fact_obj = fact if isinstance(fact, dict) else fact
                source_url = fact_obj.get('source_url') if isinstance(fact_obj, dict) else fact_obj.source_url
                key_fact = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
                suggested_domains = fact_obj.get('suggested_trusted_domains') if isinstance(fact_obj, dict) else fact_obj.suggested_trusted_domains
                
                print(f"\n       Verifying {side_name.title()} Fact: {key_fact[:60]}...")
                
                # TIER 1: Google Fact Check API
                tier1_result = check_google_fact_check_tool(key_fact)
                
                if "MATCH:" in tier1_result:
                    print(f"          TIER 1 VERIFIED")
                    verified_list.append(VerifiedEvidence(
                        source_url=source_url,
                        key_fact=key_fact,
                        side=side_name,
                        trust_score="High",
                        verification_method="Tier1-FactCheck",
                        verification_details=tier1_result,
                        supporting_urls=[]
                    ))
                    continue
                
                # TIER 2: Domain Trust Check
                domain_trust = get_domain_trust_level(source_url)
                is_suggested = is_trusted_domain(source_url, suggested_domains)
                
                if domain_trust == "High" or is_suggested:
                    tier2_details = f"Domain Trust: {domain_trust}, Matches Suggested: {is_suggested}"
                    print(f"          TIER 2 VERIFIED: {tier2_details}")
                    verified_list.append(VerifiedEvidence(
                        source_url=source_url,
                        key_fact=key_fact,
                        side=side_name,
                        trust_score=domain_trust,
                        verification_method="Tier2-Domain",
                        verification_details=tier2_details,
                        supporting_urls=[]
                    ))
                    continue
                
                # TIER 3: Queue for batch consensus check
                evidence_id_counter += 1
                evidence_id = f"ev_{claim_id}_{side_name}_{evidence_id_counter}"
                
                print(f"          → Queued for TIER 3 (Batch ID: {evidence_id})")
                
                # Run search now, store results for later batch analysis
                consensus_data = consensus_search_tool(key_fact[:100])
                
                if consensus_data.get("success"):
                    tier3_queue.append({
                        'evidence_id': evidence_id,
                        'claim_id': claim_id,
                        'fact_text': key_fact,
                        'source_url': source_url,
                        'side': side_name,
                        'suggested_domains': suggested_domains
                    })
                    tier3_search_results[evidence_id] = consensus_data.get("results", [])
                else:
                    # Search failed - mark as unverified immediately
                    verified_list.append(VerifiedEvidence(
                        source_url=source_url,
                        key_fact=key_fact,
                        side=side_name,
                        trust_score="Low",
                        verification_method="Unverified",
                        verification_details="Consensus search failed",
                        supporting_urls=[]
                    ))
        
        # Store intermediate results (will be updated after batch consensus)
        verified_claims.append({
            'claim_id': claim_id,
            'verified_prosecutor': verified_prosecutor,
            'verified_defender': verified_defender
        })
    
    # PASS 2: Batch process Tier 3 consensus checks
    if tier3_queue:
        print(f"\n   {'='*70}")
        print(f"    TIER 3 BATCH CONSENSUS CHECK")
        print(f"   {'='*70}")
        print(f"    Total evidence items queued: {len(tier3_queue)}")
        
        batch_size = 4
        num_batches = (len(tier3_queue) + batch_size - 1) // batch_size
        print(f"    Processing in {num_batches} batches of up to {batch_size} items each")
        
        all_consensus_results = {}
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(tier3_queue))
            batch = tier3_queue[start_idx:end_idx]
            
            print(f"\n       Processing Batch {batch_idx + 1}/{num_batches} ({len(batch)} items)...")
            
            # Batch analyze
            batch_results = analyze_consensus_batch(batch, tier3_search_results)
            all_consensus_results.update(batch_results)
            
            print(f"          Batch {batch_idx + 1} complete")
        
        # PASS 3: Update verified_claims with Tier 3 results
        print(f"\n       Applying Tier 3 results to claims...")
        
        for tier3_item in tier3_queue:
            evidence_id = tier3_item['evidence_id']
            claim_id = tier3_item['claim_id']
            side = tier3_item['side']
            
            consensus_analysis = all_consensus_results.get(evidence_id)
            
            if not consensus_analysis:
                consensus_analysis = {
                    "supports": 0,
                    "contradicts": 0,
                    "neutral": 0,
                    "confidence": "Low",
                    "reasoning": "Batch analysis failed"
                }
            
            # Find the claim in verified_claims
            for verified_claim in verified_claims:
                if verified_claim['claim_id'] == claim_id:
                    # Determine trust score based on consensus
                    supports = consensus_analysis['supports']
                    contradicts = consensus_analysis['contradicts']
                    confidence = consensus_analysis['confidence']
                    reasoning = consensus_analysis['reasoning']
                    
                    # Logic depends on side (prosecutor vs defender)
                    if side == 'prosecutor':
                        # Prosecutor evidence contradicts the claim
                        # So if consensus contradicts claim → supports prosecutor
                        if contradicts > supports:
                            trust_score = confidence
                            details = f"Consensus: {contradicts} contradict claim. {reasoning}"
                        elif supports > contradicts:
                            trust_score = "Low"
                            details = f"Consensus AGAINST prosecutor: {supports} support claim. {reasoning}"
                        else:
                            trust_score = "Low"
                            details = f"No clear consensus. {reasoning}"
                    else:  # defender
                        # Defender evidence supports the claim
                        # So if consensus supports claim → supports defender
                        if supports > contradicts:
                            trust_score = confidence
                            details = f"Consensus: {supports} support claim. {reasoning}"
                        elif contradicts > supports:
                            trust_score = "Low"
                            details = f"Consensus AGAINST defender: {contradicts} contradict claim. {reasoning}"
                        else:
                            trust_score = "Low"
                            details = f"No clear consensus. {reasoning}"
                    
                    # Create verified evidence object
                    verified_evidence = VerifiedEvidence(
                        source_url=tier3_item['source_url'],
                        key_fact=tier3_item['fact_text'],
                        side=side,
                        trust_score=trust_score,
                        verification_method="Tier3-Consensus-Batch",
                        verification_details=details,
                        supporting_urls=consensus_analysis.get('majority_urls', [])
                    )
                    
                    # Add to appropriate list
                    if side == 'prosecutor':
                        verified_claim['verified_prosecutor'].append(verified_evidence)
                    else:
                        verified_claim['verified_defender'].append(verified_evidence)
                    
                    break
        
        print(f"\n   {'='*70}")
        print(f"    TIER 3 BATCH PROCESSING COMPLETE")
        print(f"   {'='*70}")
        print(f"    API calls saved: {len(tier3_queue) - num_batches}")
        print(f"    (Would have been {len(tier3_queue)} calls, now only {num_batches} calls)")

    print(f"\n   {'='*70}")
    print(f"    FACT-CHECKING COMPLETE")
    print(f"   {'='*70}")

    return {'verified_evidence': verified_claims}


# ==============================================================================
# LEGACY VERIFIER NODE (NON-BATCHED)
# ==============================================================================

def three_tier_fact_check_node(state: CourtroomState):
    """
    PHASE 3: Three-Tier Fact-Checking on ALL Evidence (Non-batched version)
    For each evidence item:
    - Tier 1: Google Fact Check API
    - Tier 2: Universal Domain Trust Check
    - Tier 3: Consensus Check (10 websites)

    Returns verified evidence with trust scores
    """
    print("\nTHREE-TIER FACT-CHECKING: Verifying All Evidence...")

    all_claim_evidence = state.get('all_claim_evidence')
    if not all_claim_evidence:
        print("No evidence to verify. Skipping.")
        return {}

    verified_claims = []

    for claim_evidence in all_claim_evidence:
        claim_id = claim_evidence.claim_id if hasattr(claim_evidence, 'claim_id') else claim_evidence.get('claim_id')
        print(f"\n   {'='*70}")
        print(f"    FACT-CHECKING CLAIM #{claim_id}")
        print(f"   {'='*70}")
        
        verified_prosecutor = []
        verified_defender = []
        
        # Process prosecutor facts
        prosecutor_facts = claim_evidence.prosecutor_facts if hasattr(claim_evidence, 'prosecutor_facts') else claim_evidence.get('prosecutor_facts', [])
        
        for fact in prosecutor_facts:
            fact_obj = fact if isinstance(fact, dict) else fact
            source_url = fact_obj.get('source_url') if isinstance(fact_obj, dict) else fact_obj.source_url
            key_fact = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
            suggested_domains = fact_obj.get('suggested_trusted_domains') if isinstance(fact_obj, dict) else fact_obj.suggested_trusted_domains
            
            print(f"\n       Verifying Prosecutor Fact: {key_fact[:80]}...")
            
            # TIER 1: Google Fact Check API
            tier1_result = check_google_fact_check_tool(key_fact)
            
            if "MATCH:" in tier1_result:
                print(f"          TIER 1 VERIFIED: {tier1_result}")
                verified_prosecutor.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="prosecutor",
                    trust_score="High",
                    verification_method="Tier1-FactCheck",
                    verification_details=tier1_result,
                    supporting_urls=[]
                ))
                continue
            
            # TIER 2: Universal Domain Trust Check
            domain_trust = get_domain_trust_level(source_url)
            is_suggested = is_trusted_domain(source_url, suggested_domains)
            
            if domain_trust == "High" or is_suggested:
                tier2_details = f"Domain Trust: {domain_trust}, Matches Suggested: {is_suggested}"
                print(f"          TIER 2 VERIFIED: {tier2_details}")
                verified_prosecutor.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="prosecutor",
                    trust_score=domain_trust,
                    verification_method="Tier2-Domain",
                    verification_details=tier2_details,
                    supporting_urls=[]
                ))
                continue
            
            # TIER 3: Consensus Check (NOW USES GEMINI!)
            print(f"          Running TIER 3 Consensus Check...")
            consensus_data = consensus_search_tool(key_fact[:100])
            
            if consensus_data.get("success"):
                # Analyze consensus using Gemini API
                consensus_analysis = analyze_consensus_with_gemini(
                    key_fact,
                    consensus_data.get("results", [])
                )
                
                supports = consensus_analysis.get("supports", 0)
                contradicts = consensus_analysis.get("contradicts", 0)
                confidence = consensus_analysis.get("confidence", "Low")
                reasoning = consensus_analysis.get("reasoning", "No reasoning provided")
                
                print(f"          TIER 3 CONSENSUS: {supports} support, {contradicts} contradict")
                print(f"          Confidence: {confidence}")
                
                # Determine trust score based on consensus
                # For PROSECUTOR facts (contradicting the claim):
                # - If sources CONTRADICT the original claim = they SUPPORT the prosecutor
                # - If sources SUPPORT the original claim = they CONTRADICT the prosecutor
                
                if contradicts > supports:
                    # Majority contradicts the original claim → Supports prosecutor
                    trust_score = confidence  # Use Gemini's confidence level
                    tier3_details = f"Consensus: {contradicts}/{consensus_data['count']} sources contradict claim. {reasoning}"
                elif supports > contradicts:
                    # Majority supports the original claim → Contradicts prosecutor
                    trust_score = "Low"
                    tier3_details = f"Consensus AGAINST prosecutor: {supports}/{consensus_data['count']} sources support claim. {reasoning}"
                else:
                    # Tie or unclear
                    trust_score = "Low"
                    tier3_details = f"No clear consensus: {supports} support, {contradicts} contradict. {reasoning}"
                
                verified_prosecutor.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="prosecutor",
                    trust_score=trust_score,
                    verification_method="Tier3-Consensus",
                    verification_details=tier3_details,
                    supporting_urls=consensus_analysis.get('majority_urls', [])
                ))
            else:
                # All tiers failed - mark as Low trust
                print(f"          ALL TIERS FAILED - Marking as Low Trust")
                verified_prosecutor.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="prosecutor",
                    trust_score="Low",
                    verification_method="Unverified",
                    verification_details="Could not verify through any tier",
                    supporting_urls=[]
                ))
        
        # Process defender facts
        defender_facts = claim_evidence.defender_facts if hasattr(claim_evidence, 'defender_facts') else claim_evidence.get('defender_facts', [])
        
        for fact in defender_facts:
            fact_obj = fact if isinstance(fact, dict) else fact
            source_url = fact_obj.get('source_url') if isinstance(fact_obj, dict) else fact_obj.source_url
            key_fact = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
            suggested_domains = fact_obj.get('suggested_trusted_domains') if isinstance(fact_obj, dict) else fact_obj.suggested_trusted_domains
            
            print(f"\n       Verifying Defender Fact: {key_fact[:80]}...")
            
            # TIER 1: Google Fact Check API
            tier1_result = check_google_fact_check_tool(key_fact)
            
            if "MATCH:" in tier1_result:
                print(f"          TIER 1 VERIFIED: {tier1_result}")
                verified_defender.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="defender",
                    trust_score="High",
                    verification_method="Tier1-FactCheck",
                    verification_details=tier1_result,
                    supporting_urls=[]
                ))
                continue
            
            # TIER 2: Universal Domain Trust Check
            domain_trust = get_domain_trust_level(source_url)
            is_suggested = is_trusted_domain(source_url, suggested_domains)
            
            if domain_trust == "High" or is_suggested:
                tier2_details = f"Domain Trust: {domain_trust}, Matches Suggested: {is_suggested}"
                print(f"          TIER 2 VERIFIED: {tier2_details}")
                verified_defender.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="defender",
                    trust_score=domain_trust,
                    verification_method="Tier2-Domain",
                    verification_details=tier2_details,
                    supporting_urls=[]
                ))
                continue
            
            # TIER 3: Consensus Check (NOW USES GEMINI!)
            print(f"          Running TIER 3 Consensus Check...")
            consensus_data = consensus_search_tool(key_fact[:100])
            
            if consensus_data.get("success"):
                # Analyze consensus using Gemini API
                consensus_analysis = analyze_consensus_with_gemini(
                    key_fact,
                    consensus_data.get("results", [])
                )
                
                supports = consensus_analysis.get("supports", 0)
                contradicts = consensus_analysis.get("contradicts", 0)
                confidence = consensus_analysis.get("confidence", "Low")
                reasoning = consensus_analysis.get("reasoning", "No reasoning provided")
                
                print(f"          TIER 3 CONSENSUS: {supports} support, {contradicts} contradict")
                print(f"          Confidence: {confidence}")
                
                # Determine trust score based on consensus
                # For DEFENDER facts (supporting the claim):
                # - If sources SUPPORT the original claim = they SUPPORT the defender
                # - If sources CONTRADICT the original claim = they CONTRADICT the defender
                
                if supports > contradicts:
                    # Majority supports the original claim → Supports defender
                    trust_score = confidence  # Use Gemini's confidence level
                    tier3_details = f"Consensus: {supports}/{consensus_data['count']} sources support claim. {reasoning}"
                elif contradicts > supports:
                    # Majority contradicts the original claim → Contradicts defender
                    trust_score = "Low"
                    tier3_details = f"Consensus AGAINST defender: {contradicts}/{consensus_data['count']} sources contradict claim. {reasoning}"
                else:
                    # Tie or unclear
                    trust_score = "Low"
                    tier3_details = f"No clear consensus: {supports} support, {contradicts} contradict. {reasoning}"
                
                verified_defender.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="defender",
                    trust_score=trust_score,
                    verification_method="Tier3-Consensus",
                    verification_details=tier3_details,
                    supporting_urls=consensus_analysis.get('majority_urls', [])
                ))
            else:
                # All tiers failed - mark as Low trust
                print(f"          ALL TIERS FAILED - Marking as Low Trust")
                verified_defender.append(VerifiedEvidence(
                    source_url=source_url,
                    key_fact=key_fact,
                    side="defender",
                    trust_score="Low",
                    verification_method="Unverified",
                    verification_details="Could not verify through any tier",
                    supporting_urls=[]
                ))
        
        verified_claims.append({
            'claim_id': claim_id,
            'verified_prosecutor': verified_prosecutor,
            'verified_defender': verified_defender
        })

    print(f"\n   {'='*70}")
    print(f"    FACT-CHECKING COMPLETE")
    print(f"   {'='*70}")

    # Store verified evidence back in state
    return {'verified_evidence': verified_claims}

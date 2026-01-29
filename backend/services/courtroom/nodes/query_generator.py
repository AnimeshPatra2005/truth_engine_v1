"""
Query Generator Node - Claim Decomposition & Search Query Generation.
PHASE 1 of the Courtroom Pipeline.

Analyzes transcript and extracts:
- Core implication
- Atomic claims (max 5)
- Prosecutor queries (to find contradicting evidence)
- Defender queries (to find supporting evidence)
"""
from ..schemas import CourtroomState, DecomposedClaims, ClaimUnit
from ..utils import safe_invoke_json
from ..llm_setup import get_llm_for_task


def claim_decomposer_node(state: CourtroomState):
    """
    PHASE 1: Decompose transcript into claims + generate search queries (1 API CALL)
    
    Requirements:
    - Extract max 5 claims
    - Combine strongly related topics
    - Generate defender query with 'supporting documents' phrase
    - Generate prosecutor query with 'supporting documents' phrase
    """
    print("\nSMART DECOMPOSER: Analyzing Transcript & Generating Queries...")
    print("TARGET: 1 API call for decomposition + query generation")
    transcript = state['transcript']
    
    try:
        prompt = f"""
        Analyze the following transcript and extract verifiable claims with search queries.
        
        TRANSCRIPT: "{transcript}"

        YOUR TASKS:
        1. IMPLICATION EXTRACTION:
           - Extract the "Core Implication" (the main narrative or conclusion being claimed)
        
        2. CLAIM EXTRACTION RULES (Max 5 claims):
           - ATOMIC: ONE testable fact per claim (max 30 words each)
           - COMBINE strongly related topics that can be covered in a single search
           - SPLIT if two independent facts joined by AND
           - KEEP TOGETHER if claim contains supporting context (WHY/HOW/WHERE)
           - PRESERVE keywords: names, dates, Sanskrit terms, numbers
           
           Split Examples:
            "Supreme Court said ritual is celebratory AND ancient"
            Split into:
              - "Ritual mentioned in ancient scriptures"
              - "Supreme Court classified ritual as celebratory activity"
           
           Combine Examples:
            "Firecrackers mentioned in Skanda Purana" + "Firecrackers mentioned in Ramayana"
            Combine into:
              - "Firecrackers mentioned in ancient Hindu scriptures like Skanda Purana and Ramayana"
        
        3. PER-CLAIM CONTEXT ANALYSIS:
           For EACH claim, determine:
           
           a) topic_category - Choose from:
              ["Science/Technology", "Law/Policy", "Politics/Geopolitics", "Mythology/Religion",
               "History/Culture", "Health/Medicine", "Environment/Climate", "Economy/Business",
               "Education/Academia", "Social Issues", "Ethics/Philosophy", "Media/Entertainment",
               "News/Viral", "General"]
           
           b) prosecutor_query - Query to find CONTRADICTING evidence:
              CRITICAL REQUIREMENTS:
              - Start with the claim keywords
              - Add term: "(debunked)"
              - ALWAYS include: "(supporting evidence)"
              - Keep it short and focused
              
              Format: "[claim keywords] AND (debunked) AND (supporting evidence)"
              
              Example: "firecrackers ancient Hindu scriptures AND (debunked) AND (supporting evidence)"
           
           c) defender_query - Query to find SUPPORTING evidence:
              CRITICAL REQUIREMENTS:
              - Start with the claim keywords
              - Add term: "(verified)"
              - ALWAYS include: "(supporting evidence)"
              - Keep it short and focused
              
              Format: "[claim keywords] AND (verified) AND (supporting evidence)"
              
              Example: "firecrackers ancient Hindu scriptures AND (verified) AND (supporting evidence)"

        OUTPUT FORMAT:
        Return a JSON OBJECT with this structure:
        
        {{
          "implication": "The core narrative or conclusion",
          "claims": [
            {{
              "id": 1,
              "claim_text": "Atomic claim statement",
              "topic_category": "Category name",
              "prosecutor_query": "Query with supporting documents phrase",
              "defender_query": "Query with supporting documents phrase"
            }}
          ]
        }}
        
        EXAMPLE OUTPUT:
        {{
          "implication": "Vaccines cause autism in children",
          "claims": [
            {{
              "id": 1,
              "claim_text": "MMR vaccine is linked to autism in children",
              "topic_category": "Health/Medicine",
              "prosecutor_query": "MMR vaccine autism link AND (debunked) AND (supporting evidence)",
              "defender_query": "MMR vaccine autism link AND (verified) AND (supporting evidence)"
            }},
            {{
              "id": 2,
              "claim_text": "Andrew Wakefield's 1998 study proved vaccine-autism connection",
              "topic_category": "Health/Medicine",
              "prosecutor_query": "Wakefield 1998 vaccine autism study AND (debunked) AND (supporting evidence)",
              "defender_query": "Wakefield 1998 vaccine autism study AND (verified) AND (supporting evidence)"
            }}
          ]
        }}
        
        REMEMBER: Keep queries short (under 15 words) and ALWAYS include "(supporting evidence)"!
        """
        
        # Use LOW thinking for fast claim extraction
        data = safe_invoke_json(get_llm_for_task("decompose"), prompt, DecomposedClaims)
        
        if not data:
            raise ValueError("Decomposition returned empty data")

        decomposed_data = DecomposedClaims(**data)
        
        print(f"    Implication: {decomposed_data.implication}")
        print(f"    Claims Extracted: {len(decomposed_data.claims)}")
        
        for claim in decomposed_data.claims:
            print(f"\n      [{claim.id}] {claim.claim_text}")
            print(f"           Category: {claim.topic_category}")
            print(f"           Prosecutor: {claim.prosecutor_query}")
            print(f"           Defender: {claim.defender_query}")

        print(f"\n    DECOMPOSER COMPLETE - Total API Calls: 1")
        return {"decomposed_data": decomposed_data}

    except Exception as e:
        print(f"    Error in Decomposer: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: create basic claim structure
        fallback = DecomposedClaims(
            implication="General Verification",
            claims=[ClaimUnit(
                id=1,
                claim_text=transcript[:100],
                topic_category="General",
                prosecutor_query=f"{transcript[:50]} AND (false OR debunked) AND (supporting documents OR supporting texts)",
                defender_query=f"{transcript[:50]} AND (proven OR confirmed) AND (supporting documents OR supporting texts)"
            )]
        )
        return {"decomposed_data": fallback}

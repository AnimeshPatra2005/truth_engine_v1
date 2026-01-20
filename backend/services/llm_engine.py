import os
import re
import json
import time
import requests
import operator
from typing import Annotated, List, Optional, TypedDict, Literal
from dotenv import load_dotenv
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# LangGraph & AI
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from services.tools import search_web 

load_dotenv()

# ==============================================================================
# 1. SETUP
# ==============================================================================
MODEL_NAME = "gemini-2.5-flash"
API_CALL_DELAY = 10
MAX_RETRIES_ON_QUOTA = 3
api_call_count = 0

llm_analysis = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"), 
    temperature=0
)

llm_search = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    google_api_key=os.getenv("GEMINI_API_KEY_SEARCH"),   
    temperature=0.4
)

# ==============================================================================
# 2. ROBUST UTILS & TOOLS
# ==============================================================================

def clean_llm_json(raw_text: str) -> str:
    """
    Clean LLM-generated JSON before parsing.
    Handles common issues like markdown formatting, escaped characters, and trailing commas.
    
    Args:
        raw_text: Raw text from LLM that should contain JSON
        
    Returns:
        Cleaned JSON string ready for parsing
    """
    if not raw_text:
        return "[]"
    
    text = str(raw_text).strip()
    
    # 1. Remove markdown code blocks (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'```', '', text)
    
    # 2. Fix escaped newlines (literal \\n instead of actual newlines)
    #Gemini issue should be fixed 
    text = text.replace('\\n', ' ')
    text = text.replace('\n', ' ')
    
    # 3. Fix double-escaped quotes (\\" → ")
    text = text.replace('\\"', '"')
    
    # 4. Remove trailing commas before } or ] (invalid JSON)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # 5. Fix single quotes to double quotes (JSON requires double quotes)
    text = re.sub(r"'([^']*)':", r'"\1":', text)  # Keys
    
    # 6. Remove extra whitespace
    text = ' '.join(text.split())
    
    # 7. Extract JSON if embedded in other text
    if '{' in text and '}' in text:
        start = text.find('{')
        end = text.rfind('}') + 1
        text = text[start:end]
    elif '[' in text and ']' in text:
        start = text.find('[')
        end = text.rfind(']') + 1
        text = text[start:end]
    
    return text.strip()

def safe_invoke_json(model, prompt_text, pydantic_object, max_retries=MAX_RETRIES_ON_QUOTA):
    """Bulletproof JSON invoker with intelligent rate limiting and quota handling."""
    global api_call_count
    schema = pydantic_object.model_json_schema()
    final_prompt = f"{prompt_text}\n\nIMPORTANT: Return ONLY valid JSON matching this schema: \n{json.dumps(schema)}"
    
    for attempt in range(max_retries):
        try:
            api_call_count += 1
            print(f"   ⏳ [API Call #{api_call_count}] Waiting {API_CALL_DELAY} seconds before call...")
            time.sleep(API_CALL_DELAY)
            
            response = model.invoke(final_prompt)
            
            # Extract content from response
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, list):
                    content = ' '.join([
                        block.get('text', '') if isinstance(block, dict) 
                        else str(block) 
                        for block in content
                    ])
                elif not isinstance(content, str):
                    content = str(content)
            else:
                content = str(response)
            
            # ✅ USE CENTRALIZED JSON CLEANER
            cleaned_content = clean_llm_json(content)
            
            # Parse and validate
            try:
                parsed_dict = json.loads(cleaned_content)
                validated_obj = pydantic_object(**parsed_dict)
                print(f"   ✅ API Call #{api_call_count} successful")
                return validated_obj.model_dump()
            except json.JSONDecodeError as je:
                # Log the error with raw content for debugging
                print(f"   ❌ JSON Parse Error: {je}")
                print(f"   📄 Raw response (first 300 chars): {content[:300]}")
                print(f"   🧹 Cleaned content (first 300 chars): {cleaned_content[:300]}")
                raise  # Re-raise to trigger retry logic

        except Exception as e:
            error_str = str(e)
            
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                retry_match = re.search(r'retry in (\d+\.?\d*)s', error_str)
                if retry_match:
                    retry_delay = float(retry_match.group(1)) + 2
                else:
                    retry_delay = 60
                
                print(f"   ⚠️ QUOTA EXHAUSTED (Attempt {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    print(f"   ⏱️ Waiting {retry_delay:.1f} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"   ❌ All retries exhausted. API quota likely depleted for today.")
                    return {}
            else:
                print(f"   ⚠️ LLM/JSON ERROR: {e}")
                return {}
    
    return {}

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def check_google_fact_check_tool(query: str):
    """Tool: Queries Google Fact Check API with Error Handling."""
    try:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY_SEARCH")
        url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        params = {"query": query, "key": api_key, "languageCode": "en"}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return f"API Error: {response.status_code}"
            
        data = response.json()
        if "claims" in data and data["claims"]:
            best = data["claims"][0]
            review = best.get("claimReview", [])[0]
            return f"MATCH: {review['publisher']['name']} rates this '{review['textualRating']}' ({review['url']})"
        return "No fact check found."
    except Exception as e:
        print(f"   ⚠️ Fact Check Tool Error: {e}")
        return "Tool Unavailable"

def consensus_search_tool(claim: str):
    """Tool: Performs Majority Vote search with Network Safety."""
    # EXCLUDE unreliable sources from consensus check
    query = f'is it true that "{claim}" -site:quora.com -site:reddit.com -site:stackexchange.com -site:twitter.com -site:x.com -site:medium.com -site:linkedin.com'
    print(f"   📊 CONSENSUS CHECK: {query}")
    try:
        results = search_web(query)
        if not results: return "No results found."
        return str(results)[:5000]
    except Exception as e:
        print(f"      ⚠️ Network Error during consensus check: {e}")
        return "Search failed due to network error."

def build_prosecutor_query(claim_text: str) -> str:
    """Hardcoded prosecutor query builder - no LLM hallucination risk."""
    # Prosecutor tries to DISPROVE the claim
    keywords = "debunked OR false OR myth OR fake OR misleading OR contradiction OR disproven"
    specifics = "supporting facts OR evidence OR proof OR citation"
    query = f'"{claim_text}" AND ({keywords}) AND ({specifics})'
    return query

def build_defender_query(claim_text: str) -> str:
    """Hardcoded defender query builder - no LLM hallucination risk."""
    # Defender tries to SUPPORT the claim
    keywords = "proven OR confirmed OR verified OR true OR evidence OR citation OR proof"
    specifics = "supporting facts OR evidence OR specific details"
    query = f'"{claim_text}" AND ({keywords}) AND ({specifics})'
    return query

def generate_optimized_queries(claims: List["ClaimUnit"]) -> dict:
    """
    ONE API CALL: Generate prosecutor + defender queries for ALL claims.
    Then append specific evidence terms in Python (deterministic, not LLM-dependent).
    Returns dict: {claim_id: {"prosecutor": "...", "defender": "..."}}
    """
    claims_text = ""
    for c in claims:
        claims_text += f"\nClaim {c.id} ({c.topic_category}): {c.claim_text}"
    
    prompt = f"""
    Generate web search query keywords for fact-checking. ONE CALL for all claims.
    
    CLAIMS TO GENERATE QUERIES FOR:
    {claims_text}
    
    YOUR TASK:
    For EACH claim above, extract 5-7 KEY TERMS (keywords only, no full sentences).
    Return JSON array with:
    - claim_id
    - base_query: The extracted keywords (e.g., "Akash Deepav ritual ancestors ancient")
    
    QUERY STYLE:
    - Extract main concepts, proper nouns, specific terms from claim
    - No character limit, keep keywords focused
    - Broken English OK - web search is smart
    - NO need to add "false", "confirmed", etc - we'll add those in Python
    """
    
    data = safe_invoke_json(llm_search, prompt, OptimizedQueries)
    
    if not data:
        print("   ⚠️ Query generation failed, returning empty dict")
        return {}
    
    # Post-process: append prosecutor/defender terms in Python
    # Include diverse evidence types: textual, statistical, legal, expert, documentary, factual
    result = {}
    if "queries" in data:
        for q in data["queries"]:
            # FIXED: Use base_query instead of prosecutor_query
            base = q.get("base_query", "")
            
            # CRITICAL: Remove "not" from base query - it negates the search!
            base = base.replace(" not ", " ").replace(" NOT ", " ").strip()
            
            # Append prosecutor-specific terms (deterministic, not LLM-dependent)
            # Covers: false claims, debunked myths, contradictions, textual evidence, court rulings, statistics disproving it
            prosecutor_query = f"{base} false debunked myth contradicts textual evidence court ruling disproved statistics data study refuted"
            
            # Append defender-specific terms (deterministic, not LLM-dependent)
            # Covers: verified claims, confirmed facts, textual evidence, legal support, expert testimony, supporting studies/data
            defender_query = f"{base} confirmed verified proven true textual evidence court ruling expert testimony study data statistics supporting details facts"
            
            result[q["claim_id"]] = {
                "prosecutor": prosecutor_query,
                "defender": defender_query
            }
            
            print(f"      [Claim {q['claim_id']}]")
            print(f"         🔴 Prosecutor: {prosecutor_query}")
            print(f"         🟢 Defender:   {defender_query}")
    
    return result

def intelligent_quote_summarizer(quote: str, claim_context: str) -> str:
    """
    AI-powered quote summarization - preserves ALL specifics while condensing to one-liner.
    Uses AI to intelligently extract key facts without truncation loss.
    """
    if len(quote) <= 200:
        return quote  # If already short, return as-is
    
    try:
        summary_prompt = f"""
        Condense this quote into a SINGLE POWERFUL LINE that preserves ALL critical details.
        
        CONTEXT: {claim_context}
        
        ORIGINAL QUOTE:
        "{quote}"
        
        YOUR TASK:
        - Extract the MOST IMPORTANT fact or statement
        - Keep ALL specifics: numbers, dates, names, facts, citations
        - Make it ONE clear, punchy line (max 150 chars)
        - Preserve exact wording where possible (no paraphrasing)
        - Do NOT lose any critical information through summarization
        
        Example transformations:
        ❌ BAD: "According to..." (loses the actual content)
        ✅ GOOD: "Study shows 87% of X resulted in Y (Journal Z, 2024)"
        
        Return ONLY the one-liner, no explanation.
        """
        
        response = llm_analysis.invoke(summary_prompt)
        
        if hasattr(response, 'content'):
            content = response.content
            if isinstance(content, list):
                content = ' '.join([str(b) for b in content])
            else:
                content = str(content)
        else:
            content = str(response)
        
        content = content.strip().strip('"').strip()
        
        # If AI response is reasonable length, use it; otherwise use original truncated
        if 20 < len(content) < 300:
            print(f"      🤖 Summarized: {content}")
            return content
        else:
            # Fallback to truncation if summary fails
            return quote[:200]
    
    except Exception as e:
        print(f"      ⚠️ Summarization failed: {e}, using truncation fallback")
        return quote[:200]

# ==============================================================================
# 3. SCHEMAS - FIXED WITH base_query
# ==============================================================================

class ClaimUnit(BaseModel):
    id: int
    claim_text: str = Field(description="The specific claim statement (merged if similar)")
    topic_category: str = Field(description="Topic category for this specific claim")
    trusted_domains: List[str] = Field(description="Trusted domains specific to this claim's topic")
    prosecutor_query: str = Field(default="", description="Search query to find evidence DISPROVING this claim")
    defender_query: str = Field(default="", description="Search query to find evidence SUPPORTING this claim")

class DecomposedClaims(BaseModel):
    implication: str = Field(description="The core narrative or hidden conclusion of the text")
    claims: List[ClaimUnit] = Field(description="List of atomic, de-duplicated claims (Max 5)", max_items=5)

class RawEvidence(BaseModel):
    """Raw search result before AI filtering"""
    claim_id: int
    side: Literal["Prosecutor", "Defender"]
    source_url: str
    title: str
    snippet: str

class FilteredEvidence(BaseModel):
    """Evidence after AI filtering - only relevant to implication"""
    claim_id: int
    side: Literal["Prosecutor", "Defender"]
    source_url: str
    quote: str = Field(description="Most relevant quote from the source")
    trust_score: Literal["High", "Low"]
    relevance_score: int = Field(description="0-10 how relevant to core implication", ge=0, le=10)
    has_specifics: bool = Field(description="Does it contain quotes, facts, figures, or citations?")

class VerificationResult(BaseModel):
    claim_text: str
    method_used: Literal["FactCheckAPI", "PrimarySource", "ConsensusVote"]
    status: Literal["Verified", "Debunked", "Unclear"]
    details: str

# FIXED: Changed to base_query instead of prosecutor_query/defender_query
class QueryPair(BaseModel):
    claim_id: int
    base_query: str = Field(description="Core keywords extracted from claim")

class OptimizedQueries(BaseModel):
    queries: List[QueryPair]

class FinalVerdict(BaseModel):
    verdict: Literal["True", "False", "Debatable", "Unverified"]
    summary: str
    top_prosecutor_evidence: List[FilteredEvidence] = Field(description="Top 3 prosecutor evidences")
    top_defender_evidence: List[FilteredEvidence] = Field(description="Top 3 defender evidences")
    verifications: List[VerificationResult]

class CourtroomState(TypedDict):
    transcript: str
    decomposed_data: Optional[DecomposedClaims]
    raw_evidence: List[RawEvidence]
    filtered_evidence: List[FilteredEvidence]
    final_verdict: Optional[FinalVerdict]

# ==============================================================================
# 4. NODES
# ==============================================================================

# ==========================================
# PHASE 1: DECOMPOSER - WITH PER-CLAIM CATEGORIZATION
# ==========================================

def claim_decomposer_node(state: CourtroomState):
    print("\n🧠 SMART DECOMPOSER: Analyzing Transcript & Context...")
    transcript = state['transcript']
    
    try:
        prompt = f"""
        Analyze the following transcript. 
        TRANSCRIPT: "{transcript}"

        YOUR TASKS:
        1. IMPLICATION:
           -Extract the "Core Implication" (The main narrative or conclusion being claimed).
        2. CLAIM EXTRACTION RULES:

1. ATOMIC FOUNDATION (max 30 words each):
   - ONE testable fact per claim
   - If claim contains "AND" between independent facts → SPLIT (but remember -split only when facts are independent)
   - If claim contains supporting context (WHY/HOW/WHERE) → KEEP TOGETHER
   
2. SPLIT CRITERIA (always split these):
   - Two different topics (law + mythology) → split but preserve context
   - Two contradictory statements (X is true AND X is false) → split
   - Example WRONG: "Supreme Court said ritual is celebratory"
   - Example RIGHT:
     * Claim A: "Ritual mentioned in ancient scriptures"
     * Claim B: "Supreme Court classified the ritual as celebratory activity" (mention about the ritual, meaning keep the essence alive)
   
3. MERGE ONLY IF (max 1 merge per claim):
   - Same topic AND single testable fact
   - Example: "Akash Deepav mentioned in Karthik Mahatma AND Vedic texts" 
     = One fact (same scripture source type) → KEEP MERGED
   
4. PRESERVE KEYWORDS: Names, dates, Sanskrit terms, numbers stay intact
          
           
        
        3. PER-CLAIM CONTEXT ANALYSIS:
           For EACH claim, determine:
           - topic_category: The specific category for THIS claim from:
             ["Science/Technology", "Law/Policy", "Politics/Geopolitics", "Mythology/Religion",
              "History/Culture", "Health/Medicine", "Environment/Climate", "Economy/Business",
              "Education/Academia", "Social Issues", "Ethics/Philosophy", "Media/Entertainment",
              "News/Viral", "General"]
           
           - trusted_domains: 3-5 authoritative domains for THIS specific claim's topic.
             Examples by category:
             * Science/Technology: nature.com, science.org, arxiv.org, ieee.org, nasa.gov
             * Law/Policy (India): indiankanoon.org, supremecourtofindia.nic.in, livelaw.in, barandbench.com
             * Law/Policy (Global): justia.com, law.cornell.edu, oecd.org
             * Politics/Geopolitics: mea.gov.in, un.org, cfr.org, brookings.edu
             * Mythology/Religion: sacred-texts.com, britannica.com, jstor.org, vedicheritage.gov.in
             * History/Culture: britannica.com, jstor.org, asi.nic.in, nationalarchives.gov.in
             * Health/Medicine: who.int, cdc.gov, nih.gov, pubmed.ncbi.nlm.nih.gov, mayoclinic.org
             * Environment/Climate: ipcc.ch, noaa.gov, epa.gov, climate.nasa.gov
             * News/Viral: reuters.com, apnews.com, bbc.com, thehindu.com, altnews.in, snopes.com
             * General fallback: britannica.com, wikipedia.org (with citation check)
             
             Government sites (.gov.in, .nic.in) are always trusted for their domain.

        CONSTRAINTS:
        - Max 5 Claims total
        - Each claim MUST have its own topic_category and trusted_domains
        - DO NOT generate prosecutor_query or defender_query - these will be built programmatically
        """
        
        data = safe_invoke_json(llm_analysis, prompt, DecomposedClaims)
        
        if not data:
            raise ValueError("Decomposition returned empty data")

        decomposed_data = DecomposedClaims(**data)
        
        # Generate optimized queries for ALL claims in ONE API call
        print("\n   🔍 GENERATING OPTIMIZED QUERIES (One API Call)...")
        queries_dict = generate_optimized_queries(decomposed_data.claims)
        
        # Populate queries from generated dict
        for claim in decomposed_data.claims:
            if claim.id in queries_dict:
                claim.prosecutor_query = queries_dict[claim.id]["prosecutor"]
                claim.defender_query = queries_dict[claim.id]["defender"]
            else:
                # Fallback if generation failed for this claim
                print(f"      ⚠️ Query generation failed for claim {claim.id}, using fallback")
                claim.prosecutor_query = f"{claim.claim_text} debunked false"
                claim.defender_query = f"{claim.claim_text} verified confirmed"
        
        print(f"   🎯 Implication: {decomposed_data.implication}")
        print(f"   🔢 Claims Extracted: {len(decomposed_data.claims)}")
        
        for c in decomposed_data.claims:
            print(f"\n      [{c.id}] {c.claim_text}")
            print(f"          📂 Category: {c.topic_category}")
            print(f"          🏰 Trusted: {c.trusted_domains}")
            print(f"          🔴 Pros Query: {c.prosecutor_query}")
            print(f"          🟢 Def Query: {c.defender_query}")

        return {"decomposed_data": decomposed_data}

    except Exception as e:
        print(f"   ❌ Error in Decomposer: {e}")
        fallback = DecomposedClaims(
            implication="General Verification",
            claims=[ClaimUnit(
                id=1,
                claim_text=transcript[:100],
                topic_category="General",
                trusted_domains=["wikipedia.org", "reuters.com", "apnews.com"],
                prosecutor_query=build_prosecutor_query(transcript[:100]),
                defender_query=build_defender_query(transcript[:100])
            )]
        )
        return {"decomposed_data": fallback}

# ==========================================
# PHASE 2: INVESTIGATOR (COMPLETELY FIXED)
# ==========================================

def investigator_node(state: CourtroomState):
    print("\n🔍 INVESTIGATOR: Intelligent Evidence Collection...")
    
    decomposed = state.get('decomposed_data')
    if not decomposed:
        print("   ⚠️ No claims to investigate. Skipping.")
        return {"raw_evidence": [], "filtered_evidence": []}

    raw_evidence_list = []

    # ==========================================
    # STEP 1: Python - Fire Searches (Top 2 per side)
    # ==========================================
    
    for claim in decomposed.claims:
        print(f"\n   🔎 Processing Claim #{claim.id}: '{claim.claim_text}'")
        print(f"      📂 Category: {claim.topic_category}")
        print(f"      🏰 Trusted Domains: {claim.trusted_domains}")
        
        # Prosecutor Search (Top 2)
        print(f"      🔴 Prosecutor Search: {claim.prosecutor_query}")
        try:
            raw_pros = search_web(claim.prosecutor_query, intent="prosecutor")
            
            if raw_pros and isinstance(raw_pros, list):
                print(f"         ✅ Got {len(raw_pros)} results")
                for i, result in enumerate(raw_pros[:2], 1):  # TOP 2 ONLY
                    url = result.get('url', 'unknown')
                    title = result.get('title', 'Untitled')
                    snippet = result.get('snippet', '')
                    
                    print(f"         {i}. {title}")
                    
                    raw_evidence_list.append(RawEvidence(
                        claim_id=claim.id,
                        side="Prosecutor",
                        source_url=url,
                        title=title,
                        snippet=snippet[:1000]
                    ))
            else:
                print(f"         ❌ No results or invalid format")
                
        except Exception as e:
            print(f"      ⚠️ Prosecutor Search Failed: {e}")
            import traceback
            traceback.print_exc()

        # Defender Search (Top 2)
        print(f"      🟢 Defender Search: {claim.defender_query}")
        try:
            raw_def = search_web(claim.defender_query, intent="defender")
            
            if raw_def and isinstance(raw_def, list):
                print(f"         ✅ Got {len(raw_def)} results")
                for i, result in enumerate(raw_def[:2], 1):  # TOP 2 ONLY
                    url = result.get('url', 'unknown')
                    title = result.get('title', 'Untitled')
                    snippet = result.get('snippet', '')
                    
                    print(f"         {i}. {title}")
                    
                    raw_evidence_list.append(RawEvidence(
                        claim_id=claim.id,
                        side="Defender",
                        source_url=url,
                        title=title,
                        snippet=snippet[:1000]
                    ))
            else:
                print(f"         ❌ No results or invalid format")
                
        except Exception as e:
            print(f"      ⚠️ Defender Search Failed: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n   📦 Raw Evidence Collected: {len(raw_evidence_list)} sources")
    
    if len(raw_evidence_list) == 0:
        print("\n   ⚠️ CRITICAL: No evidence collected. Check your search_web() function!")
        print("      This could mean:")
        print("      1. search_web() is returning None or empty list")
        print("      2. Response format doesn't match expected keys (url, title, snippet)")
        print("      3. API key is invalid or quota exhausted")
        return {
            "raw_evidence": raw_evidence_list,
            "filtered_evidence": []
        }
    
    # ==========================================
    # STEP 2: AI - Filter Based on Implication (ROBUST VERSION)
    # ==========================================
    
    print("\n   🧠 AI FILTERING: Analyzing relevance to core implication...")
    
    filtered_evidence_list = []
    
    # Group evidence by claim for efficient processing
    for claim in decomposed.claims:
        claim_evidence = [e for e in raw_evidence_list if e.claim_id == claim.id]
        
        if not claim_evidence:
            print(f"      ⚠️ No raw evidence for Claim {claim.id}, skipping")
            continue
        
        # Construct evidence text for AI
        evidence_text = ""
        for i, ev in enumerate(claim_evidence):
            evidence_text += f"\n[Evidence {i+1}] ({ev.side})\n"
            evidence_text += f"URL: {ev.source_url}\n"
            evidence_text += f"Title: {ev.title}\n"
            evidence_text += f"Content: {ev.snippet}\n"
            evidence_text += "-" * 50 + "\n"
        
        prompt = f"""
You are an Intelligent Investigator analyzing evidence.

CORE IMPLICATION: "{decomposed.implication}"
SPECIFIC CLAIM: "{claim.claim_text}"
CLAIM CATEGORY: "{claim.topic_category}"
TRUSTED DOMAINS: {claim.trusted_domains}

RAW EVIDENCE:
{evidence_text}

YOUR TASK:
For EACH piece of evidence above, determine:
1. Is it relevant to the CORE IMPLICATION (not just the claim)?
2. Does it contain SPECIFICS (exact quotes, citations, facts, figures, dates, case numbers, study references)?
3. Extract the MOST RELEVANT quote (prioritize quotes with specifics).
4. Assign relevance_score (0-10) where 10 = highly relevant with specifics.
5. Determine trust_score:
   - "High" if domain matches trusted_domains list OR is a .gov/.edu/.org from reputable institution
   - "Low" otherwise

CRITICAL: You MUST return a valid JSON array, even if empty.
If NO evidence is relevant, return: []

EXAMPLE OUTPUT:
[
  {{
    "claim_id": {claim.id},
    "side": "Prosecutor",
    "source_url": "https://example.com",
    "quote": "Specific quote here",
    "trust_score": "High",
    "relevance_score": 8,
    "has_specifics": true
  }}
]

Return ONLY the JSON array, no explanation or preamble.
"""
        
        try:
            print(f"      🔍 Filtering evidence for Claim {claim.id}...")
            
            response = llm_analysis.invoke(prompt)
            
            # Extract content
            content = response.content if hasattr(response, 'content') else str(response)
            if isinstance(content, list):
                content = ' '.join([str(b) for b in content])
            
            # ✅ USE CENTRALIZED JSON CLEANER
            cleaned_content = clean_llm_json(content)
            
            # If no JSON found, default to empty array
            if not cleaned_content or cleaned_content == "[]":
                print(f"      ⚠️ No JSON array found in response for Claim {claim.id}")
                parsed_array = []
            else:
                # Parse JSON with error handling
                try:
                    parsed_array = json.loads(cleaned_content)
                except json.JSONDecodeError as je:
                    print(f"      ❌ JSON parsing failed for Claim {claim.id}: {je}")
                    print(f"      📄 Raw content (first 200 chars): {content[:200]}")
                    print(f"      🧹 Cleaned content (first 200 chars): {cleaned_content[:200]}")
                    print(f"      ⚠️ Using empty array as fallback")
                    parsed_array = []
            
            for item_data in parsed_array:
                try:
                    # Ensure all required fields exist with defaults
                    item_data.setdefault('claim_id', claim.id)
                    item_data.setdefault('side', 'Prosecutor')
                    item_data.setdefault('source_url', 'unknown')
                    item_data.setdefault('quote', '')
                    item_data.setdefault('trust_score', 'Low')
                    item_data.setdefault('relevance_score', 0)
                    item_data.setdefault('has_specifics', False)
                    
                    filtered_ev = FilteredEvidence(**item_data)
                    
                    # Double-check trust score against claim-specific trusted domains
                    if any(domain in filtered_ev.source_url for domain in claim.trusted_domains):
                        filtered_ev.trust_score = "High"
                    
                    filtered_evidence_list.append(filtered_ev)
                    
                    print(f"      ✅ Filtered: {filtered_ev.side} | Relevance: {filtered_ev.relevance_score}/10 | Specifics: {filtered_ev.has_specifics} | Trust: {filtered_ev.trust_score}")
                    
                except Exception as e:
                    print(f"      ⚠️ Failed to validate evidence item: {e}")
                    print(f"         Item data: {item_data}")
            
            if not parsed_array:
                print(f"      ℹ️ No relevant evidence found for Claim {claim.id} (empty array returned)")
            
        except Exception as e:
            print(f"      ❌ AI Filtering Failed for Claim {claim.id}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n   ✨ Filtered Evidence: {len(filtered_evidence_list)} high-quality sources")
    
    return {
        "raw_evidence": raw_evidence_list,
        "filtered_evidence": filtered_evidence_list
    }

# ==========================================
# PHASE 3: THE JUDGE - TOP 3 PER SIDE + 3-TIER VERIFICATION
# ==========================================

def judge_node(state: CourtroomState):
    print("\n⚖️ JUDGE: Supreme Verdict Process...")
    
    try:
        decomposed = state.get('decomposed_data')
        filtered_evidence = state.get('filtered_evidence', [])
        
        if not decomposed:
            raise ValueError("Missing decomposed data")

        if not filtered_evidence:
            print("   ⚠️ WARNING: No filtered evidence available.")
            return {"final_verdict": FinalVerdict(
                verdict="Unverified",
                summary="Unable to verify: No evidence passed filtering.",
                top_prosecutor_evidence=[],
                top_defender_evidence=[],
                verifications=[]
            )}

        # ==========================================
        # STEP 1: Select Top 3 PER SIDE (Prosecutor & Defender)
        # ==========================================
        
        print("\n   🏆 STEP 1: Selecting Top 3 Evidence Per Side...")
        
        # Separate evidence by side
        prosecutor_evidence = [e for e in filtered_evidence if e.side == "Prosecutor"]
        defender_evidence = [e for e in filtered_evidence if e.side == "Defender"]
        
        print(f"      📊 Prosecutor pool: {len(prosecutor_evidence)} pieces")
        print(f"      📊 Defender pool: {len(defender_evidence)} pieces")
        
        # Prepare FULL evidence summaries for AI (all evidence, not pre-filtered)
        pros_summary = ""
        for i, ev in enumerate(prosecutor_evidence):
            pros_summary += f"\n[{i+1}] Claim #{ev.claim_id} | Trust: {ev.trust_score} | Relevance: {ev.relevance_score}/10 | Specifics: {ev.has_specifics}\n"
            pros_summary += f"Quote: {ev.quote[:300]}...\n"
            pros_summary += f"URL: {ev.source_url}\n"
            pros_summary += "-" * 50 + "\n"
        
        def_summary = ""
        for i, ev in enumerate(defender_evidence):
            def_summary += f"\n[{i+1}] Claim #{ev.claim_id} | Trust: {ev.trust_score} | Relevance: {ev.relevance_score}/10 | Specifics: {ev.has_specifics}\n"
            def_summary += f"Quote: {ev.quote[:300]}...\n"
            def_summary += f"URL: {ev.source_url}\n"
            def_summary += "-" * 50 + "\n"
        
        # Select Top 3 Prosecutor Evidence - HOLISTIC ANALYSIS
        pros_selection_prompt = f"""
        You are the Supreme Judge reviewing ALL PROSECUTOR evidence (pieces that attack/debunk the implication).
        
        CORE IMPLICATION TO DEBUNK: "{decomposed.implication}"
        
        ALL PROSECUTOR EVIDENCE (anti-claim):
        {pros_summary}
        
        YOUR TASK: Analyze ALL pieces holistically and select EXACTLY 3 that are:
        1. MOST POWERFUL in debunking/contradicting the implication
        2. Have HIGHEST specifics (direct quotes, facts, figures, citations, case numbers, dates)
        3. Come from TRUSTED sources (High trust score preferred)
        4. Are UNIQUE and NON-CONFLICTING (don't pick 2 pieces saying the same thing - pick the strongest ONE)
        5. Together tell a complete story against the implication
        
        CRITICAL: Look for pieces that:
        - Cover DIFFERENT aspects of the implication (not just repetition)
        - Have direct contradictory evidence (opposite facts, different outcomes, etc.)
        - Contain verifiable specifics (names, dates, numbers, citations to studies/laws)
        - From different sources when possible (not all from one source)
        
        Return a JSON array with EXACTLY 3 evidence indices covering the most damaging, non-redundant evidence.
        Example: [1, 5, 8] means pieces 1, 5, and 8 are your top 3.
        If fewer than 3 pieces exist, return what's available.
        """
        
        try:
            response = llm_analysis.invoke(pros_selection_prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            if isinstance(content, list):
                content = ' '.join([str(b) for b in content])
            
            content = re.sub(r'```json\s*', '', content).replace('```', '').strip()
            if "[" in content and "]" in content:
                content = content[content.find("["):content.rfind("]")+1]
            
            selected_indices = json.loads(content)
            top_prosecutor = []
            for idx in selected_indices[:3]:
                if isinstance(idx, int) and 1 <= idx <= len(prosecutor_evidence):
                    top_prosecutor.append(prosecutor_evidence[idx - 1])
            
            print(f"      ✅ Selected {len(top_prosecutor)} prosecutor evidences")
            
        except Exception as e:
            print(f"      ⚠️ Prosecutor selection failed, using top by score: {e}")
            sorted_pros = sorted(prosecutor_evidence, key=lambda x: (x.has_specifics, x.relevance_score, x.trust_score=="High"), reverse=True)
            top_prosecutor = sorted_pros[:3]
        
        # Select Top 3 Defender Evidence - HOLISTIC ANALYSIS
        def_selection_prompt = f"""
        You are the Supreme Judge reviewing ALL DEFENDER evidence (pieces that support/verify the implication).
        
        CORE IMPLICATION TO SUPPORT: "{decomposed.implication}"
        
        ALL DEFENDER EVIDENCE (pro-claim):
        {def_summary}
        
        YOUR TASK: Analyze ALL pieces holistically and select EXACTLY 3 that are:
        1. MOST POWERFUL in supporting/verifying the implication
        2. Have HIGHEST specifics (direct quotes, facts, figures, citations, case numbers, dates)
        3. Come from TRUSTED sources (High trust score preferred)
        4. Are UNIQUE and NON-CONFLICTING (don't pick 2 pieces saying the same thing - pick the strongest ONE)
        5. Together tell a complete story supporting the implication
        
        CRITICAL: Look for pieces that:
        - Cover DIFFERENT aspects of the implication (not just repetition)
        - Have direct supporting evidence (confirming facts, similar outcomes, corroborating sources)
        - Contain verifiable specifics (names, dates, numbers, citations to studies/laws/events)
        - From different sources when possible (not all from one source)
        
        Return a JSON array with EXACTLY 3 evidence indices covering the most supportive, non-redundant evidence.
        Example: [2, 4, 7] means pieces 2, 4, and 7 are your top 3.
        If fewer than 3 pieces exist, return what's available.
        """
        
        try:
            response = llm_search.invoke(def_selection_prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            if isinstance(content, list):
                content = ' '.join([str(b) for b in content])
            
            content = re.sub(r'```json\s*', '', content).replace('```', '').strip()
            if "[" in content and "]" in content:
                content = content[content.find("["):content.rfind("]")+1]
            
            selected_indices = json.loads(content)
            top_defender = []
            for idx in selected_indices[:3]:
                if isinstance(idx, int) and 1 <= idx <= len(defender_evidence):
                    top_defender.append(defender_evidence[idx - 1])
            
            print(f"      ✅ Selected {len(top_defender)} defender evidences")
            
        except Exception as e:
            print(f"      ⚠️ Defender selection failed, using top by score: {e}")
            sorted_def = sorted(defender_evidence, key=lambda x: (x.has_specifics, x.relevance_score, x.trust_score=="High"), reverse=True)
            top_defender = sorted_def[:3]
        
        # ==========================================
        # STEP 2: 3-Tier Verification
        # ==========================================
        
        print("\n   🔬 STEP 2: 3-Tier Verification Process...")
        
        verifications = []
        
        for claim in decomposed.claims:
            print(f"\n   👉 Verifying Claim #{claim.id}: '{claim.claim_text}'")
            
            # TIER 1: Fact Check API
            print("      [Tier 1] Google Fact Check API...")
            fc_result = check_google_fact_check_tool(claim.claim_text)
            if "MATCH:" in fc_result:
                print(f"      ✅ Tier 1 Passed: {fc_result}")
                verifications.append(VerificationResult(
                    claim_text=claim.claim_text,
                    method_used="FactCheckAPI",
                    status="Debunked" if any(word in fc_result.lower() for word in ["false", "misleading", "incorrect"]) else "Verified",
                    details=fc_result
                ))
                continue
            print("      ❌ Tier 1: No official fact-check found")
            
            # TIER 2: Trusted Domain Check (using claim-specific trusted domains)
            print("      [Tier 2] Trusted Domain Verification...")
            claim_evidence = [e for e in top_prosecutor + top_defender if e.claim_id == claim.id]
            found_trusted = False
            
            for ev in claim_evidence:
                if ev.trust_score == "High":
                    print(f"      ✅ Tier 2 Passed: Trusted source found - {ev.source_url}")
                    
                    # Use intelligent summarizer instead of truncation
                    summary = intelligent_quote_summarizer(ev.quote, claim.claim_text)
                    
                    verifications.append(VerificationResult(
                        claim_text=claim.claim_text,
                        method_used="PrimarySource",
                        status="Verified" if ev.side == "Defender" else "Debunked",
                        details=f"Trusted source ({ev.source_url}) states: {summary}"
                    ))
                    found_trusted = True
                    break
            
            if found_trusted:
                continue
            
            print("      ❌ Tier 2: No trusted sources found")
            
            # TIER 3: Consensus Vote
            print("      [Tier 3] Consensus Analysis...")
            consensus_data = consensus_search_tool(claim.claim_text)
            
            consensus_prompt = f"""
            Analyze search results for claim: "{claim.claim_text}"
            
            Search Results: {consensus_data}
            
            Determine:
            - If results say "False", "Myth", "Misleading", "Fake", "Debunked" → status = "Debunked"
            - If results say "True", "Verified", "Confirmed", "Proven" → status = "Verified"
            - If sources disagree or inconclusive → status = "Unclear"
            
            Return JSON with claim_text, method_used="ConsensusVote", status, and details.
            """
            
            vote = safe_invoke_json(llm_search, consensus_prompt, VerificationResult)
            if not vote:
                vote = {"claim_text": claim.claim_text, "method_used": "ConsensusVote", "status": "Unclear", "details": "Consensus analysis failed"}
            
            print(f"      🗳️ Tier 3 Result: {vote.get('status')} | {vote.get('details', '')}")
            
            verifications.append(VerificationResult(**vote))
        
        # ==========================================
        # STEP 3: Final Verdict
        # ==========================================
        
        print("\n   🔨 STEP 3: Writing Final Verdict...")
        
        # Construct case file with prosecutor vs defender evidence
        case_file = f"CORE IMPLICATION: {decomposed.implication}\n\n"
        
        case_file += "PROSECUTOR EVIDENCE (Against the claim):\n"
        for i, ev in enumerate(top_prosecutor, 1):
            case_file += f"\n{i}. [PROSECUTOR] Trust: {ev.trust_score} | Relevance: {ev.relevance_score}/10 | Specifics: {ev.has_specifics}\n"
            case_file += f"   Source: {ev.source_url}\n"
            case_file += f"   Quote: {ev.quote}\n"
        
        case_file += f"\n\nDEFENDER EVIDENCE (Supporting the claim):\n"
        for i, ev in enumerate(top_defender, 1):
            case_file += f"\n{i}. [DEFENDER] Trust: {ev.trust_score} | Relevance: {ev.relevance_score}/10 | Specifics: {ev.has_specifics}\n"
            case_file += f"   Source: {ev.source_url}\n"
            case_file += f"   Quote: {ev.quote}\n"
        
        case_file += f"\n\nVERIFICATION RESULTS:\n"
        for v in verifications:
            case_file += f"- {v.claim_text}: {v.status} via {v.method_used}\n"
        
        verdict_prompt = f"""
        You are the Supreme Court Judge delivering the final verdict based on balanced evidence.
        
        {case_file}
        
        YOUR TASK:
        1. Review the prosecutor evidence (3 pieces against the claim)
        2. Review the defender evidence (3 pieces supporting the claim)
        3. Balance both sides fairly
        4. Consider all verification results
        5. Determine if the CORE IMPLICATION is True/False/Debatable/Unverified
        6. Write a professional summary with citations to specific evidence
        
        VERDICT RULES:
        - "False" if prosecutor evidence is stronger and more credible
        - "True" if defender evidence is stronger and more credible
        - "Debatable" if both sides have equally strong, credible evidence
        - "Unverified" if insufficient evidence on either side
        
        PRIORITIZATION:
        - Evidence with specific quotes, facts, figures gets highest weight
        - Evidence from trusted sources gets higher weight
        - Consider the source quality and relevance score
        """
        
        verdict_data = safe_invoke_json(llm_analysis, verdict_prompt, FinalVerdict)
        
        if not verdict_data:
            return {"final_verdict": FinalVerdict(
                verdict="Unverified",
                summary="Judge failed to generate verdict due to API error.",
                top_prosecutor_evidence=top_prosecutor,
                top_defender_evidence=top_defender,
                verifications=verifications
            )}
        
        # Ensure both evidence lists are included
        final_verdict = FinalVerdict(**verdict_data)
        final_verdict.top_prosecutor_evidence = top_prosecutor
        final_verdict.top_defender_evidence = top_defender
        
        return {"final_verdict": final_verdict}

    except Exception as e:
        print(f" ❌ Judge Error: {e}")
        return {"final_verdict": FinalVerdict(
            verdict="Unverified",
            summary=f"System Error: {e}",
            top_prosecutor_evidence=[],
            top_defender_evidence=[],
            verifications=[]
        )}

# ==============================================================================
# 5. WORKFLOW
# ==============================================================================

workflow = StateGraph(CourtroomState)

workflow.add_node("claim_decomposer", claim_decomposer_node)
workflow.add_node("investigator", investigator_node)
workflow.add_node("judge", judge_node)

workflow.add_edge(START, "claim_decomposer")
workflow.add_edge("claim_decomposer", "investigator")
workflow.add_edge("investigator", "judge")
workflow.add_edge("judge", END)

app = workflow.compile()

# ==============================================================================
# 6. WRAPPER FUNCTION FOR API USAGE
# ==============================================================================

def analyze_text(transcript: str) -> dict:
    """Wrapper function to analyze transcript and return verdict result"""
    try:
        result = app.invoke({"transcript": transcript})
        return result.get('final_verdict', {})
    except Exception as e:
        print(f"Error analyzing text: {e}")
        return {"error": str(e)}

# ==============================================================================
# 7. RUNNER
# ==============================================================================

if __name__ == "__main__":
    transcript = "Umar Khalid was innocent."
    
    print(f"🚀 ENGINE STARTING: '{transcript}'")
    print(f"⏱️ Rate Limiting: {API_CALL_DELAY}s delay")
    print(f"📊 Model: {MODEL_NAME}")
    
    try:
        start_time = time.time()
        result = app.invoke({"transcript": transcript})
        elapsed = time.time() - start_time
        
        v = result.get('final_verdict')
        
        print("\n" + "="*70)
        print("🏆 FINAL VERDICT REPORT")
        print("="*70)
        print(f"⏱️ Total runtime: {elapsed / 60:.1f} minutes")
        print(f"📊 Total API calls made: {api_call_count}")
        
        if v:
            verdict_val = v.get('verdict') if isinstance(v, dict) else v.verdict
            summary_val = v.get('summary') if isinstance(v, dict) else v.summary
            pros_evidence = v.get('top_prosecutor_evidence') if isinstance(v, dict) else v.top_prosecutor_evidence
            def_evidence = v.get('top_defender_evidence') if isinstance(v, dict) else v.top_defender_evidence
            verifications = v.get('verifications') if isinstance(v, dict) else v.verifications

            print(f"\n⚖️ JUDGEMENT: {verdict_val.upper()}")
            print(f"📝 SUMMARY:\n{summary_val}")
            
            if pros_evidence:
                print("\n🔴 TOP 3 PROSECUTOR EVIDENCE (Against):")
                for i, ev in enumerate(pros_evidence, 1):
                    ev_url = ev.get('source_url') if isinstance(ev, dict) else ev.source_url
                    ev_quote = ev.get('quote') if isinstance(ev, dict) else ev.quote
                    ev_trust = ev.get('trust_score') if isinstance(ev, dict) else ev.trust_score
                    ev_rel = ev.get('relevance_score') if isinstance(ev, dict) else ev.relevance_score
                    
                    print(f"\n   #{i} Trust: {ev_trust} | Relevance: {ev_rel}/10")
                    print(f"   📎 {ev_url}")
                    print(f"   💬 \"{ev_quote}\"")
                    print("   " + "-"*60)
            
            if def_evidence:
                print("\n🟢 TOP 3 DEFENDER EVIDENCE (Supporting):")
                for i, ev in enumerate(def_evidence, 1):
                    ev_url = ev.get('source_url') if isinstance(ev, dict) else ev.source_url
                    ev_quote = ev.get('quote') if isinstance(ev, dict) else ev.quote
                    ev_trust = ev.get('trust_score') if isinstance(ev, dict) else ev.trust_score
                    ev_rel = ev.get('relevance_score') if isinstance(ev, dict) else ev.relevance_score
                    
                    print(f"\n   #{i} Trust: {ev_trust} | Relevance: {ev_rel}/10")
                    print(f"   📎 {ev_url}")
                    print(f"   💬 \"{ev_quote}\"")
                    print("   " + "-"*60)
            
            if verifications:
                print("\n🔍 DETAILED VERIFICATION LOG:")
                for i, check in enumerate(verifications, 1):
                    c_claim = check.get('claim_text') if isinstance(check, dict) else check.claim_text
                    c_status = check.get('status') if isinstance(check, dict) else check.status
                    c_method = check.get('method_used') if isinstance(check, dict) else check.method_used
                    c_details = check.get('details') if isinstance(check, dict) else check.details
                    
                    print(f"\n   #{i} CLAIM: \"{c_claim}\"")
                    print(f"      📍 METHOD:  {c_method}")
                    print(f"      ✅ STATUS:  {c_status}")
                    print(f"      📜 PROOF:   {c_details}")
                    print("      " + "-"*60)
        else:
            print("❌ No verdict generated.")

    except Exception as e:
        print(f"\n💥 SYSTEM FAILURE: {e}")
        print(f"📊 API calls completed before failure: {api_call_count}")
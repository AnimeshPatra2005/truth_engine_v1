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
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"), 
    temperature=0
)

llm_search = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY_SEARCH"),   
    temperature=0.4
)

# ==============================================================================
# 2. ROBUST UTILS & TOOLS
# ==============================================================================

def clean_llm_json(raw_text: str, expect_array: bool = None) -> str:
    """
    Clean LLM-generated JSON before parsing.
    Handles common issues like markdown formatting, escaped characters, and trailing commas.
    
    Args:
        raw_text: Raw text from LLM that should contain JSON
        expect_array: If True, prioritize array extraction. If False, prioritize object extraction.
                     If None, auto-detect based on what's found first.
        
    Returns:
        Cleaned JSON string ready for parsing
    """
    if not raw_text:
        return "[]" if expect_array else "{}"
    
    text = str(raw_text).strip()
    
    # 0. Handle Gemini's dictionary response format: {'type': 'text', 'text': '...'}
    # This happens when response.content is a dict instead of a string
    if text.startswith("{'type':") or text.startswith('{"type":'):
        # Try to extract the actual JSON from the 'text' field
        try:
            # First, try to parse it as a Python dict representation
            import ast
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict) and 'text' in parsed:
                text = parsed['text']
        except:
            # If that fails, use regex to extract content between 'text': ' and the last '
            match = re.search(r"'text':\s*'(.*)'(?:\s*})?$", text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                # Try with double quotes
                match = re.search(r'"text":\s*"(.*)"(?:\s*})?$', text, re.DOTALL)
                if match:
                    text = match.group(1)
    
    # 1. Remove markdown code blocks (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'```', '', text)
    
    # 2. Fix escaped newlines (literal \\n instead of actual newlines)
    text = text.replace('\\n', ' ')
    text = text.replace('\n', ' ')
    
    # 3. Fix double-escaped quotes (\\\" → ")
    text = text.replace('\\"', '"')
    
    # 4. Remove trailing commas before } or ] (invalid JSON)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # 5. Remove extra whitespace
    text = ' '.join(text.split())
    
    # 6. Extract JSON based on context (array vs object)
    has_array = '[' in text and ']' in text
    has_object = '{' in text and '}' in text
    
    if expect_array is True:
        # Caller expects array - prioritize array extraction
        if has_array:
            start = text.find('[')
            end = text.rfind(']') + 1
            text = text[start:end]
        elif has_object:
            # Found object but expected array - check if multiple objects
            start = text.find('{')
            end = text.rfind('}') + 1
            text = text[start:end]
            if '}{' in text:
                # Multiple objects concatenated - wrap in array
                text = '[' + text.replace('}{', '},{') + ']'
            else:
                # Single object - wrap in array
                text = '[' + text + ']'
    
    elif expect_array is False:
        # Caller expects object - prioritize object extraction
        if has_object:
            start = text.find('{')
            end = text.rfind('}') + 1
            text = text[start:end]
            # DO NOT wrap multiple objects - let it fail so we can debug
        elif has_array:
            # Found array but expected object - extract first element
            start = text.find('[')
            end = text.rfind(']') + 1
            array_text = text[start:end]
            try:
                import json
                parsed = json.loads(array_text)
                if isinstance(parsed, list) and len(parsed) > 0:
                    text = json.dumps(parsed[0])
                else:
                    text = array_text  # Keep as-is, will fail later
            except:
                text = array_text  # Keep as-is, will fail later
    
    else:
        # Auto-detect (legacy behavior) - prioritize array
        if has_array:
            start = text.find('[')
            end = text.rfind(']') + 1
            text = text[start:end]
        elif has_object:
            start = text.find('{')
            end = text.rfind('}') + 1
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
                
                # Handle different response formats
                if isinstance(content, dict):
                    # Gemini sometimes returns {'type': 'text', 'text': '...'}
                    content = content.get('text', str(content))
                elif isinstance(content, list):
                    content = ' '.join([
                        block.get('text', '') if isinstance(block, dict) 
                        else str(block) 
                        for block in content
                    ]) 
                elif not isinstance(content, str):
                    content = str(content)
            else:
                content = str(response)
            
            #  USE CENTRALIZED JSON CLEANER (expects object for Pydantic validation)
            cleaned_content = clean_llm_json(content, expect_array=False)
            
            # Parse and validate
            try:
                parsed_dict = json.loads(cleaned_content)
                validated_obj = pydantic_object(**parsed_dict)
                print(f"    API Call #{api_call_count} successful")
                return validated_obj.model_dump()
            except json.JSONDecodeError as je:
                # Log the error with raw content for debugging
                print(f"    JSON Parse Error: {je}")
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
                
                print(f"    QUOTA EXHAUSTED (Attempt {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    print(f"    Waiting {retry_delay:.1f} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"    All retries exhausted. API quota likely depleted for today.")
                    return {}
            else:
                print(f"    LLM/JSON ERROR: {e}")
                return {}
    
    return {}

def safe_invoke_json_array(model, prompt_text, item_class, max_retries=MAX_RETRIES_ON_QUOTA):
    """
    Specialized invoker for JSON arrays.
    Returns list of validated objects.
    """
    global api_call_count
    
    # Create example schema for a single item
    example_item = item_class.model_json_schema()
    final_prompt = f"""{prompt_text}

IMPORTANT: Return ONLY a valid JSON ARRAY of objects matching this schema:
[
  {json.dumps(example_item)},
  {json.dumps(example_item)},
  ...
]

Rules:
- Top level MUST be an array: [ ... ]
- Each item must match the schema
- No markdown, no explanations
- If no items, return empty array: []
"""
    
    for attempt in range(max_retries):
        try:
            api_call_count += 1
            print(f"   ⏳ [API Call #{api_call_count}] Waiting {API_CALL_DELAY} seconds before call...")
            time.sleep(API_CALL_DELAY)
            
            response = model.invoke(final_prompt)
            
            # Extract content
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, dict):
                    content = content.get('text', str(content))
                elif isinstance(content, list):
                    content = ' '.join([
                        block.get('text', '') if isinstance(block, dict) else str(block)
                        for block in content
                    ])
                elif not isinstance(content, str):
                    content = str(content)
            else:
                content = str(response)
            
            # Clean expecting array
            cleaned_content = clean_llm_json(content, expect_array=True)
            
            try:
                parsed_array = json.loads(cleaned_content)
                
                if not isinstance(parsed_array, list):
                    print(f"    Expected array but got {type(parsed_array)}")
                    return []
                
                # Validate each item
                validated_items = []
                for i, item_data in enumerate(parsed_array):
                    try:
                        validated_obj = item_class(**item_data)
                        validated_items.append(validated_obj.model_dump())
                    except Exception as validation_err:
                        print(f"    Item {i} validation failed: {validation_err}")
                        continue
                
                print(f"    API Call #{api_call_count} successful - {len(validated_items)} items")
                return validated_items
                
            except json.JSONDecodeError as je:
                print(f"    JSON Parse Error: {je}")
                print(f"   📄 Raw response (first 300 chars): {content[:300]}")
                print(f"   🧹 Cleaned content (first 300 chars): {cleaned_content[:300]}")
                raise

        except Exception as e:
            error_str = str(e)
            
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                retry_match = re.search(r'retry in (\d+\.?\d*)s', error_str)
                retry_delay = float(retry_match.group(1)) + 2 if retry_match else 60
                
                print(f"    QUOTA EXHAUSTED (Attempt {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    print(f"    Waiting {retry_delay:.1f} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"    All retries exhausted.")
                    return []
            else:
                print(f"    Error: {e}")
                return []
    
    return []

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
        print(f"    Fact Check Tool Error: {e}")
        return "Tool Unavailable"

def consensus_search_tool(claim: str):
    """Tool: Performs Majority Vote search with Network Safety."""
    # EXCLUDE unreliable sources from consensus check
    query = f'is it true that "{claim}" -site:quora.com -site:reddit.com -site:stackexchange.com -site:twitter.com -site:x.com -site:medium.com -site:linkedin.com'
    print(f"    CONSENSUS CHECK: {query}")
    try:
        results = search_web(query)
        if not results: return "No results found."
        return str(results)[:5000]
    except Exception as e:
        print(f"       Network Error during consensus check: {e}")
        return "Search failed due to network error."

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
         BAD: "According to..." (loses the actual content)
         GOOD: "Study shows 87% of X resulted in Y (Journal Z, 2024)"
        
        Return ONLY the one-liner, no explanation.
        """
        
        response = llm_analysis.invoke(summary_prompt)
        
        if hasattr(response, 'content'):
            content = response.content
            
            # Handle different response formats
            if isinstance(content, dict):
                # Gemini sometimes returns {'type': 'text', 'text': '...'}
                content = content.get('text', str(content))
            elif isinstance(content, list):
                content = ' '.join([
                    item.get('text', str(item)) if isinstance(item, dict) else str(item)
                    for item in content
                ])
            else:
                content = str(content)
        else:
            content = str(response)
        
        content = content.strip().strip('"').strip()
        
        # If AI response is reasonable length, use it; otherwise use original truncated
        if 20 < len(content) < 300:
            print(f"       Summarized: {content}")
            return content
        else:
            # Fallback to truncation if summary fails
            return quote[:200]
    
    except Exception as e:
        print(f"       Summarization failed: {e}, using truncation fallback")
        return quote[:200]

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

def extract_domain(url: str) -> str:
    """Extract domain from URL for trust scoring."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except:
        return url

def is_trusted_domain(url: str, trusted_domains: List[str]) -> bool:
    """Check if URL is from a trusted domain."""
    domain = extract_domain(url)
    
    # Check exact matches
    if domain in trusted_domains:
        return True
    
    # Check if any trusted domain is a substring (e.g., nih.gov matches pubmed.ncbi.nlm.nih.gov)
    for trusted in trusted_domains:
        if trusted in domain or domain in trusted:
            return True
    
    # Check for government/educational domains
    if domain.endswith('.gov') or domain.endswith('.edu') or domain.endswith('.gov.in') or domain.endswith('.nic.in'):
        return True
    
    # Check for major academic/scientific publishers
    academic_indicators = ['journal', 'academic', 'science', 'research', 'university', 'institute']
    if any(indicator in domain for indicator in academic_indicators):
        return True
    
    return False

# ==============================================================================
# 3. SCHEMAS - RESTRUCTURED FOR NEW OUTPUT FORMAT
# ==============================================================================

class ClaimUnit(BaseModel):
    id: int
    claim_text: str = Field(description="The specific claim statement")
    topic_category: str = Field(description="Topic category for this claim")
    base_query: str = Field(description="5-7 keywords for web search")
    prosecutor_query: str = Field(default="", description="Search query to find evidence DISPROVING this claim")
    defender_query: str = Field(default="", description="Search query to find evidence SUPPORTING this claim")

class DecomposedClaims(BaseModel):
    implication: str = Field(description="The core narrative or hidden conclusion of the text")
    claims: List[ClaimUnit] = Field(description="List of atomic, de-duplicated claims (Max 5)", max_items=5)

class QueryPair(BaseModel):
    claim_id: int
    base_query: str = Field(description="Core keywords extracted from claim")

class OptimizedQueries(BaseModel):
    queries: List[QueryPair]

class EvidencePoint(BaseModel):
    """Single piece of evidence with checkable facts"""
    source_url: str
    key_fact: str = Field(description="Specific fact with numbers/dates/names/citations - NO vague statements")
    trust_score: Literal["High", "Low"]

class ClaimAnalysis(BaseModel):
    """Analysis for a single claim"""
    claim_id: int
    claim_text: str
    status: Literal["Verified", "Debunked", "Unclear"]
    detailed_paragraph: str = Field(description="Crystal clear explanation (150-250 words) considering both sides")
    prosecutor_evidence: List[EvidencePoint] = Field(max_items=2, description="Top 2 contradicting facts with specifics")
    defender_evidence: List[EvidencePoint] = Field(max_items=2, description="Top 2 supporting facts with specifics")

class FinalVerdict(BaseModel):
    overall_verdict: Literal["True", "False", "Partially True", "Unverified"]
    implication_connection: str = Field(description="Long detailed paragraph (200-300 words) connecting implication to claims")
    claim_analyses: List[ClaimAnalysis]

class CourtroomState(TypedDict):
    transcript: str
    decomposed_data: Optional[DecomposedClaims]
    final_verdict: Optional[FinalVerdict]

# ==============================================================================
# 4. NODES - OPTIMIZED STRUCTURE
# ==============================================================================

def claim_decomposer_node(state: CourtroomState):
    """PHASE 1: Decompose transcript into claims + generate search queries (1 API CALL)"""
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
           - SPLIT if two independent facts joined by AND
           - KEEP TOGETHER if claim contains supporting context (WHY/HOW/WHERE)
           - PRESERVE keywords: names, dates, Sanskrit terms, numbers
           
           Split Examples:
            "Supreme Court said ritual is celebratory AND ancient"
            Split into:
              - "Ritual mentioned in ancient scriptures"
              - "Supreme Court classified ritual as celebratory activity"
        
        3. PER-CLAIM CONTEXT ANALYSIS:
           For EACH claim, determine:
           
           a) topic_category - Choose from:
              ["Science/Technology", "Law/Policy", "Politics/Geopolitics", "Mythology/Religion",
               "History/Culture", "Health/Medicine", "Environment/Climate", "Economy/Business",
               "Education/Academia", "Social Issues", "Ethics/Philosophy", "Media/Entertainment",
               "News/Viral", "General"]
           
           b) trusted_domains - 3-5 authoritative sources for THIS specific topic:
              * Science/Technology: nature.com, science.org, arxiv.org, ieee.org, nasa.gov
              * Law/Policy (India): indiankanoon.org, supremecourtofindia.nic.in, livelaw.in, barandbench.com
              * Law/Policy (Global): justia.com, law.cornell.edu, oecd.org, un.org
              * Politics/Geopolitics: mea.gov.in, un.org, cfr.org, brookings.edu, bbc.com
              * Mythology/Religion: sacred-texts.com, britannica.com, jstor.org, vedicheritage.gov.in
              * History/Culture: britannica.com, jstor.org, asi.nic.in, nationalarchives.gov.in
              * Health/Medicine: who.int, cdc.gov, nih.gov, pubmed.ncbi.nlm.nih.gov, mayoclinic.org
              * Environment/Climate: ipcc.ch, noaa.gov, epa.gov, climate.nasa.gov
              * News/Viral: reuters.com, apnews.com, bbc.com, thehindu.com, altnews.in, snopes.com
              * General: britannica.com, wikipedia.org (with citation check)
              
              Government sites (.gov.in, .nic.in, .gov, .edu) are trusted for their domain.

        OUTPUT FORMAT:
        Return a JSON OBJECT with this structure:
        
        {{
          "implication": "The core narrative or conclusion",
          "claims": [
            {{
              "id": 1,
              "claim_text": "Atomic claim statement",
              "topic_category": "Category name",
              "trusted_domains": ["domain1.com", "domain2.com", "domain3.com"],
              "prosecutor_query": "",
              "defender_query": ""
            }}
          ]
        }}
        
        IMPORTANT:
        - Leave prosecutor_query and defender_query as empty strings
        - Focus on extracting claims and assigning proper categories/domains
        - Max 5 claims total
        
        EXAMPLE OUTPUT:
        {{
          "implication": "Vaccines cause autism in children",
          "claims": [
            {{
              "id": 1,
              "claim_text": "MMR vaccine is linked to autism in children",
              "topic_category": "Health/Medicine",
              "trusted_domains": ["who.int", "cdc.gov", "nih.gov", "pubmed.ncbi.nlm.nih.gov"],
              "prosecutor_query": "",
              "defender_query": ""
            }},
            {{
              "id": 2,
              "claim_text": "Andrew Wakefield's 1998 study proved vaccine-autism connection",
              "topic_category": "Health/Medicine",
              "trusted_domains": ["thelancet.com", "bmj.com", "pubmed.ncbi.nlm.nih.gov"],
              "prosecutor_query": "",
              "defender_query": ""
            }}
          ]
        }}
        """
        
        data = safe_invoke_json(llm_analysis, prompt, DecomposedClaims)
        
        if not data:
            raise ValueError("Decomposition returned empty data")

        decomposed_data = DecomposedClaims(**data)
        
        print(f"    Implication: {decomposed_data.implication}")
        print(f"    Claims Extracted: {len(decomposed_data.claims)}")
        
        # Generate search queries in Python (deterministic, no API call)
        print("\nGENERATING SEARCH QUERIES (Python - No API Call)...")
        for claim in decomposed_data.claims:
            # Extract key terms from claim (simple keyword extraction)
            claim_words = claim.claim_text.split()
            
            # Remove common stop words and keep important terms
            stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'but', 'not'}
            keywords = [w for w in claim_words if w.lower() not in stop_words][:7]
            base_query = ' '.join(keywords)
            
            # Remove negations that might flip the search
            base_query = base_query.replace(' not ', ' ').replace(' NOT ', ' ').strip()
            
            # Build prosecutor query (find contradicting evidence)
            claim.prosecutor_query = f"{base_query} false debunked myth contradicts evidence court ruling disproved statistics"
            
            # Build defender query (find supporting evidence)
            claim.defender_query = f"{base_query} confirmed verified proven true evidence court ruling expert testimony study data"
            
            print(f"\n      [{claim.id}] {claim.claim_text}")
            print(f"           Category: {claim.topic_category}")
            print(f"           Trusted: {', '.join(claim.trusted_domains[:3])}")
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
                trusted_domains=["wikipedia.org", "reuters.com", "apnews.com"],
                prosecutor_query=build_prosecutor_query(transcript[:100]),
                defender_query=build_defender_query(transcript[:100])
            )]
        )
        return {"decomposed_data": fallback}

def investigator_and_judge_node(state: CourtroomState):
    """
    PHASE 2: Search, Extract Evidence, Analyze Claims, Connect to Implication
    TARGET: ≤5 API calls per claim + 1 final API call
    """
    print("\nINVESTIGATOR + JUDGE: Evidence Collection & Analysis...")
    print(f"    TARGET: Max 5 API calls per claim + 1 final call")
    
    decomposed = state.get('decomposed_data')
    if not decomposed:
        print("No claims to investigate. Skipping.")
        return {"final_verdict": None}

    all_claim_analyses = []
    total_claim_api_calls = 0

    # ==========================================
    # Process Each Claim
    # ==========================================
    
    for claim in decomposed.claims:
        claim_start_calls = api_call_count
        print(f"\n   {'='*70}")
        print(f"    PROCESSING CLAIM #{claim.id}")
        print(f"   {'='*70}")
        print(f"   Claim: '{claim.claim_text}'")
        print(f"   Category: {claim.topic_category}")
        print(f"   Trusted Domains: {', '.join(claim.trusted_domains)}")
        
        # ==========================================
        # STEP 1: Fire Web Searches (No API calls)
        # ==========================================
        
        print(f"\n       STEP 1: Web Search (No API calls)")
        
        # Prosecutor Search
        print(f"       Prosecutor Query: {claim.prosecutor_query}")
        try:
            raw_pros_results = search_web(claim.prosecutor_query, intent="prosecutor")
            prosecutor_results = raw_pros_results[:2] if raw_pros_results and isinstance(raw_pros_results, list) else []
            print(f"          Retrieved {len(prosecutor_results)} prosecutor sources")
        except Exception as e:
            print(f"          Prosecutor search failed: {e}")
            prosecutor_results = []
        
        # Defender Search
        print(f"       Defender Query: {claim.defender_query}")
        try:
            raw_def_results = search_web(claim.defender_query, intent="defender")
            defender_results = raw_def_results[:2] if raw_def_results and isinstance(raw_def_results, list) else []
            print(f"          Retrieved {len(defender_results)} defender sources")
        except Exception as e:
            print(f"          Defender search failed: {e}")
            defender_results = []
        
        # ==========================================
        # STEP 2: Extract Prosecutor Evidence (1-2 API calls)
        # ==========================================
        
        prosecutor_facts = []
        
        if prosecutor_results:
            print(f"\n       STEP 2a: Extract Prosecutor Evidence")
            
            # Build evidence text from search results
            pros_evidence_text = ""
            for i, result in enumerate(prosecutor_results):
                pros_evidence_text += f"\n[Source {i+1}]\n"
                pros_evidence_text += f"URL: {result.get('url', 'unknown')}\n"
                pros_evidence_text += f"Title: {result.get('title', 'Untitled')}\n"
                pros_evidence_text += f"Content: {result.get('snippet', '')[:800]}\n"
                pros_evidence_text += "-" * 60 + "\n"
            
            extract_prompt = f"""
            Extract the TOP 2 most powerful CONTRADICTING facts for this claim.
            
            CLAIM TO CONTRADICT: "{claim.claim_text}"
            CLAIM CATEGORY: {claim.topic_category}
            TRUSTED DOMAINS: {', '.join(claim.trusted_domains)}
            
            PROSECUTOR SOURCES (contradicting the claim):
            {pros_evidence_text}
            
            EXTRACTION RULES:
            1. Extract EXACTLY 2 facts (or fewer if insufficient evidence)
            2. Each fact MUST contain SPECIFIC, CHECKABLE information:
               - Numbers, percentages, statistics
               - Dates, years, time periods
               - Names of people, organizations, studies
               - Citations to research, court cases, laws
               - Direct quotes from authorities
            
            3. NO vague statements like:
                "Experts disagree"
                "Studies show"
                "According to sources"
            
            4. ONLY concrete facts like:
                "CDC study of 1.2M children found no MMR-autism link (JAMA, 2015)"
                "Wakefield's 1998 paper retracted by The Lancet in 2010 for data fraud"
                "Supreme Court ruling 2018/SC/1234 banned firecrackers in Delhi NCR"
            
            5. Assign trust_score:
               - "High" if URL matches trusted domains OR is .gov/.edu/.org from reputable institution
               - "Low" otherwise
            
            Return JSON array:
            [
              {{
                "source_url": "https://...",
                "key_fact": "Specific fact with numbers/dates/names/citations",
                "trust_score": "High" | "Low"
              }}
            ]
            
            If no good evidence, return empty array: []
            """
            
            prosecutor_facts_raw = safe_invoke_json_array(llm_analysis, extract_prompt, EvidencePoint)
            
            # Double-check trust scores against claim-specific trusted domains
            for fact in prosecutor_facts_raw:
                if isinstance(fact, dict):
                    url = fact.get('source_url', '')
                    if is_trusted_domain(url, claim.trusted_domains):
                        fact['trust_score'] = "High"
                    prosecutor_facts.append(fact)
            
            print(f"          Extracted {len(prosecutor_facts)} prosecutor facts")
            for i, fact in enumerate(prosecutor_facts, 1):
                fact_text = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                fact_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                print(f"         {i}. [{fact_trust}] {fact_text[:100]}...")
        else:
            print(f"\n       STEP 2a: No prosecutor sources found, skipping extraction")
        
        # ==========================================
        # STEP 3: Extract Defender Evidence (1-2 API calls)
        # ==========================================
        
        defender_facts = []
        
        if defender_results:
            print(f"\n       STEP 2b: Extract Defender Evidence")
            
            # Build evidence text from search results
            def_evidence_text = ""
            for i, result in enumerate(defender_results):
                def_evidence_text += f"\n[Source {i+1}]\n"
                def_evidence_text += f"URL: {result.get('url', 'unknown')}\n"
                def_evidence_text += f"Title: {result.get('title', 'Untitled')}\n"
                def_evidence_text += f"Content: {result.get('snippet', '')[:800]}\n"
                def_evidence_text += "-" * 60 + "\n"
            
            extract_prompt = f"""
            Extract the TOP 2 most powerful SUPPORTING facts for this claim.
            
            CLAIM TO SUPPORT: "{claim.claim_text}"
            CLAIM CATEGORY: {claim.topic_category}
            TRUSTED DOMAINS: {', '.join(claim.trusted_domains)}
            
            DEFENDER SOURCES (supporting the claim):
            {def_evidence_text}
            
            EXTRACTION RULES:
            1. Extract EXACTLY 2 facts (or fewer if insufficient evidence)
            2. Each fact MUST contain SPECIFIC, CHECKABLE information:
               - Numbers, percentages, statistics
               - Dates, years, time periods
               - Names of people, organizations, studies
               - Citations to research, court cases, laws, scriptures
               - Direct quotes from authorities
            
            3. NO vague statements like:
                "Ancient texts mention this"
                "It's traditional"
                "Many believe"
            
            4. ONLY concrete facts like:
                "Skanda Purana (Chapter 5, Verse 12) describes 'akash deepa' ritual"
                "Archaeological evidence from 1200 BCE shows firecracker-like devices (ASI Report 2010)"
                "85% of respondents in 2019 survey practiced this tradition (Pew Research)"
            
            5. Assign trust_score:
               - "High" if URL matches trusted domains OR is .gov/.edu/.org from reputable institution
               - "Low" otherwise
            
            Return JSON array:
            [
              {{
                "source_url": "https://...",
                "key_fact": "Specific fact with numbers/dates/names/citations",
                "trust_score": "High" | "Low"
              }}
            ]
            
            If no good evidence, return empty array: []
            """
            
            defender_facts_raw = safe_invoke_json_array(llm_analysis, extract_prompt, EvidencePoint)
            
            # Double-check trust scores
            for fact in defender_facts_raw:
                if isinstance(fact, dict):
                    url = fact.get('source_url', '')
                    if is_trusted_domain(url, claim.trusted_domains):
                        fact['trust_score'] = "High"
                    defender_facts.append(fact)
            
            print(f"          Extracted {len(defender_facts)} defender facts")
            for i, fact in enumerate(defender_facts, 1):
                fact_text = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                fact_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                print(f"         {i}. [{fact_trust}] {fact_text[:100]}...")
        else:
            print(f"\n       STEP 2b: No defender sources found, skipping extraction")
        
        # ==========================================
        # STEP 4: Fact-Check with Google API (if available)
        # ==========================================
        
        print(f"\n       STEP 3: Fact-Checking")
        fact_check_result = check_google_fact_check_tool(claim.claim_text)
        if "MATCH:" in fact_check_result:
            print(f"          Google Fact Check: {fact_check_result}")
        else:
            print(f"          Google Fact Check: {fact_check_result}")
        
        # Optionally run consensus check for unclear cases
        consensus_result = ""
        if len(prosecutor_facts) == 0 and len(defender_facts) == 0:
            print(f"          Running Consensus Check (no direct evidence found)...")
            consensus_result = consensus_search_tool(claim.claim_text)
            print(f"          Consensus check complete")
        
        # ==========================================
        # STEP 5: AI Analysis & Verdict (1 API call)
        # ==========================================
        
        print(f"\n       STEP 4: Writing Detailed Analysis")
        
        # Prepare evidence summaries
        prosecutor_summary = json.dumps([
            {
                'url': (f.get('source_url') if isinstance(f, dict) else f.source_url),
                'fact': (f.get('key_fact') if isinstance(f, dict) else f.key_fact),
                'trust': (f.get('trust_score') if isinstance(f, dict) else f.trust_score)
            }
            for f in prosecutor_facts
        ], indent=2)
        
        defender_summary = json.dumps([
            {
                'url': (f.get('source_url') if isinstance(f, dict) else f.source_url),
                'fact': (f.get('key_fact') if isinstance(f, dict) else f.key_fact),
                'trust': (f.get('trust_score') if isinstance(f, dict) else f.trust_score)
            }
            for f in defender_facts
        ], indent=2)
        
        analysis_prompt = f"""
        You are a Supreme Court Judge analyzing evidence for a fact-checking verdict.
        
        CLAIM UNDER REVIEW:
        "{claim.claim_text}"
        
        CLAIM CATEGORY: {claim.topic_category}
        TRUSTED SOURCES: {', '.join(claim.trusted_domains)}
        
        PROSECUTOR EVIDENCE (Contradicting the claim):
        {prosecutor_summary}
        
        DEFENDER EVIDENCE (Supporting the claim):
        {defender_summary}
        
        FACT-CHECK RESULT:
        {fact_check_result}
        
        {"CONSENSUS ANALYSIS:" + consensus_result if consensus_result else ""}
        
        YOUR TASK:
        1. Determine the claim status: "Verified", "Debunked", or "Unclear"
        
        2. Write a DETAILED PARAGRAPH (150-250 words) that:
           - States your verdict clearly in the opening sentence
           - Explains the reasoning behind your verdict
           - References SPECIFIC evidence from both prosecutor and defender sides
           - Compares the quality and credibility of sources
           - Addresses why one side is stronger (or if balanced, why it's unclear)
           - Mentions trust scores and source credibility
           - Includes specific facts, numbers, dates, citations from the evidence
           - Makes the reasoning crystal clear so readers don't need to read individual evidence
        
        VERDICT GUIDELINES:
        - "Verified" if defender evidence is stronger, from trusted sources, with specifics
        - "Debunked" if prosecutor evidence is stronger, from trusted sources, with specifics
        - "Unclear" if:
          * Both sides have equally strong evidence
          * Evidence is insufficient or low-quality on both sides
          * Sources contradict each other with similar credibility
        
        WRITING STYLE:
        - Professional, balanced, objective
        - Reference specific evidence: "According to [Source], [specific fact]..."
        - Compare evidence: "While defenders cite [X], prosecutors counter with [Y]..."
        - Explain source credibility: "The CDC (high-trust source) contradicts..."
        
        OUTPUT FORMAT:
        Return JSON object:
        {{
          "claim_id": {claim.id},
          "claim_text": "{claim.claim_text}",
          "status": "Verified" | "Debunked" | "Unclear",
          "detailed_paragraph": "Your 150-250 word analysis here...",
          "prosecutor_evidence": {prosecutor_summary},
          "defender_evidence": {defender_summary}
        }}
        
        EXAMPLE PARAGRAPH:
        "The claim that the MMR vaccine causes autism is DEBUNKED based on overwhelming scientific evidence. The CDC's comprehensive study of 1.2 million children (JAMA, 2015) found absolutely no causal link between MMR vaccination and autism spectrum disorder. This high-trust source is corroborated by systematic reviews from the WHO and multiple peer-reviewed meta-analyses. While defenders cite Andrew Wakefield's 1998 study, this research was formally retracted by The Lancet in 2010 after investigations revealed data fraud and ethical violations. Wakefield subsequently lost his medical license. The prosecutor evidence is not only more recent but comes from the world's leading health organizations, whereas the defender's primary source has been thoroughly discredited. The scientific consensus, based on decades of research involving millions of participants, definitively contradicts this claim."
        """
        
        analysis_data = safe_invoke_json(llm_analysis, analysis_prompt, ClaimAnalysis)
        
        if analysis_data:
            # Ensure evidence lists are properly included
            if not analysis_data.get('prosecutor_evidence'):
                analysis_data['prosecutor_evidence'] = prosecutor_facts
            if not analysis_data.get('defender_evidence'):
                analysis_data['defender_evidence'] = defender_facts
            
            analysis = ClaimAnalysis(**analysis_data)
            all_claim_analyses.append(analysis)
            
            claim_end_calls = api_call_count
            claim_api_calls = claim_end_calls - claim_start_calls
            total_claim_api_calls += claim_api_calls
            
            print(f"          Analysis Complete")
            print(f"          Verdict: {analysis.status}")
            print(f"          API Calls for this claim: {claim_api_calls}")
            print(f"          Paragraph length: {len(analysis.detailed_paragraph)} chars")
        else:
            print(f"          Analysis generation failed for claim {claim.id}")
            # Create fallback analysis
            fallback_analysis = ClaimAnalysis(
                claim_id=claim.id,
                claim_text=claim.claim_text,
                status="Unclear",
                detailed_paragraph=f"Unable to reach a verdict for this claim due to insufficient evidence or analysis errors. The claim '{claim.claim_text}' requires further investigation.",
                prosecutor_evidence=prosecutor_facts[:2],
                defender_evidence=defender_facts[:2]
            )
            all_claim_analyses.append(fallback_analysis)
    
    print(f"\n   {'='*70}")
    print(f"    ALL CLAIMS PROCESSED")
    print(f"   {'='*70}")
    print(f"   Total API calls for all claims: {total_claim_api_calls}")
    print(f"   Average per claim: {total_claim_api_calls / len(decomposed.claims):.1f}")
    
    # ==========================================
    # FINAL STEP: Connect Everything to Implication (1 API call)
    # ==========================================
    
    print(f"\n    FINAL STEP: Writing Implication Connection...")
    
    # Build comprehensive summary of all claim analyses
    claims_summary = ""
    for i, analysis in enumerate(all_claim_analyses, 1):
        a_status = analysis.status if hasattr(analysis, 'status') else analysis.get('status')
        a_text = analysis.claim_text if hasattr(analysis, 'claim_text') else analysis.get('claim_text')
        a_para = analysis.detailed_paragraph if hasattr(analysis, 'detailed_paragraph') else analysis.get('detailed_paragraph')
        
        claims_summary += f"\n{'='*60}\n"
        claims_summary += f"CLAIM #{i}: {a_text}\n"
        claims_summary += f"STATUS: {a_status}\n"
        claims_summary += f"ANALYSIS:\n{a_para}\n"
    
    final_prompt = f"""
    You are the Supreme Court Chief Justice delivering the FINAL VERDICT.
    
    CORE IMPLICATION UNDER REVIEW:
    "{decomposed.implication}"
    
    INDIVIDUAL CLAIM VERDICTS:
    {claims_summary}
    
    YOUR TASK:
    1. Determine OVERALL VERDICT:
       - "True" if implication is supported by verified claims
       - "False" if implication is contradicted by debunked claims
       - "Partially True" if some claims verified, others debunked (selective facts)
       - "Unverified" if most claims are unclear or insufficient evidence
    
    2. Write a LONG DETAILED PARAGRAPH (200-300 words) that:
       - Opens with clear statement of overall verdict
       - Explains HOW the implication relates to individual claims
       - Connects the dots between verified/debunked/unclear claims
       - Addresses SELECTIVE USE OF FACTS if applicable (e.g., "While claim X is true, it doesn't support the broader implication because...")
       - Explains what the evidence collectively reveals about the implication
       - Discusses correlation vs causation where relevant
       - Provides a comprehensive, nuanced conclusion
       - References specific claims by number when explaining reasoning
    
    WRITING GUIDELINES:
    - Be balanced and objective, not prosecutorial or defensive
    - Acknowledge complexity where it exists
    - Explain why certain verified claims don't necessarily support the implication
    - Address context and how facts can be true but misleading when isolated
    - Make connections explicit: "Although Claim 1 is verified, it doesn't support the implication because..."
    
    OUTPUT FORMAT:
    Return JSON object:
    {{
      "overall_verdict": "True" | "False" | "Partially True" | "Unverified",
      "implication_connection": "Your 200-300 word comprehensive paragraph...",
      "claim_analyses": []
    }}
    
    NOTE: Leave claim_analyses as empty array [] - will be populated automatically.
    
    EXAMPLE PARAGRAPH (Partially True):
    "The overall implication that 'bursting firecrackers during Diwali is an ancient Hindu tradition with scriptural origins' receives a verdict of PARTIALLY TRUE. While Claim 1 regarding mentions in ancient scriptures is VERIFIED—the Skanda Purana does reference 'akash deepa' or sky lamps in religious contexts—this doesn't fully support the broader implication. The verified scriptural references describe oil lamps and ceremonial fires, not explosive firecrackers as we know them today. Claim 2, which asserts that firecracker bursting predates the British period, was DEBUNKED by historical evidence showing that gunpowder-based firecrackers were introduced to India during Mughal rule and popularized in the colonial era. The Supreme Court ruling (Claim 3) is VERIFIED but addresses environmental and health concerns rather than historical or religious legitimacy. This is a classic case of selective fact usage: while ancient fire-based rituals are indeed traditional, conflating them with modern firecrackers creates a misleading narrative. The implication uses one verified element (ancient fire rituals) to justify a different practice (explosive firecrackers) that lacks the claimed historical depth. The evidence suggests that while fire has always been central to Diwali, the specific practice of bursting firecrackers is a relatively recent addition to the celebration, making the core implication misleading despite containing a kernel of truth."
    """
    
    final_verdict_data = safe_invoke_json(llm_analysis, final_prompt, FinalVerdict)
    
    if final_verdict_data:
        # Ensure claim_analyses is included
        final_verdict_data['claim_analyses'] = [
            a.model_dump() if hasattr(a, 'model_dump') else a 
            for a in all_claim_analyses
        ]
        
        final_verdict = FinalVerdict(**final_verdict_data)
        
        final_api_calls = api_call_count - (1 + total_claim_api_calls)  # Subtract decomposer + claims
        
        print(f"    Final Verdict Written")
        print(f"    Overall Verdict: {final_verdict.overall_verdict}")
        print(f"    Connection paragraph: {len(final_verdict.implication_connection)} chars")
        print(f"    API calls for final verdict: {final_api_calls}")
        
        print(f"\n   {'='*70}")
        print(f"    TOTAL API CALL BREAKDOWN")
        print(f"   {'='*70}")
        print(f"   Phase 1 (Decomposer): 1 call")
        print(f"   Phase 2 (Claims): {total_claim_api_calls} calls ({total_claim_api_calls / len(decomposed.claims):.1f} avg per claim)")
        print(f"   Phase 3 (Final Verdict): {final_api_calls} call")
        print(f"   TOTAL: {api_call_count} calls")
        
        return {"final_verdict": final_verdict}
    else:
        print(f"    Final verdict generation failed")
        # Create fallback verdict
        fallback_verdict = FinalVerdict(
            overall_verdict="Unverified",
            implication_connection=f"Unable to reach a final verdict on the implication '{decomposed.implication}' due to analysis errors. The system successfully analyzed {len(all_claim_analyses)} individual claims, but could not synthesize a final conclusion.",
            claim_analyses=all_claim_analyses
        )
        return {"final_verdict": fallback_verdict}

# ==============================================================================
# 5. WORKFLOW
# ==============================================================================

workflow = StateGraph(CourtroomState)

workflow.add_node("claim_decomposer", claim_decomposer_node)
workflow.add_node("investigator_judge", investigator_and_judge_node)

workflow.add_edge(START, "claim_decomposer")
workflow.add_edge("claim_decomposer", "investigator_judge")
workflow.add_edge("investigator_judge", END)

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
# 7. PRETTY PRINTER FOR RESULTS
# ==============================================================================

def print_verdict_report(verdict_dict):
    """Pretty print the final verdict in the new format"""
    if not verdict_dict:
        print("No verdict data to display")
        return
    
    v = verdict_dict
    
    print("\n" + "="*80)
    print("FINAL VERDICT REPORT")
    print("="*80)
    
    # Overall Verdict
    overall = v.get('overall_verdict') if isinstance(v, dict) else v.overall_verdict
    print(f"\n OVERALL VERDICT: {overall.upper()}")
    print("="*80)
    
    # Implication Connection
    connection = v.get('implication_connection') if isinstance(v, dict) else v.implication_connection
    print(f"\n IMPLICATION ANALYSIS:\n")
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
                print(f"\n PROSECUTOR FACTS (Contradicting):")
                for i, fact in enumerate(a_pros, 1):
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    
                    print(f"\n   {i}. {f_key}")
                    print(f"       Source: {f_url}")
                    print(f"       Trust: {f_trust}")
            else:
                print(f"\n PROSECUTOR FACTS: No contradicting evidence found")
            
            # Defender Facts
            if a_def:
                print(f"\n DEFENDER FACTS (Supporting):")
                for i, fact in enumerate(a_def, 1):
                    f_url = fact.get('source_url') if isinstance(fact, dict) else fact.source_url
                    f_key = fact.get('key_fact') if isinstance(fact, dict) else fact.key_fact
                    f_trust = fact.get('trust_score') if isinstance(fact, dict) else fact.trust_score
                    
                    print(f"\n   {i}. {f_key}")
                    print(f"       Source: {f_url}")
                    print(f"       Trust: {f_trust}")
            else:
                print(f"\n DEFENDER FACTS: No supporting evidence found")
    
    print("\n" + "="*80)

# ==============================================================================
# 8. RUNNER
# ==============================================================================

if __name__ == "__main__":
    transcript = "Bursting firecrackers is an ancient Hindu tradition mentioned in the Skanda Purana and predates the British colonial period in India."
    
    print(f" OPTIMIZED FACT-CHECK ENGINE STARTING")
    print("="*80)
    print(f" TRANSCRIPT: '{transcript}'")
    print("="*80)
    print(f"\n API CALL TARGET:")
    print(f"   • Phase 1 (Decomposer): 1 call")
    print(f"   • Phase 2 (Per Claim): ≤5 calls each")
    print(f"   • Phase 3 (Final Verdict): 1 call")
    print(f" Rate Limiting: {API_CALL_DELAY}s delay between calls")
    print(f" Model: {MODEL_NAME}")
    
    try:
        start_time = time.time()
        result = app.invoke({"transcript": transcript})
        elapsed = time.time() - start_time
        
        print("\n" + "="*80)
        print(f" EXECUTION COMPLETE")
        print("="*80)
        print(f"Total Runtime: {elapsed / 60:.1f} minutes ({elapsed:.0f} seconds)")
        print(f"Total API Calls: {api_call_count}")
        print(f"Average Time per Call: {elapsed / api_call_count:.1f}s")
        
        # Print the formatted verdict
        verdict = result.get('final_verdict')
        if verdict:
            print_verdict_report(verdict)
        else:
            print("\nNo verdict generated")

    except Exception as e:
        print(f"\n SYSTEM FAILURE: {e}")
        print(f" API calls completed before failure: {api_call_count}")
        import traceback
        traceback.print_exc()
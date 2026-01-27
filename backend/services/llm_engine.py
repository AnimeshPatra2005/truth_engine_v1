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
import json_repair  # LLM-specific JSON repair library

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
API_CALL_DELAY = 2  # Reduced from 10s - using 2 API keys for load balancing
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
    temperature=0.2
)

# Load Balancing Helper
def get_balanced_llm():
    """
    Alternates between llm_analysis and llm_search for load balancing.
    Even API calls use llm_analysis, odd calls use llm_search.
    """
    global api_call_count
    return llm_analysis if (api_call_count % 2 == 0) else llm_search


# ==============================================================================
# 2. TRUSTED DOMAINS CATALOG
# ==============================================================================

TRUSTED_DOMAINS = {
    "government": [
        # India Government
        "gov.in", "nic.in", "indiankanoon.org", "supremecourtofindia.nic.in",
        "mea.gov.in", "pib.gov.in", "asi.nic.in", "nationalarchives.gov.in",
        "vedicheritage.gov.in",
        # International Government
        "gov", "gov.uk", "europa.eu", "un.org", "who.int", "cdc.gov",
        "nih.gov", "nasa.gov", "noaa.gov", "epa.gov", "fda.gov"
    ],
    "academic": [
        "edu", "ac.uk", "ac.in", "arxiv.org", "jstor.org", "pubmed.ncbi.nlm.nih.gov",
        "scholar.google.com", "researchgate.net", "nature.com", "science.org",
        "springer.com", "sciencedirect.com", "ieee.org", "acm.org",
        "thelancet.com", "bmj.com", "jama.jamanetwork.com"
    ],
    "legal": [
        "indiankanoon.org", "supremecourtofindia.nic.in", "livelaw.in",
        "barandbench.com", "justia.com", "law.cornell.edu", "scotusblog.com"
    ],
    "news_trusted": [
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "thehindu.com",
        "theguardian.com", "nytimes.com", "wsj.com", "ft.com", "economist.com",
        "aljazeera.com", "npr.org", "pbs.org"
    ],
    "fact_checkers": [
        "snopes.com", "factcheck.org", "politifact.com", "fullfact.org",
        "altnews.in", "boomlive.in", "thequint.com/news/webqoof",
        "africacheck.org", "factcheckni.org"
    ],
    "religious_scholarly": [
        "sacred-texts.com", "britannica.com", "oxfordreference.com",
        "encyclopedia.com", "worldcat.org"
    ],
    "international_orgs": [
        "un.org", "who.int", "worldbank.org", "imf.org", "oecd.org",
        "wto.org", "icc-cpi.int", "icj-cij.org", "unhcr.org"
    ],
    "untrusted": [
        "quora.com", "reddit.com", "x.com", "facebook.com",
        "instagram.com", "medium.com","linkedin.com"
    ]
}

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

def get_domain_trust_level(url: str) -> Literal["High", "Medium", "Low"]:
    """
    Determine trust level of a domain based on universal catalog.
    
    Returns:
        "High" - Government, academic, legal, major news, fact-checkers
        "Medium" - Other news sources, Wikipedia, established organizations
        "Low" - Social media, forums, blogs, unknown sources
    """
    domain = extract_domain(url)
    
    # Check untrusted first
    for untrusted in TRUSTED_DOMAINS["untrusted"]:
        if untrusted in domain or domain in untrusted:
            return "Low"
    
    # Check high-trust categories
    high_trust_categories = [
        "government", "academic", "legal", "fact_checkers", 
        "religious_scholarly", "international_orgs"
    ]
    
    for category in high_trust_categories:
        for trusted in TRUSTED_DOMAINS[category]:
            if trusted in domain or domain in trusted:
                return "High"
    
    # Check news sources (high trust)
    for trusted_news in TRUSTED_DOMAINS["news_trusted"]:
        if trusted_news in domain or domain in trusted_news:
            return "High"
    
    # Wikipedia gets medium trust (needs citation verification)
    if "wikipedia.org" in domain:
        return "Medium"
    
    # Default to Low for unknown sources
    return "Low"

def is_trusted_domain(url: str, suggested_domains: List[str] = None) -> bool:
    """
    Check if URL is from a trusted domain.
    
    Args:
        url: URL to check
        suggested_domains: Optional list of domain-specific trusted sources
    
    Returns:
        True if domain is trusted, False otherwise
    """
    domain = extract_domain(url)
    
    # Check against suggested domains if provided
    if suggested_domains:
        for suggested in suggested_domains:
            if suggested in domain or domain in suggested:
                return True
    
    # Check against universal trust catalog
    trust_level = get_domain_trust_level(url)
    return trust_level == "High"

# ==============================================================================
# 3. ROBUST UTILS & TOOLS
# ==============================================================================

# NOTE: Modified search_web wrapper to support variable result counts
def search_web_with_count(query: str, num_results: int = 5, intent: str = "general") -> list:
    """
    Wrapper around search_web that allows specifying number of results.
    If your tools.py search_web doesn't support max_results parameter,
    this wrapper will just call it and return the first num_results items.
    """
    try:
        # Call your existing search_web function
        results = search_web(query, intent=intent)
        
        # Return only the requested number of results
        return results[:num_results] if results else []
    except Exception as e:
        print(f"Search error: {e}")
        return []

def clean_llm_json(raw_text: str, expect_array: bool = None) -> str:
    """
    Clean LLM-generated JSON before parsing.
    Handles markdown formatting, escaped characters, and trailing commas.
    """
    if not raw_text:
        return "[]" if expect_array else "{}"
    
    text = str(raw_text).strip()
    
    # Handle Gemini's dict response format: {'type': 'text', 'text': '...'}
    if text.startswith("{'type':") or text.startswith('{"type":'):
        try:
            import ast
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict) and 'text' in parsed:
                text = parsed['text']
        except:
            match = re.search(r"'text':\s*'(.*)'(?:\s*})?$", text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                match = re.search(r'"text":\s*"(.*)"(?:\s*})?$', text, re.DOTALL)
                if match:
                    text = match.group(1)
    
    # Remove markdown code blocks
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'```', '', text)
    
    # Fix escaped characters
    text = text.replace('\\n', ' ')
    text = text.replace('\n', ' ')
    text = text.replace('\\"', '"')
    
    # Normalize mixed quotes
    text = re.sub(r"(?<![a-zA-Z])'(?![a-zA-Z])", '"', text)
    
    # Fix nested unescaped quotes
    def fix_nested_quotes(match):
        key = match.group(1)
        value = match.group(2)
        fixed_value = value.replace('"', '\\"')
        return f'"{key}": "{fixed_value}"'
    
    text = re.sub(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', fix_nested_quotes, text)
    
    # Remove trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    # Extract JSON based on expected type
    has_array = '[' in text and ']' in text
    has_object = '{' in text and '}' in text
    
    if expect_array is True:
        if has_array:
            start = text.find('[')
            end = text.rfind(']') + 1
            text = text[start:end]
        elif has_object:
            start = text.find('{')
            end = text.rfind('}') + 1
            text = text[start:end]
            if '}{' in text:
                text = '[' + text.replace('}{', '},{') + ']'
            else:
                text = '[' + text + ']'
    
    elif expect_array is False:
        if has_object:
            start = text.find('{')
            end = text.rfind('}') + 1
            text = text[start:end]
        elif has_array:
            start = text.find('[')
            end = text.rfind(']') + 1
            array_text = text[start:end]
            try:
                parsed = json.loads(array_text)
                if isinstance(parsed, list) and len(parsed) > 0:
                    text = json.dumps(parsed[0])
                else:
                    text = array_text
            except:
                text = array_text
    
    else:
        # Auto-detect
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
            print(f"   [API Call #{api_call_count}] Waiting {API_CALL_DELAY} seconds before call...")
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
            
            # Use json_repair to parse - it handles all LLM quirks automatically
            try:
                parsed_dict = json_repair.loads(content)
                
                # CRITICAL FIX: If json_repair returns a string, parse it again
                if isinstance(parsed_dict, str):
                    print(f"    json_repair returned string, attempting second parse...")
                    try:
                        parsed_dict = json.loads(parsed_dict)
                    except json.JSONDecodeError:
                        # Try json_repair again on the string
                        parsed_dict = json_repair.loads(parsed_dict)
                
                # Validate that we now have a dict/list
                if not isinstance(parsed_dict, (dict, list)):
                    print(f"    ERROR: Final result is {type(parsed_dict)} instead of dict/list")
                    print(f"    Content preview: {str(parsed_dict)[:200]}")
                    print(f"    Full LLM response:\n{content}")
                    raise ValueError(f"Could not parse to dict/list, got {type(parsed_dict)}")
                
                # Validate with Pydantic
                validated_obj = pydantic_object(**parsed_dict)
                print(f"    API Call #{api_call_count} successful")
                return validated_obj.model_dump()
            except (ValueError, TypeError, json.JSONDecodeError, Exception) as je:
                # Log the error with raw content for debugging
                print(f"    JSON Parse Error: {je}")
                print(f"    Full LLM response (first 500 chars):\n{content[:500]}")
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
                if attempt < max_retries - 1:
                    print(f"    Retrying... (Attempt {attempt + 2}/{max_retries})")
                    time.sleep(2)
                    continue
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
            print(f"   [API Call #{api_call_count}] Waiting {API_CALL_DELAY} seconds before call...")
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
            
            # Use json_repair to parse array
            try:
                parsed_array = json_repair.loads(content)
                
                # CRITICAL FIX: If json_repair returns a string, parse it again
                if isinstance(parsed_array, str):
                    print(f"    json_repair returned string, attempting second parse...")
                    try:
                        parsed_array = json.loads(parsed_array)
                    except json.JSONDecodeError:
                        # Try json_repair again on the string
                        parsed_array = json_repair.loads(parsed_array)
                
                # Validate that we now have a list
                if not isinstance(parsed_array, list):
                    print(f"    ERROR: Expected array but got {type(parsed_array)}")
                    print(f"    Content preview: {str(parsed_array)[:200]}")
                    if isinstance(parsed_array, dict):
                        # LLM returned object instead of array - wrap it
                        print(f"    Wrapping single object in array")
                        parsed_array = [parsed_array]
                    else:
                        raise ValueError(f"Could not parse to list, got {type(parsed_array)}")
                
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
                
            except (ValueError, TypeError, json.JSONDecodeError, Exception) as je:
                print(f"    JSON Parse Error: {je}")
                print(f"    Full LLM response (first 500 chars):\n{content[:500]}")
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
                if attempt < max_retries - 1:
                    print(f"    Retrying... (Attempt {attempt + 2}/{max_retries})")
                    time.sleep(2)
                    continue
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
    """
    Tool: Performs Majority Vote search with Network Safety.
    Searches 10 websites (if available) for consensus checking.
    EXCLUDES all untrusted domains to prevent contamination.
    
    Returns structured dict with results for Gemini analysis.
    """
    # Build exclusion list from TRUSTED_DOMAINS catalog
    exclusions = []
    for domain in TRUSTED_DOMAINS["untrusted"]:
        exclusions.append(f"-site:{domain}")
    
    # Additional social media and forum sites to exclude
    additional_exclusions = [
        "-site:stackexchange.com"
    ]
    
    all_exclusions = " ".join(exclusions + additional_exclusions)
    
    # Build query with claim and exclusions
    query = f'is it true that "{claim}" {all_exclusions}'
    
    print(f"    CONSENSUS CHECK: {query[:150]}...")
    print(f"    Excluding {len(exclusions) + len(additional_exclusions)} untrusted domain types")
    
    try:
        # CRITICAL: Request 10 results for proper majority voting
        results = search_web_with_count(query, num_results=10, intent="consensus")
        
        if not results:
            return {"success": False, "results": [], "count": 0}
        
        # Additional client-side filtering for safety
        filtered_results = []
        for result in results:
            url = result.get('url', '').lower()
            domain = extract_domain(url)
            
            # Double-check: Skip if domain is in untrusted list
            is_untrusted = False
            for untrusted in TRUSTED_DOMAINS["untrusted"]:
                if untrusted in domain:
                    is_untrusted = True
                    print(f"       Filtered out untrusted source: {domain}")
                    break
            
            if not is_untrusted:
                filtered_results.append(result)
        
        print(f"       Consensus search: {len(results)} retrieved, {len(filtered_results)} after filtering")
        
        # Return structured data for Gemini analysis
        return {
            "success": True,
            "results": filtered_results,
            "count": len(filtered_results)
        }
    except Exception as e:
        print(f"       Network Error during consensus check: {e}")
        return {"success": False, "results": [], "count": 0, "error": str(e)}

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
    
    OUTPUT FORMAT (JSON):
    {{
      "supports": <number>,
      "contradicts": <number>,
      "neutral": <number>,
      "confidence": "High" | "Medium" | "Low",
      "reasoning": "Brief explanation of the consensus pattern"
    }}
    
    IMPORTANT: 
    - The numbers MUST add up to {len(search_results)}
    - Be strict - only count clear support/contradiction
    - When in doubt, mark as neutral
    """
    
    class ConsensusAnalysis(BaseModel):
        supports: int = Field(description="Number of sources supporting the claim")
        contradicts: int = Field(description="Number of sources contradicting the claim")
        neutral: int = Field(description="Number of neutral/unclear sources")
        confidence: Literal["High", "Medium", "Low"] = Field(description="Confidence level based on agreement percentage")
        reasoning: str = Field(description="Brief explanation of consensus pattern")
    
    analysis = safe_invoke_json(get_balanced_llm(), prompt, ConsensusAnalysis)
    
    if not analysis:
        return {
            "supports": 0,
            "contradicts": 0,
            "neutral": len(search_results),
            "confidence": "Low",
            "reasoning": "Failed to analyze consensus"
        }
    
    return analysis

# ==============================================================================
# 4. SCHEMAS
# ==============================================================================

class ClaimUnit(BaseModel):
    id: int
    claim_text: str = Field(description="The specific claim statement")
    topic_category: str = Field(description="Topic category for this claim")
    prosecutor_query: str = Field(description="Search query to find evidence DISPROVING this claim with 'supporting documents' phrase")
    defender_query: str = Field(description="Search query to find evidence SUPPORTING this claim with 'supporting documents' phrase")

class DecomposedClaims(BaseModel):
    implication: str = Field(description="The core narrative or hidden conclusion of the text")
    claims: List[ClaimUnit] = Field(description="List of atomic, de-duplicated claims (Max 5)", max_items=5)

class Evidence(BaseModel):
    """Single piece of evidence extracted from search results"""
    source_url: str
    key_fact: str = Field(description="Specific fact with numbers/dates/names/citations - NO vague statements")
    side: Literal["prosecutor", "defender"] = Field(description="Which side this evidence supports")
    suggested_trusted_domains: List[str] = Field(
        description="3-5 domain-specific trusted sources for verification",
        max_items=5
    )

class ClaimEvidence(BaseModel):
    """Evidence collection for a single claim"""
    claim_id: int
    prosecutor_facts: List[Evidence] = Field(max_items=2, description="Top 2 contradicting facts")
    defender_facts: List[Evidence] = Field(max_items=2, description="Top 2 supporting facts")

class VerifiedEvidence(BaseModel):
    """Evidence after 3-tier fact-checking"""
    source_url: str
    key_fact: str
    side: Literal["prosecutor", "defender"]
    trust_score: Literal["High", "Medium", "Low"]
    verification_method: str = Field(description="Which tier verified this: Tier1-FactCheck / Tier2-Domain / Tier3-Consensus")
    verification_details: str = Field(description="Details of verification result")

class ClaimAnalysis(BaseModel):
    """Analysis for a single claim"""
    claim_id: int
    claim_text: str
    status: Literal["Verified", "Debunked", "Unclear"]
    detailed_paragraph: str = Field(description="Crystal clear explanation (150-250 words) considering both sides")
    prosecutor_evidence: List[VerifiedEvidence] = Field(max_items=2)
    defender_evidence: List[VerifiedEvidence] = Field(max_items=2)

class FinalVerdict(BaseModel):
    overall_verdict: Literal["True", "False", "Partially True", "Unverified"]
    implication_connection: str = Field(description="Long detailed paragraph (200-300 words) connecting implication to claims")
    claim_analyses: List[ClaimAnalysis]

class CourtroomState(TypedDict):
    transcript: str
    decomposed_data: Optional[DecomposedClaims]
    all_claim_evidence: Optional[List[ClaimEvidence]]
    verified_evidence: Optional[List[dict]]
    final_verdict: Optional[FinalVerdict]

# ==============================================================================
# 5. NODES
# ==============================================================================

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
        
        data = safe_invoke_json(get_balanced_llm(), prompt, DecomposedClaims)
        
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
        
        evidence_data = safe_invoke_json(get_balanced_llm(), extract_prompt, ClaimEvidence)
        
        if evidence_data:
            claim_evidence = ClaimEvidence(**evidence_data)
            all_claim_evidence.append(claim_evidence)
            
            extraction_api_calls += 1
            
            print(f"          Extracted {len(claim_evidence.prosecutor_facts)} prosecutor facts")
            for i, fact in enumerate(claim_evidence.prosecutor_facts, 1):
                fact_obj = fact if isinstance(fact, dict) else fact
                fact_text = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
                print(f"             {i}. {fact_text[:100]}...")
            
            print(f"          Extracted {len(claim_evidence.defender_facts)} defender facts")
            for i, fact in enumerate(claim_evidence.defender_facts, 1):
                fact_obj = fact if isinstance(fact, dict) else fact
                fact_text = fact_obj.get('key_fact') if isinstance(fact_obj, dict) else fact_obj.key_fact
                print(f"             {i}. {fact_text[:100]}...")
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
        "reasoning": "Brief explanation"
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
    """
    
    class SingleConsensusAnalysis(BaseModel):
        evidence_id: str
        supports: int
        contradicts: int
        neutral: int
        confidence: Literal["High", "Medium", "Low"]
        reasoning: str
    
    # Use llm_search for consensus analysis
    analyses = safe_invoke_json_array(llm_search, prompt, SingleConsensusAnalysis)
    
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
            "reasoning": analysis['reasoning']
        }
        for analysis in analyses
    }


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
                        verification_details=tier1_result
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
                        verification_details=tier2_details
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
                        verification_details="Consensus search failed"
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
                        verification_details=details
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

def three_tier_fact_check_node(state: CourtroomState):
    """
    PHASE 3: Three-Tier Fact-Checking on ALL Evidence
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
                    verification_details=tier1_result
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
                    verification_details=tier2_details
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
                    verification_details=tier3_details
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
                    verification_details="Could not verify through any tier"
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
                    verification_details=tier1_result
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
                    verification_details=tier2_details
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
                    verification_details=tier3_details
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
                    verification_details="Could not verify through any tier"
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

    final_verdict_data = safe_invoke_json(get_balanced_llm(), analysis_prompt, FinalVerdict)

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
# 6. WORKFLOW
# ==============================================================================
workflow = StateGraph(CourtroomState)
workflow.add_node("claim_decomposer", claim_decomposer_node)
workflow.add_node("evidence_extractor", evidence_extraction_node)
workflow.add_node("fact_checker", three_tier_fact_check_node_batched)
workflow.add_node("final_analyzer", final_analysis_node)

workflow.add_edge(START, "claim_decomposer")
workflow.add_edge("claim_decomposer", "evidence_extractor")
workflow.add_edge("evidence_extractor", "fact_checker")
workflow.add_edge("fact_checker", "final_analyzer")
workflow.add_edge("final_analyzer", END)

app = workflow.compile()

# ==============================================================================
# 7. WRAPPER FUNCTION FOR API USAGE
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
# 8. PRETTY PRINTER FOR RESULTS
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



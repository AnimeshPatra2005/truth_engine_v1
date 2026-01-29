"""
Utility functions for the Courtroom Engine.
Contains JSON parsing, API invocation helpers, and search tools.
"""
import re
import json
import time
import requests
from typing import Literal
from tenacity import retry, stop_after_attempt, wait_exponential
import json_repair
from pydantic import BaseModel, Field

from .llm_setup import (
    API_CALL_DELAY, MAX_RETRIES_ON_QUOTA,
    llm_fallback, get_llm_for_task
)
from .config import TRUSTED_DOMAINS, extract_domain

# Import search_web from tools - using relative import path
from services.tools import search_web


# ==============================================================================
# JSON CLEANING UTILITIES
# ==============================================================================

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


# ==============================================================================
# SAFE LLM INVOCATION
# ==============================================================================

# Global API call counter
api_call_count = 0

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
            
            # Log the FULL error for debugging
            print(f"    ⚠️ API ERROR: {error_str[:200]}")
            
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                print(f"    QUOTA EXHAUSTED (Attempt {attempt + 1}/{max_retries})")
                
                # FALLBACK LOGIC: Switch to llm_fallback if primary model fails
                if model != llm_fallback:
                    print(f"    🔄 SWITCHING TO FALLBACK MODEL (Gemini 1.5 Flash)...")
                    try:
                        # Recursive call with fallback model
                        # Decrease retries to avoid infinite loops
                        return safe_invoke_json(llm_fallback, prompt_text, pydantic_object, max_retries=2)
                    except Exception as fallback_error:
                        print(f"    ❌ Fallback model also failed: {fallback_error}")
                        # Fall through to normal retry logic

                retry_match = re.search(r'retry in (\d+\.?\d*)s', error_str)
                if retry_match:
                    retry_delay = float(retry_match.group(1)) + 2
                else:
                    retry_delay = 30 # Reduced from 60s
                
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


# ==============================================================================
# SEARCH TOOLS
# ==============================================================================

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


# ==============================================================================
# FACT CHECK TOOLS
# ==============================================================================

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def check_google_fact_check_tool(query: str):
    """Tool: Queries Google Fact Check API with Error Handling."""
    import os
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

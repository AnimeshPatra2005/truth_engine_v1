import os
import time
from tavily import TavilyClient
from dotenv import load_dotenv
from requests.exceptions import ConnectionError, Timeout, ReadTimeout

# 1. Load Environment Variables
load_dotenv()

# 2. Initialize Tavily Client
api_key = os.getenv("TAVILY_API_KEY")
if not api_key:
    print("WARNING: TAVILY_API_KEY not found. Search capability will be disabled.")
    tavily_client = None
else:
    tavily_client = TavilyClient(api_key=api_key)

def search_web(query: str, intent: str = "general", max_retries: int = 3) -> list:
    """
    Searches the web using Tavily and returns a LIST of results.
    Each result has: 'title', 'url', 'snippet' (for compatibility with investigator)
    
    Features:
    - Retry logic with exponential backoff (1s, 2s, 4s)
    - Increased timeout to 30 seconds
    - Rate limiting to respect 100 RPM limit (0.65s delay)
    - Graceful error handling
    """
    if not tavily_client:
        print("Search disabled (No API Key)")
        return []

    print(f"Searching Web ({intent}): {query}")

    for attempt in range(max_retries):
        try:
            response = tavily_client.search(
                query=query,
                search_depth="advanced",
                max_results=5,
                timeout=30  # Increased from default 10s to 30s
            )

            MIN_RELEVANCE_SCORE = 0.3
            clean_results = []

            for result in response.get("results", []):
                score = result.get("score", 0)

                if score < MIN_RELEVANCE_SCORE:
                    continue

                # CRITICAL: Use 'title' and 'snippet' keys for compatibility
                clean_results.append({
                    "title": result.get("title", "Untitled"),
                    "url": result.get("url", ""),
                    "snippet": result.get("content", "")[:1000],  # Keep under 1000 chars
                    "score": score,
                })

            print(f"   Found {len(clean_results)} relevant results")
            
            # Rate limiting: Tavily free tier = 100 RPM
            time.sleep(0.35)
            
            #  CRITICAL: Return a LIST, not a dict
            return clean_results

        except (ConnectionError, Timeout, ReadTimeout) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"   Search timeout, retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"    Search failed after {max_retries} attempts: {e}")
                return []  # Return empty list instead of crashing
        
        except Exception as e:
            print(f" Search Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    # Fallback if all retries exhausted
    return []


# --- TEST BLOCK ---
if __name__ == "__main__":
    print("--- Testing Search Tool ---")
    
    # Test query
    result = search_web(
        "Karna pushed Arjuna's chariot documented recorded Mahabharata", 
        intent="prosecutor"
    )
    
    # Should be a list now
    print(f"\nResult type: {type(result)}")
    print(f"Result length: {len(result)}")
    
    if result:
        print("\nFirst result:")
        for key, value in result[0].items():
            if key != "snippet":
                print(f"   {key}: {value}")
            else:
                print(f"   {key}: {value[:100]}...")
    else:
        print("\nNo results returned")
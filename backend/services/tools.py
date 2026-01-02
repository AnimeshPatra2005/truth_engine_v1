import os
from tavily import TavilyClient
from dotenv import load_dotenv

# 1. Load Environment Variables
load_dotenv()

# 2. Initialize Tavily Client
api_key = os.getenv("TAVILY_API_KEY")
if not api_key:
    print("⚠️ WARNING: TAVILY_API_KEY not found. Search capability will be disabled.")
    tavily_client = None
else:
    tavily_client = TavilyClient(api_key=api_key)

# (DELETED TRUSTED_DOMAINS list - allowing full web access)

def search_web(query: str, intent: str = "general") -> dict:
    """
    Searches the web using Tavily.
    """
    if not tavily_client:
        return {"error": "Search is disabled (No API Key)"}

    print(f"🔎 Searching Web ({intent}): {query}")

    try:
        # We use 'search_depth="advanced"' to get real content.
        # REMOVED 'include_domains' to let Agents see the whole internet.
        response = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=5
        )
        
        clean_results = []
        for result in response.get('results', []):
            clean_results.append({
                "source": result['title'],
                "url": result['url'],
                # Limit text to 500 chars to save tokens
                "content": result['content'][:4000] 
            })
            
        return {"results": clean_results}

    except Exception as e:
        print(f"❌ Search Error: {e}")
        return {"results": [], "error": str(e)}

# --- TEST BLOCK ---
if __name__ == "__main__":
    print("--- Testing Search Tool ---")
    # Test queries
    result = search_web("Is the earth flat?", intent="prosecutor")
    
    import json
    print(json.dumps(result, indent=2))
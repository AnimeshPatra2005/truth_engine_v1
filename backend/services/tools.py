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
    Searches the web using Tavily with relevance-score gating.
    """
    if not tavily_client:
        return {"error": "Search is disabled (No API Key)"}

    print(f"🔎 Searching Web ({intent}): {query}")

    try:
        response = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=5
        )

        MIN_RELEVANCE_SCORE = 0.5
        clean_results = []

        for result in response.get("results", []):
            score = result.get("score", 0)

            if score < MIN_RELEVANCE_SCORE:
                print(f"⛔ Skipping low-relevance result (score={score})")
                continue

            clean_results.append({
                "source": result.get("title"),
                "url": result.get("url"),
                "score": score,
                "content": result.get("content", "")[:4000]
            })

        return {"results": clean_results}

    except Exception as e:
        print(f"❌ Search Error: {e}")
        return {"results": [], "error": str(e)}

# --- TEST BLOCK ---
if __name__ == "__main__":
    print("--- Testing Search Tool ---")
    # Test queries
    result = search_web("Karna pushed Arjuna's chariot documented OR recorded in original Mahabharata ", intent="prosecutor")
    
    import json
    print(json.dumps(result, indent=2))
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

def search_web(query: str, intent: str = "general") -> list:
    """
    Searches the web using Tavily and returns a LIST of results.
    Each result has: 'title', 'url', 'snippet' (for compatibility with investigator)
    """
    if not tavily_client:
        print("⚠️ Search disabled (No API Key)")
        return []

    print(f"🔎 Searching Web ({intent}): {query}")

    try:
        response = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=5
        )

        MIN_RELEVANCE_SCORE = 0.0
        clean_results = []

        for result in response.get("results", []):
            score = result.get("score", 0)

            if score < MIN_RELEVANCE_SCORE:
                print(f"⛔ Skipping low-relevance result (score={score})")
                continue

            # ✅ CRITICAL: Use 'title' and 'snippet' keys for compatibility
            clean_results.append({
                "title": result.get("title", "Untitled"),
                "url": result.get("url", ""),
                "snippet": result.get("content", "")[:1000],  # Keep under 1000 chars
                "score": score,
            })

        print(f"   ✅ Found {len(clean_results)} relevant results")
        
        # ✅ CRITICAL: Return a LIST, not a dict
        return clean_results

    except Exception as e:
        print(f"❌ Search Error: {e}")
        import traceback
        traceback.print_exc()
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
    print(f"\n📊 Result type: {type(result)}")
    print(f"📊 Result length: {len(result)}")
    
    if result:
        print("\n✅ First result:")
        for key, value in result[0].items():
            if key != "snippet":
                print(f"   {key}: {value}")
            else:
                print(f"   {key}: {value[:100]}...")
    else:
        print("\n❌ No results returned")
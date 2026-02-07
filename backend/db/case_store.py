"""
Vector DB storage for analysis case files.
Enables semantic search and multi-source grounding for Expert Chat.
"""
import os
import uuid
import time
from datetime import datetime
from typing import Optional, Dict, List
import chromadb
from chromadb.config import Settings
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
if not os.getenv("GEMINI_API_KEY_SEARCH"):
    print("WARNING: GEMINI_API_KEY_SEARCH not found in environment variables")
else:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY_SEARCH"))

EMBEDDING_MODEL = "models/gemini-embedding-001"

CHROMA_DB_PATH = "./chroma_db"
MAX_CASES = 20  # Only keep the 20 most recent cases

client: Optional[chromadb.Client] = None
collection: Optional[chromadb.Collection] = None
page_collection: Optional[chromadb.Collection] = None  # For full page content


def init_collection():
    """
    Initialize ChromaDB collections on startup.
    Creates persistent storage in ./chroma_db directory.
    """
    global client, collection, page_collection
    
    os.makedirs(CHROMA_DB_PATH, exist_ok=True)
    
    client = chromadb.PersistentClient(
        path=CHROMA_DB_PATH,
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True
        )
    )
    
    # We use a dummy embedding function or None because we handle embeddings manually
    # to support different task types (RETRIEVAL_DOCUMENT vs QUESTION_ANSWERING)
    collection = client.get_or_create_collection(
        name="truth_engine_cases",
        metadata={"description": "Stored fact-check analysis cases for Expert Chat"}
    )
    
    # New collection for full page content
    page_collection = client.get_or_create_collection(
        name="truth_engine_pages",
        metadata={"description": "Full web page content for Expert Chat context"}
    )
    
    print(f" ChromaDB initialized: {collection.count()} facts, {page_collection.count()} pages stored")
    return collection


def compute_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
    """
    Compute embedding for a single string using Gemini.
    
    Args:
        text: Text to embed
        task_type: "RETRIEVAL_DOCUMENT" for storage, "QUESTION_ANSWERING" for query
        
    Returns:
        List of floats (embedding vector)
    """
    try:
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=text,
            task_type=task_type
        )
        return result["embedding"]
    except Exception as e:
        print(f"Error computing embedding: {e}")
        return []


def compute_batch_embeddings(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
    """
    Compute embeddings for a batch of strings.
    Chunks requests to respect API limits if necessary (though genai handles some batching).
    """
    if not texts:
        return []
        
    try:
        # Simple batch call
        # Note: Gemini API has limits on batch size, but for < 100 items it's usually fine
        # If texts list is huge, we might need to chunk it further.
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=texts,
            task_type=task_type
        )
        return result["embedding"]
    except Exception as e:
        print(f"Batch embedding error: {e}. Falling back to single processing.")
        # Fallback to single processing if batch fails
        embeddings = []
        for text in texts:
            embeddings.append(compute_embedding(text, task_type))
            time.sleep(0.1)  # Brief pause to avoid rate limits
        return embeddings


def save_case(verdict_data: Dict, case_id: Optional[str] = None) -> str:
    """
    Store analysis results with embeddings.
    Each fact is stored separately for fine-grained semantic retrieval.
    
    Args:
        verdict_data: The verdict dictionary with claim analyses
        case_id: Optional pre-generated case ID (if None, generates new one)
    
    Returns:
        case_id: UUID for this case
    """
    if collection is None:
        raise RuntimeError("ChromaDB not initialized. Call init_collection() first.")
    
    # Use provided case_id or generate new one
    if not case_id:
        case_id = str(uuid.uuid4())
    
    documents = []
    metadatas = []
    ids = []
    
    overall_verdict = verdict_data.get("overall_verdict", "Unknown")
    implication = verdict_data.get("implication_connection", "")
    
    for claim_idx, claim_analysis in enumerate(verdict_data.get("claim_analyses", [])):
        claim_text = claim_analysis.get("claim_text", "")
        claim_verdict = claim_analysis.get("status", "Unclear")
        
        for side in ["prosecutor", "defender"]:
            evidence_list = claim_analysis.get(f"{side}_evidence", [])
            
            for ev_idx, evidence in enumerate(evidence_list):
                fact_text = evidence.get("key_fact", "")
                source_url = evidence.get("source_url", "")
                trust_score = evidence.get("trust_score", "Low")
                supporting_urls = evidence.get("supporting_urls", [])
                
                # Format: Claim + Fact for better context in embedding
                doc_text = f"Claim: {claim_text}\nFact: {fact_text}"
                
                documents.append(doc_text)
                metadatas.append({
                    "case_id": case_id,
                    "claim_id": claim_idx,
                    "claim_text": claim_text,
                    "claim_verdict": claim_verdict,
                    "fact_text": fact_text,
                    "source_url": source_url,
                    "side": side,
                    "trust_score": trust_score,
                    "supporting_urls": ",".join(supporting_urls),
                    "overall_verdict": overall_verdict,
                    "created_at": datetime.now().isoformat()
                })
                ids.append(f"{case_id}_claim{claim_idx}_{side}_{ev_idx}")
    
    if documents:
        # Generate embeddings with "RETRIEVAL_DOCUMENT" task type
        print(f"Generating embeddings for {len(documents)} logic facts...")
        embeddings = compute_batch_embeddings(documents, task_type="RETRIEVAL_DOCUMENT")
        
        collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Saved case {case_id}: {len(documents)} facts embedded")
        
        # Cleanup old cases to maintain MAX_CASES limit
        cleanup_old_cases()
    
    return case_id


def cleanup_old_cases():
    """
    Remove oldest cases when total exceeds MAX_CASES.
    Keeps only the 20 most recent cases based on created_at timestamp.
    """
    if collection is None:
        return
    
    try:
        # Get all unique case_ids with their timestamps
        all_data = collection.get(include=["metadatas"])
        
        if not all_data["ids"]:
            return
        
        # Build case_id -> oldest_timestamp mapping
        case_timestamps = {}
        for metadata in all_data["metadatas"]:
            case_id = metadata.get("case_id")
            created_at = metadata.get("created_at", "1970-01-01T00:00:00")
            
            if case_id not in case_timestamps:
                case_timestamps[case_id] = created_at
            else:
                # Keep the earliest timestamp for each case
                if created_at < case_timestamps[case_id]:
                    case_timestamps[case_id] = created_at
        
        # Sort cases by timestamp (newest first)
        sorted_cases = sorted(case_timestamps.items(), key=lambda x: x[1], reverse=True)
        
        # If we have more than MAX_CASES, delete the oldest ones
        if len(sorted_cases) > MAX_CASES:
            cases_to_delete = [case_id for case_id, _ in sorted_cases[MAX_CASES:]]
            
            for old_case_id in cases_to_delete:
                # Delete all documents with this case_id
                collection.delete(where={"case_id": old_case_id})
                
                # Also delete from page_collection if it exists
                if page_collection is not None:
                    try:
                        page_collection.delete(where={"case_id": old_case_id})
                    except:
                        pass
            
            print(f"Cleaned up {len(cases_to_delete)} old cases. Keeping {MAX_CASES} most recent.")
    
    except Exception as e:
        print(f"Error during cleanup: {e}")


def retrieve_context(case_id: str, question: str, top_k: int = 5) -> Dict:
    """
    Semantic search for relevant facts within a specific case.
    Prioritizes High > Medium > Low trust sources.
    
    Args:
        case_id: UUID of the case to search within
        question: User's question
        top_k: Number of relevant facts to retrieve
    
    Returns:
        {
            "facts": [list of relevant facts with metadata],
            "trust_breakdown": {trust score distribution}
        }
    """
    if collection is None:
        raise RuntimeError("ChromaDB not initialized. Call init_collection() first.")
    
    # Compute embedding for the question with "QUESTION_ANSWERING" task type
    query_embedding = compute_embedding(question, task_type="QUESTION_ANSWERING")
    
    if not query_embedding:
        print("Error: Could not compute embedding for query")
        return {"facts": [], "trust_breakdown": {}}
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k * 3,
        where={"case_id": case_id}
    )
    
    if not results["ids"] or not results["ids"][0]:
        return {"facts": [], "trust_breakdown": {}}
    
    facts = []
    trust_counts = {"High": 0, "Medium": 0, "Low": 0}
    
    for idx in range(len(results["ids"][0])):
        metadata = results["metadatas"][0][idx]
        distance = results["distances"][0][idx] if "distances" in results else 0
        
        supporting_urls_str = metadata.get("supporting_urls", "")
        supporting_urls = supporting_urls_str.split(",") if supporting_urls_str else []
        
        fact_obj = {
            "fact_text": metadata.get("fact_text", ""),
            "claim_text": metadata.get("claim_text", ""),
            "claim_verdict": metadata.get("claim_verdict", ""),
            "source_url": metadata.get("source_url", ""),
            "supporting_urls": supporting_urls,
            "trust_score": metadata.get("trust_score", "Low"),
            "side": metadata.get("side", ""),
            "relevance_score": 1 - distance
        }
        
        facts.append(fact_obj)
        trust_counts[fact_obj["trust_score"]] = trust_counts.get(fact_obj["trust_score"], 0) + 1
    
    facts_sorted = sorted(
        facts,
        key=lambda x: (
            {"High": 3, "Medium": 2, "Low": 1}.get(x["trust_score"], 0),
            x["relevance_score"]
        ),
        reverse=True
    )[:top_k]
    
    return {
        "facts": facts_sorted,
        "trust_breakdown": trust_counts
    }


def save_page_content(url: str, content: str, case_id: str, title: str = "") -> bool:
    """
    Store full web page content for later retrieval by Expert Chat.
    Splits content into manageable chunks to avoid memory errors.
    
    Args:
        url: Source URL (used as unique identifier)
        content: Full page text content
        case_id: Associated case ID
        title: Page title (optional)
        
    Returns:
        bool: Success status
    """
    if page_collection is None:
        print("Warning: page_collection not initialized")
        return False
        
    if not content or len(content.strip()) < 100:
        return False  # Skip pages with minimal content
    
    try:
        # Simple chunking strategy to avoid "bad allocation" errors
        # Embedding models often have token limits (e.g. 512 tokens), 
        # and large strings cause memory spikes in ONNX runtime.
        CHUNK_SIZE = 2000
        OVERLAP = 200
        
        chunks = []
        if len(content) > CHUNK_SIZE:
            for i in range(0, len(content), CHUNK_SIZE - OVERLAP):
                chunks.append(content[i:i + CHUNK_SIZE])
        else:
            chunks = [content]
            
        documents = []
        metadatas = []
        ids = []
        
        for idx, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({
                "url": url,
                "case_id": case_id,
                "title": title,
                "chunk_index": idx,
                "total_chunks": len(chunks)
            })
            # Improve ID uniqueness
            ids.append(f"{case_id}_{hash(url) % 10**8}_{idx}")
        
        # Check uniqueness just in case (optional, but good for safety)
        # For now, relying on unique IDs should be enough or let Chroma handle duplicates (upsert behavior)
        
        # Generate embeddings for chunks
        print(f"Generating embeddings for {len(documents)} page chunks...")
        embeddings = compute_batch_embeddings(documents, task_type="RETRIEVAL_DOCUMENT")
        
        page_collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print(f"       Saved page content ({len(chunks)} chunks): {url[:50]}...")
        return True
        
    except Exception as e:
        print(f"Error saving page content: {e}")
        return False


def get_page_content(case_id: str, question: str, top_k: int = 3) -> List[Dict]:
    """
    Semantic search for relevant page content within a case.
    
    Args:
        case_id: UUID of the case 
        question: User's question for semantic matching
        top_k: Number of pages to retrieve
    
    Returns:
        List of {url, title, content, relevance_score}
    """
    if page_collection is None:
        return []
    
    try:
        # Compute embedding for the question
        query_embedding = compute_embedding(question, task_type="QUESTION_ANSWERING")
        
        if not query_embedding:
            return []
            
        results = page_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"case_id": case_id}
        )
        
        if not results["ids"] or not results["ids"][0]:
            return []
        
        pages = []
        for idx in range(len(results["ids"][0])):
            metadata = results["metadatas"][0][idx]
            document = results["documents"][0][idx]
            distance = results["distances"][0][idx] if "distances" in results else 0
            
            pages.append({
                "url": metadata.get("url", ""),
                "title": metadata.get("title", ""),
                "content": document,
                "relevance_score": 1 - distance
            })
        
        return pages
    except Exception as e:
        print(f"Error retrieving page content: {e}")
        return []

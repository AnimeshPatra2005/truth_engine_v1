"""
Vector DB storage for analysis case files.
Enables semantic search and multi-source grounding for Expert Chat.
"""
import os
import uuid
from typing import Optional, Dict, List
import chromadb
from chromadb.config import Settings

CHROMA_DB_PATH = "./chroma_db"

client: Optional[chromadb.Client] = None
collection: Optional[chromadb.Collection] = None


def init_collection():
    """
    Initialize ChromaDB collection on startup.
    Creates persistent storage in ./chroma_db directory.
    """
    global client, collection
    
    os.makedirs(CHROMA_DB_PATH, exist_ok=True)
    
    client = chromadb.PersistentClient(
        path=CHROMA_DB_PATH,
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True
        )
    )
    
    collection = client.get_or_create_collection(
        name="truth_engine_cases",
        metadata={"description": "Stored fact-check analysis cases for Expert Chat"}
    )
    
    print(f" ChromaDB initialized: {collection.count()} cases stored")
    return collection


def save_case(verdict_data: Dict) -> str:
    """
    Store analysis results with embeddings.
    Each fact is stored separately for fine-grained semantic retrieval.
    
    Returns:
        case_id: UUID for this case
    """
    if collection is None:
        raise RuntimeError("ChromaDB not initialized. Call init_collection() first.")
    
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
                    "overall_verdict": overall_verdict
                })
                ids.append(f"{case_id}_claim{claim_idx}_{side}_{ev_idx}")
    
    if documents:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Saved case {case_id}: {len(documents)} facts embedded")
    
    return case_id


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
    
    results = collection.query(
        query_texts=[question],
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

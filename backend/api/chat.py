"""
Chat API endpoint for Expert Chat feature.
Uses ChromaDB for context retrieval + Gemini 3 Flash with thinking.
Produces research-paper style citations [1], [2], [3].
"""
import os
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict

# Clear GOOGLE_API_KEY to prevent SDK auto-selection of wrong key
os.environ.pop("GOOGLE_API_KEY", None)

from db.case_store import retrieve_context, get_page_content
from langchain_google_genai import ChatGoogleGenerativeAI

router = APIRouter()


class ChatRequest(BaseModel):
    case_id: str
    question: str


class ChatResponse(BaseModel):
    answer: str
    thought_process: str
    citations: List[Dict]  # [{"number": 1, "url": "..."}, ...]
    trust_breakdown: dict


# Initialize LLM with thinking + signature
_llm = None

def get_chat_llm():
    """Lazy initialization of chat LLM."""
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            google_api_key=os.getenv("GEMINI_API_KEY_SEARCH"),
            temperature=0.3,
            thinking_level="medium",
            include_thoughts=True,
        )
    return _llm


@router.post("/chat", response_model=ChatResponse)
async def expert_chat(request: ChatRequest):
    """
    Answer follow-up questions about a specific analysis case.
    Returns research-paper style citations.
    """
    try:
        # Quick greeting detection
        simple_greetings = ['hi', 'hello', 'hey', 'hiya', 'greetings']
        if request.question.strip().lower() in simple_greetings:
            return ChatResponse(
                answer="Hello! I'm the Expert on this fact-check analysis. Feel free to ask me specific questions about the claims, evidence, or sources from the analysis above!",
                thought_process="Detected simple greeting - no context retrieval needed.",
                citations=[],
                trust_breakdown={}
            )
        
        # Step 1: Retrieve relevant facts from Vector DB
        try:
            context_data = retrieve_context(request.case_id, request.question, top_k=5)
        except Exception as db_error:
            print(f"Vector DB error: {db_error}")
            return ChatResponse(
                answer="I'm having trouble accessing the analysis database. Please try again in a moment.",
                thought_process=f"Database retrieval error: {str(db_error)}",
                citations=[],
                trust_breakdown={}
            )
        
        if not context_data["facts"]:
            return ChatResponse(
                answer="I don't have enough information from this analysis to answer that question.",
                thought_process="No relevant facts found in the stored analysis.",
                citations=[],
                trust_breakdown={}
            )
        
        # Step 2: Retrieve relevant page content (top 5)
        page_context = get_page_content(request.case_id, request.question, top_k=5)
        
        # Step 3: Build numbered source list
        sources_map = _build_sources_map(context_data["facts"], page_context)
        
        # Step 4: Build context with numbered sources
        context_text = _build_context_with_numbers(context_data["facts"], page_context, sources_map)
        
        # Step 5: Generate answer using Gemini 3 with thinking
        try:
            response = _generate_answer(request.question, context_text, sources_map)
        except Exception as gemini_error:
            error_msg = str(gemini_error)
            if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
                return ChatResponse(
                    answer="I'm experiencing high demand right now. Please wait a moment and try again.",
                    thought_process=f"Rate limit reached: {error_msg}",
                    citations=[],
                    trust_breakdown=context_data["trust_breakdown"]
                )
            raise
        
        # Step 6: Parse response and extract used citations
        thought_process, answer = _parse_response(response)
        used_citations = _extract_used_citations(answer, sources_map)
        
        # Sources returned as structured data - frontend renders as buttons
        
        return ChatResponse(
            answer=answer,
            thought_process=thought_process,
            citations=used_citations,
            trust_breakdown=context_data["trust_breakdown"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Chat error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


def _build_sources_map(facts: list, pages: list) -> Dict[int, Dict]:
    """Build a numbered map of all unique sources."""
    sources_map = {}
    seen_urls = set()
    counter = 1
    
    # Add fact sources
    for fact in facts:
        url = fact.get('source_url', '')
        if url and url not in seen_urls:
            sources_map[counter] = {
                "url": url,
                "trust_score": fact.get('trust_score', 'Low'),
                "type": "fact"
            }
            seen_urls.add(url)
            counter += 1
    
    # Add page sources
    for page in pages:
        url = page.get('url', '')
        if url and url not in seen_urls:
            sources_map[counter] = {
                "url": url,
                "trust_score": "Medium",
                "type": "page"
            }
            seen_urls.add(url)
            counter += 1
    
    return sources_map


def _build_context_with_numbers(facts: list, pages: list, sources_map: Dict[int, Dict]) -> str:
    """Build context with numbered source references."""
    
    # Create reverse lookup: url -> number
    url_to_number = {v["url"]: k for k, v in sources_map.items()}
    
    context_parts = []
    context_parts.append("=== EVIDENCE FROM ANALYSIS ===\n")
    
    # Add facts with source numbers
    for fact in facts:
        url = fact.get('source_url', '')
        source_num = url_to_number.get(url, "?")
        context_parts.append(
            f"[Source {source_num}] ({fact['trust_score']} trust)\n"
            f"Claim: {fact['claim_text']}\n"
            f"Evidence: {fact['fact_text']}\n"
        )
    
    # Add page content with source numbers (limit each to ~5000 chars)
    if pages:
        context_parts.append("\n=== ADDITIONAL SOURCE CONTENT ===\n")
        for page in pages:
            url = page.get('url', '')
            source_num = url_to_number.get(url, "?")
            content = page.get('content', '')[:5000]  # Limit per page
            context_parts.append(
                f"[Source {source_num}] Content:\n{content}\n---\n"
            )
    
    # Add source reference list
    context_parts.append("\n=== SOURCE REFERENCE LIST ===\n")
    for num, source in sources_map.items():
        context_parts.append(f"[{num}]: {source['url']}\n")
    
    return "\n".join(context_parts)


def _generate_answer(question: str, context: str, sources_map: Dict) -> dict:
    """Generate answer using LangChain Gemini with thinking."""
    
    prompt = f"""You are a knowledgeable fact-check expert having a conversation about a previous analysis. You have access to evidence and sources that were gathered during the fact-check.

{context}

USER QUESTION: {question}

HOW TO RESPOND:
1.Keep your answers short and to the point (10 sentences maximum) and do not use characters like # or *
2. Start with a DIRECT ANSWER to their question - don't dodge or be vague
3. INTERPRET the evidence - explain what it means, not just what it says
4. Acknowledge nuance and complexity where it exists (e.g., "This is complicated because...")
5. If the evidence is mixed or unclear, say so honestly
6. Use [1], [2] style citations when referencing specific sources
7. Be conversational and helpful, like an expert colleague explaining something
8. If you think the user is asking something the evidence doesn't cover well, suggest what else they might want to look into

AVOID:
- Robotic, mechanical responses that just list facts
- Dodging the question with "it depends" without elaborating
- Overly academic language when simple words work
- Pretending certainty when the evidence is actually mixed

Think through the question carefully, then give a thoughtful, direct answer."""

    llm = get_chat_llm()
    response = llm.invoke(prompt)
    return response


def _parse_response(response) -> tuple[str, str]:
    """Parse LangChain response into thought process and answer."""
    content = response.content
    
    thought_process = ""
    answer = ""
    
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get('type') == 'thinking':
                    thought_process = part.get('thinking', '')[:500]
                elif part.get('type') == 'text':
                    answer = part.get('text', '')
            elif isinstance(part, str):
                answer = part
    elif isinstance(content, str):
        answer = content
        thought_process = "Processed query and generated response."
    
    if not answer:
        answer = str(content)
    
    if not thought_process:
        thought_process = "Analyzed context and formulated response."
    
    return thought_process, answer


def _extract_used_citations(answer: str, sources_map: Dict) -> List[Dict]:
    """Extract only the citation numbers actually used in the answer."""
    used = []
    seen_nums = set()
    
    # Find all numbers inside brackets - handles both [1] and [1, 2, 3] formats
    # First find all bracketed content
    bracket_pattern = r'\[([^\]]+)\]'
    brackets = re.findall(bracket_pattern, answer)
    
    for content in brackets:
        # Extract all numbers from each bracket
        numbers = re.findall(r'\d+', content)
        for num_str in numbers:
            num = int(num_str)
            if num in sources_map and num not in seen_nums:
                used.append({
                    "number": num,
                    "url": sources_map[num]["url"],
                    "trust_score": sources_map[num]["trust_score"]
                })
                seen_nums.add(num)
    
    # Sort by number
    used.sort(key=lambda x: x["number"])
    return used

# Citations are now rendered as buttons in the frontend (ExpertChat.jsx)
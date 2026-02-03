"""
Chat API endpoint for Expert Chat feature.
Handles follow-up questions about analyzed cases using Vector DB context.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from db.case_store import retrieve_context
from services.llm_engine import get_llm_for_task

router = APIRouter()


class ChatRequest(BaseModel):
    case_id: str
    question: str


class ChatResponse(BaseModel):
    answer: str
    thought_process: str  # Gemini's step-by-step reasoning
    sources: list
    trust_breakdown: dict


@router.post("/chat", response_model=ChatResponse)
async def expert_chat(request: ChatRequest):
    """
    Answer follow-up questions about a specific analysis case.
    Uses Vector DB for context retrieval and Gemini 2.0 with Google Search grounding.
    """
    try:
        # Step 1: Retrieve relevant context from Vector DB
        context_data = retrieve_context(request.case_id, request.question, top_k=5)
        
        if not context_data["facts"]:
            return ChatResponse(
                answer="I don't have enough information from this analysis to answer that question.",
                thought_process="No relevant facts found in the stored analysis.",
                sources=[],
                trust_breakdown={}
            )
        
        # Step 2: Build context for Gemini
        context_text = _build_context_prompt(context_data["facts"])
        
        # Step 3: Generate answer using Gemini with thinking + grounding
        full_response = _generate_answer(request.question, context_text, context_data["facts"])
        
        # Step 4: Parse thought process from answer
        thought_process, answer = _parse_thinking_response(full_response)
        
        # Step 5: Extract sources
        sources = _extract_sources(context_data["facts"])
        
        return ChatResponse(
            answer=answer,
            thought_process=thought_process,
            sources=sources,
            trust_breakdown=context_data["trust_breakdown"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


def _build_context_prompt(facts: list) -> str:
    """Build context from retrieved facts"""
    context_parts = []
    
    for idx, fact in enumerate(facts, 1):
        context_parts.append(
            f"[Fact {idx}] ({fact['trust_score']} trust)\n"
            f"Claim: {fact['claim_text']}\n"
            f"Evidence: {fact['fact_text']}\n"
            f"Source: {fact['source_url']}\n"
        )
    
    return "\n".join(context_parts)


def _generate_answer(question: str, context: str, facts: list) -> str:
    """
    Generate answer using Gemini 3 Flash with Google Search grounding.
    Returns answer with thought process (thought signatures).
    """
    import google.generativeai as genai
    import os
    
    # Collect all unique supporting URLs from high-trust sources
    grounding_urls = set()
    for fact in facts:
        if fact['trust_score'] in ["High", "Medium"]:
            grounding_urls.update(fact.get('supporting_urls', []))
            if fact.get('source_url'):
                grounding_urls.add(fact['source_url'])
    
    grounding_urls = list(grounding_urls)[:10]  # Limit to 10 URLs
    
    prompt = f"""You are an expert fact-checker assistant answering follow-up questions about a previous analysis.

CONTEXT FROM ANALYSIS:
{context}

GROUNDING SOURCES AVAILABLE:
{', '.join(grounding_urls) if grounding_urls else 'None'}

USER QUESTION: {question}

INSTRUCTIONS:
1. Analyze what information you need to answer this question
2. Use the provided context AND perform a Google Search if needed for additional verification
3. Prioritize High trust sources over Medium/Low
4. If multiple facts are relevant, synthesize them clearly
5. Be concise but thorough (3-4 sentences)
6. Cite specific sources by URL

Think step-by-step, then provide your final answer."""
    
    try:
        # Configure Gemini with grounding
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        
        # Use Gemini 3 Flash (preview)
        model = genai.GenerativeModel(
            model_name='gemini-3-flash-preview',
            generation_config={
                "temperature": 0.3,
                "top_p": 0.95,
                "max_output_tokens": 2048,
                "thinking_level": "medium"  # Enable thought signatures
            }
        )
        
        # Enable Google Search grounding
        tools = [{'google_search': {}}]
        
        response = model.generate_content(
            prompt,
            tools=tools,
            tool_config={'function_calling_config': {'mode': 'AUTO'}}
        )
        
        # Extract thought process and answer
        full_response = response.text
        
        # Gemini 3 Flash includes thought signatures in response
        # We want to return both for transparency
        return full_response
        
    except Exception as e:
        print(f"Gemini 3 Flash error: {e}")
        # Fallback to basic LLM without grounding
        llm = get_llm_for_task("chat")
        response = llm.invoke(prompt)
        return response.content if hasattr(response, 'content') else str(response)


def _parse_thinking_response(full_response: str) -> tuple[str, str]:
    """
    Parse Gemini 2.0 Flash Thinking response into thought process and final answer.
    The model outputs thinking first, then the answer.
    """
    # Gemini Thinking model separates thought process from answer
    # Look for common markers
    markers = ["**Final Answer:**", "**Answer:**", "Final answer:", "Answer:"]
    
    thought_process = ""
    answer = full_response
    
    for marker in markers:
        if marker in full_response:
            parts = full_response.split(marker, 1)
            thought_process = parts[0].strip()
            answer = parts[1].strip()
            break
    
    # If no marker found, assume entire response is the answer
    # and thinking is implicit
    if not thought_process:
        thought_process = "Analyzed context and formulated response."
    
    return thought_process, answer


def _extract_sources(facts: list) -> list:
    """Extract unique sources with metadata"""
    sources = []
    seen_urls = set()
    
    for fact in facts:
        url = fact.get('source_url', '')
        if url and url not in seen_urls:
            sources.append({
                "url": url,
                "trust_score": fact.get('trust_score', 'Low'),
                "claim": fact.get('claim_text', '')[:100] + "..."
            })
            seen_urls.add(url)
        
        # Also add supporting URLs
        for sup_url in fact.get('supporting_urls', []):
            if sup_url and sup_url not in seen_urls:
                sources.append({
                    "url": sup_url,
                    "trust_score": fact.get('trust_score', 'Low'),
                    "claim": "Consensus source"
                })
                seen_urls.add(sup_url)
    
    return sources[:10]  # Limit to 10 sources

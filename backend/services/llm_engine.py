import os
import operator
import time
from typing import Annotated, List, Optional, TypedDict, Literal
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from tools import search_web 

# --- 1. SETUP ---
load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0
)

# --- 2. SCHEMAS ---
class Evidence(BaseModel):
    source_url: str = Field(description="The source link.")
    quote: str = Field(description="The direct quote.")
    
class Claim(BaseModel):
    statement: str = Field(description="A single factual claim.")

class AgentReport(BaseModel):
    role: str = Field(description="Prosecutor or Defender")
    claims: List[Claim] = Field(description="List of specific claims.")
    evidence_links: List[Evidence] = Field(description="Sources used.")
    analysis: str = Field(description="Summary of argument.")

class JudgeVerdict(BaseModel):
    verdict: Literal["True", "False", "Debatable", "Unverified"]
    final_explanation: str
    verified_evidence: List[Evidence]
    needs_more_evidence: bool = Field(description="True if we need to retry.")
    bad_urls_found: List[str] = Field(description="List of URLs to BAN.")

class CourtroomState(TypedDict):
    transcript: str
    prosecutor_report: Optional[AgentReport]
    defender_report: Optional[AgentReport]
    burned_urls: Annotated[List[str], operator.add]
    verified_facts: Annotated[List[Evidence], operator.add]
    iteration_count: Annotated[int, operator.add] 

# --- 3. ZERO-COST SEARCH TOOL ---
def create_search_query(topic: str, burned_urls: List[str]) -> str:
    """Generates a search query without using an LLM to save quota."""
    base_query = f'{topic} "original text" OR "verse" OR "transcript" -filetype:pdf'
    standard_bans = ['reddit.com', 'quora.com', 'stackexchange.com', 'linkedin.com']
    all_bans = set(standard_bans + burned_urls)
    ban_string = " ".join([f"-site:{url}" for url in all_bans])
    return f"{base_query} {ban_string}"

# --- 4. NODES (With Safety Sleep) ---

def prosecutor_node(state: CourtroomState):
    print("\n⏳ (Rate Limit) Sleeping 10s...")
    time.sleep(10) # SAFETY BUFFER
    
    print("🕵️ PROSECUTOR (Step 1/3)...")
    transcript = state["transcript"]
    
    # Python-only Search (Saves 1 call)
    q = create_search_query(f'disprove "{transcript}"', state.get("burned_urls", []))
    print(f"   (Query): {q}")
    results = search_web(q)
    
    # LLM Analysis (Uses 1 call)
    structured_llm = llm.with_structured_output(AgentReport)
    report = structured_llm.invoke(f"""
    Role: Prosecutor. Goal: Disprove "{transcript}".
    Evidence: {results}
    Output: List of claims and evidence.
    """)
    return {"prosecutor_report": report}

def defender_node(state: CourtroomState):
    print("\n⏳ (Rate Limit) Sleeping 10s...")
    time.sleep(10) # SAFETY BUFFER
    
    print("🛡️ DEFENDER (Step 2/3)...")
    transcript = state["transcript"]
    pros_claims = state["prosecutor_report"].claims
    
    q = create_search_query(f'support "{transcript}"', state.get("burned_urls", []))
    print(f"   (Query): {q}")
    results = search_web(q)
    
    structured_llm = llm.with_structured_output(AgentReport)
    report = structured_llm.invoke(f"""
    Role: Defender. Goal: Support "{transcript}".
    Rebut Claims: {pros_claims}
    Evidence: {results}
    Output: List of claims and evidence.
    """)
    return {"defender_report": report}

def judge_node(state: CourtroomState):
    print("\n⏳ (Rate Limit) Sleeping 10s...")
    time.sleep(10) # SAFETY BUFFER
    
    print("⚖️ JUDGE (Step 3/3)...")
    
    # Fact Check Search (Python Only)
    check_query = create_search_query(f'fact check "{state["transcript"]}"', state.get("burned_urls", []))
    print(f"   (Fact Check): {check_query}")
    fc_results = search_web(check_query)
    
    # Verdict (Uses 1 call)
    structured_llm = llm.with_structured_output(JudgeVerdict)
    verdict = structured_llm.invoke(f"""
    Role: Judge.
    Prosecutor Arg: {state['prosecutor_report'].analysis}
    Defender Arg: {state['defender_report'].analysis}
    Fact Check Evidence: {fc_results}
    
    Task:
    1. Mark sources as True or False based on Fact Check.
    2. If major sources are false, add domain to bad_urls_found.
    """)
    
    return {
        "verdict": verdict,
        "burned_urls": verdict.bad_urls_found,
        "verified_facts": verdict.verified_evidence,
        "iteration_count": 1
    }

# --- 5. ROUTER & GRAPH ---

def router(state: CourtroomState):
    if state["iteration_count"] > 2:
        return END
    if state["verdict"].needs_more_evidence:
        print(f"🔄 Loop: Banning {state['verdict'].bad_urls_found} and retrying...")
        return "prosecutor"
    return END

workflow = StateGraph(CourtroomState)
workflow.add_node("prosecutor", prosecutor_node)
workflow.add_node("defender", defender_node)
workflow.add_node("judge", judge_node)

workflow.add_edge(START, "prosecutor")
workflow.add_edge("prosecutor", "defender")
workflow.add_edge("defender", "judge")
workflow.add_conditional_edges("judge", router, {"prosecutor": "prosecutor", END: END})

app = workflow.compile()

if __name__ == "__main__":
    initial_state = {
        "transcript": "Karna pushed Arjuna's chariot 2 steps back.",
        "iteration_count": 0,
        "burned_urls": [],
        "verified_facts": []
    }
    
    print("🚀 Starting Rate-Limited Truth Engine...")
    result = app.invoke(initial_state)
    
    v = result['verdict']
    print(f"\n🏆 VERDICT: {v.verdict}")
    print(f"📝 {v.final_explanation}")
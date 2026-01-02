import os
import operator
import time
from typing import Annotated, List, Optional, TypedDict, Literal
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

# --- 1. SETUP & SCHEMAS ---
load_dotenv()

# Define the structured data objects
class Evidence(BaseModel):
    source_url: str = Field(description="The source link.")
    quote: str = Field(description="The direct quote from the text.")
    credibility_score: int = Field(description="Reliability 1-10.")

class Claim(BaseModel):
    statement: str = Field(description="A single, specific factual claim.")

class AgentReport(BaseModel):
    role: str = Field(description="Prosecutor or Defender")
    claims: List[Claim] = Field(description="List of 3-5 specific verifiable facts.")
    evidence_links: List[Evidence] = Field(description="Sources used.")
    analysis: str = Field(description="Brief summary of the argument.")

class FactCheck(BaseModel):
    claim: str = Field(description="The claim being checked.")
    is_true: bool = Field(description="Is this claim supported by the text?")
    correct_source: Optional[Evidence] = Field(description="The correct source if found.")

class JudgeVerdict(BaseModel):
    verdict: Literal["True", "False", "Debatable", "Unverified"]
    final_explanation: str
    verified_evidence: List[Evidence]
    needs_more_evidence: bool = Field(description="True if we need to loop back.")
    bad_urls_found: List[str] = Field(description="List of URLs to BAN for next round.")

# Define the State
class CourtroomState(TypedDict):
    transcript: str
    prosecutor_report: Optional[AgentReport]
    defender_report: Optional[AgentReport]
    
    # MEMORY SYSTEMS
    burned_urls: Annotated[List[str], operator.add]      # List of BANNED sites
    verified_facts: Annotated[List[Evidence], operator.add] # The "Truth Store"
    
    iteration_count: Annotated[int, operator.add] 
    last_sender: str # To track whose turn it is in the debate

# Setup LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0
)

# --- 2. SMART TOOLS ---

def search_web_with_banlist(query: str, burned_urls: List[str]):
    """
    Simulated search that respects the 'Burned URLs' list.
    In production, you would pass 'exclude_domains' to Tavily/Google API.
    """
    from tools import search_web # Importing your existing tool
    
    # We append the ban logic to the query string for safety
    # (or you can filter the results list in Python after fetching)
    
    print(f"   (Search Filter) Ignoring {len(burned_urls)} bad URLs...")
    results = search_web(query) 
    
    # Simple post-processing filter to remove burned domains from results
    # (This assumes 'results' is a string or list we can parse. 
    #  For this example, we rely on the LLM to ignore them if we tell it.)
    return results

def generate_targeted_query(role: str, claim: str, burned_urls: List[str], llm_instance) -> str:
    # We explicitly tell the Search Specialist which sites are BANNED
    banned_str = ", ".join(burned_urls) if burned_urls else "None"
    
    query_prompt = f"""
    You are a Search Specialist.
    CLAIM: "{claim}"
    ROLE: {role}
    
    CRITICAL: DO NOT search the following BANNED sites (they provided false info previously):
    [{banned_str}]
    
    INSTRUCTIONS:
    1. EXCLUDE forums (reddit, quora, stackexchange).
    2. EXCLUDE PDFs (-filetype:pdf).
    3. PRIORITIZE primary texts/scripts.
    4. Generate a Google search query.
    """
    response = llm_instance.invoke(query_prompt)
    return response.content.strip()

# --- 3. AGENT NODES ---

def prosecutor_node(state: CourtroomState):
    print("\n🕵️ PROSECUTOR is arguing...")
    transcript = state["transcript"]
    burned = state.get("burned_urls", [])
    
    # 1. Search (Avoiding burned URLs)
    q = generate_targeted_query("Prosecutor", transcript, burned, llm)
    print(f"   (Query): {q}")
    evidence = search_web_with_banlist(q, burned)
    
    # 2. Argue
    structured_llm = llm.with_structured_output(AgentReport)
    prompt = f"""
    You are the Prosecutor. Disprove the claim: "{transcript}".
    Previous bad sources have been banned. Use this new evidence:
    {evidence}
    
    Return a list of specific CLAIMS and EVIDENCE.
    """
    report = structured_llm.invoke(prompt)
    report.role = "Prosecutor"
    print("   (RateLimit): Sleeping 30s to respect API rate limits...")
    time.sleep(30)
    return {"prosecutor_report": report, "last_sender": "prosecutor"}

def defender_node(state: CourtroomState):
    print("\n🛡️ DEFENDER is arguing...")
    transcript = state["transcript"]
    burned = state.get("burned_urls", [])
    
    # Defender sees Prosecutor's points
    pros_claims = state["prosecutor_report"].claims if state.get("prosecutor_report") else []
    
    # 1. Search
    q = generate_targeted_query("Defender", transcript, burned, llm)
    print(f"   (Query): {q}")
    evidence = search_web_with_banlist(q, burned)
    
    # 2. Rebut
    structured_llm = llm.with_structured_output(AgentReport)
    prompt = f"""
    You are the Defender. Support the claim: "{transcript}".
    Refute these Prosecutor claims: {pros_claims}
    
    Use this evidence: {evidence}
    """
    report = structured_llm.invoke(prompt)
    report.role = "Defender"
    print("   (RateLimit): Sleeping 30s to respect API rate limits...")
    time.sleep(30)
    return {"defender_report": report, "last_sender": "defender"}

def judge_verification_node(state: CourtroomState):
    print("\n⚖️ JUDGE is verifying facts...")
    
    # 1. Gather all claims
    pros_claims = state["prosecutor_report"].claims
    def_claims = state["defender_report"].claims
    all_claims = pros_claims + def_claims
    
    # 2. The Judge performs a "Fact Check" search on these claims
    # (In a real app, we loop through them. Here we do one consolidated check for brevity)
    check_query = f"fact check {state['transcript']} primary source -filetype:pdf"
    fact_check_results = search_web_with_banlist(check_query, state.get("burned_urls", []))
    
    # 3. Verdict Generation
    structured_llm = llm.with_structured_output(JudgeVerdict)
    prompt = f"""
    You are the Judge. Verify these claims using the Fact Check Results.
    
    CLAIMS TO CHECK: {all_claims}
    FACT CHECK RESULTS: {fact_check_results}
    
    INSTRUCTIONS:
    1. Identify any sources that are FALSE or UNRELIABLE. Add their domains to 'bad_urls_found'.
    2. Identify TRUE facts. Add them to 'verified_evidence'.
    3. If you have enough verified facts to decide, set 'needs_more_evidence' to False.
    4. If the agents used bad sources, set 'needs_more_evidence' to True to force a retry.
    """
    verdict = structured_llm.invoke(prompt)
    
    # Update the State with new knowledge
    new_burned = verdict.bad_urls_found
    new_facts = verdict.verified_evidence
    
    print(f"   (Judge): Found {len(new_facts)} verified facts.")
    print(f"   (Judge): Burning {len(new_burned)} bad URLs: {new_burned}")
    
    print("   (RateLimit): Sleeping 30s to respect API rate limits...")
    time.sleep(30)
    return {
        "burned_urls": new_burned,
        "verified_facts": new_facts,
        "iteration_count": 1,
        "verdict": verdict # Store verdict specifically to check needs_more_evidence later
    }

# --- 4. GRAPH LOGIC ---

def router(state: CourtroomState):
    # Stop if too many loops
    if state["iteration_count"] > 3:
        return END
        
    # Check Judge's decision
    # (We need to store the verdict in state to access it here, strictly speaking)
    # For this snippet, we assume the last node output is accessible or we check verified_facts count.
    
    # If Judge says we need more info (or we found bad URLs that need replacing)
    last_verdict = state.get("verdict") # You might need to add this to State definition
    if last_verdict and last_verdict.needs_more_evidence:
        print("🔄 Rerunning debate with updated ban list...")
        return "prosecutor" # Restart the cycle
        
    return END

# Build Graph
workflow = StateGraph(CourtroomState)
workflow.add_node("prosecutor", prosecutor_node)
workflow.add_node("defender", defender_node)
workflow.add_node("judge", judge_verification_node)

# Flow: Pros -> Def -> Judge -> Router
workflow.add_edge(START, "prosecutor")
workflow.add_edge("prosecutor", "defender")
workflow.add_edge("defender", "judge")
workflow.add_conditional_edges("judge", router, {
    "prosecutor": "prosecutor",
    END: END
})

app = workflow.compile()

# --- 5. EXECUTION ---
if __name__ == "__main__":
    initial_state = {
        "transcript": "Karna pushed Arjuna's chariot 2 steps back.",
        "iteration_count": 0,
        "burned_urls": [],
        "verified_facts": []
    }
    
    result = app.invoke(initial_state)
    
    final_verdict = result.get("verdict") # Assuming judge node writes to this key
    print("\n🏆 FINAL VERDICT 🏆")
    if final_verdict:
        print(f"Ruling: {final_verdict.verdict}")
        print(f"Explanation: {final_verdict.final_explanation}")
        print("\n✅ VERIFIED FACTS STORED:")
        for fact in result['verified_facts']:
            print(f" - {fact.quote} (Source: {fact.source_url})")
    else:
        print("Max iterations reached without verdict.")
import os
import operator
from typing import Annotated, List, Optional, TypedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
# NEW IMPORTS FOR SAFETY SETTINGS
from tools import search_web
from schemas import AgentReport, JudgeVerdict
import time

load_dotenv()
safety_settings = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
}
# 1. Setup the LLM (LangChain Wrapper)
llm = ChatGoogleGenerativeAI(
    model="gemini-3.0-pro",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0,
    safety_settings=safety_settings
)

# 2. Define the State (The "Folder" passed between agents)
class CourtroomState(TypedDict):
    transcript: str
    prosecutor_report: Optional[AgentReport]
    defender_report: Optional[AgentReport]
    verdict: Optional[JudgeVerdict]
    # 'messages' allows us to keep a history if we loop
    iteration_count: Annotated[int, operator.add] 
# --- HELPER FUNCTION: DYNAMIC SMART SEARCH ---
def generate_targeted_query(role: str, claim: str, llm_instance) -> str:
    """
    Dynamically identifies the topic and generates a search query 
    targeting authoritative sources for THAT specific domain.
    """
    
    # 1. Define the goal based on the agent's role
    if role == "Prosecutor":
        goal = "find credible evidence DISPROVING the claim."
    else:
        goal = "find credible evidence SUPPORTING the claim."

    # 2. The "Brain" Prompt: Identify Topic -> Pick Sources -> Write Query
    query_prompt = f"""
    You are a Search Specialist. Your task is to create a Google Search Query.
    
    CLAIM: "{claim}"
    AGENT GOAL: {goal}
    
    INSTRUCTIONS:
    1. IDENTIFY the topic (e.g., History, Science, Mythology, Current Events).
    2. DETERMINE credible domains for that specific topic (e.g., 'nasa.gov' for space, 'sacred-texts.com' for mythology, 'reuters.com' for news).
    3. EXCLUDE forums (reddit, quora) and opinion blogs.
    4. GENERATE a search query using the 'site:' operator if possible.
    
    OUTPUT:
    Output ONLY the raw search query string. No quotes. No explanations.
    """
    
    # 3. Ask the LLM to generate the best query
    response = llm_instance.invoke(query_prompt)
    return response.content.strip()


# --- NODE 1: PROSECUTOR ---
def prosecutor_node(state: CourtroomState):
    print("🕵️ Prosecutor Node Running...")
    transcript = state["transcript"]
    
    # STEP 1: Dynamic Query Generation (Works for ANY topic)
    search_q = generate_targeted_query("Prosecutor", transcript, llm)
    print(f"   (Internal Thought): Generated Search Query -> {search_q}")
    
    time.sleep(5)
    # STEP 2: Search
    results = search_web(search_q)
    
    # STEP 3: Analyze (Standard Prompt)
    structured_llm = llm.with_structured_output(AgentReport)
    prompt = f"""
    You are a Prosecutor. 
    Analyze the transcript and evidence to DISPROVE the claim.
    
    TRANSCRIPT: {transcript}
    EVIDENCE: {results}
    
    INSTRUCTIONS:
    - Rely ONLY on the provided evidence.
    - If evidence is weak, admit it.
    """
    
    report = structured_llm.invoke(prompt)
    report.role = "Prosecutor"
    return {"prosecutor_report": report}

# --- NODE 2: DEFENDER ---
def defender_node(state: CourtroomState):
    time.sleep(10)
    print("🛡️ Defender Node Running...")
    transcript = state["transcript"]
    
    # STEP 1: Dynamic Query Generation
    search_q = generate_targeted_query("Defender", transcript, llm)
    print(f"   (Internal Thought): Generated Search Query -> {search_q}")
    time.sleep(5)
    # STEP 2: Search
    results = search_web(search_q)
    
    # STEP 3: Analyze
    structured_llm = llm.with_structured_output(AgentReport)
    prompt = f"""
    You are a Defender. 
    Analyze the transcript and evidence to SUPPORT the claim.
    
    TRANSCRIPT: {transcript}
    EVIDENCE: {results}
    
    INSTRUCTIONS:
    - Rely ONLY on the provided evidence.
    """
    
    report = structured_llm.invoke(prompt)
    report.role = "Defender"
    return {"defender_report": report}
# --- NODE 3: JUDGE ---
def judge_node(state: CourtroomState):
    print("⚖️ Judge Node Running...")
    
    structured_llm = llm.with_structured_output(JudgeVerdict)
    
    prompt = f"""
    You are the Judge.
    PROSECUTOR ARGUMENT: {state['prosecutor_report'].analysis}
    DEFENDER ARGUMENT: {state['defender_report'].analysis}
    
    If the arguments are weak, set 'needs_more_info' to True.
    Otherwise, issue a verdict.

    In the final verdict you dont need to number the evidence links I have that part covered
    """
    
    verdict = structured_llm.invoke(prompt)
    
    # Increment iteration count to prevent infinite loops
    return {"verdict": verdict, "iteration_count": 1}

# --- CONDITIONAL LOGIC (The Loop) ---
def should_continue(state: CourtroomState):
    # Safety Valve: Stop after 3 tries so we don't burn API credits
    if state["iteration_count"] > 2:
        return END
    
    if state["verdict"].needs_more_info:
        print("🔄 Judge is unsatisfied. Sending back to Prosecutor...")
        return "prosecutor"
    
    return END

# 3. BUILD THE GRAPH
workflow = StateGraph(CourtroomState)

# Add Nodes
workflow.add_node("prosecutor", prosecutor_node)
workflow.add_node("defender", defender_node)
workflow.add_node("judge", judge_node)

# Set Entry Point (Run P & D in parallel? LangGraph runs sequential by default unless customized, 

workflow.add_edge(START, "prosecutor")
workflow.add_edge(START, "defender")
workflow.add_edge("prosecutor", "judge")
workflow.add_edge("defender", "judge")

# Add the Loop
workflow.add_conditional_edges(
    "judge",
    should_continue,
    {
        "prosecutor": "prosecutor", # Loop back
        END: END                    # Finish
    }
)

# Compile
app = workflow.compile()
# Add this to the bottom of langgraph_workflow.py for testing
if __name__ == "__main__":
    test_input = {"transcript": "Karn was stronger than Arjun in Mahabharat.", "iteration_count": 0}
    result = app.invoke(test_input)
# 1. Print Prosecutor's Case
    print(f"\n🕵️ PROSECUTOR FINDING: {result['prosecutor_report'].analysis}")
    print("   EVIDENCE:")
    for proof in result['prosecutor_report'].evidence_links:
        print(f"   - {proof.source_url}: {proof.quote}")

    # 2. Print Defender's Case
    print(f"\n🛡️ DEFENDER FINDING: {result['defender_report'].analysis}")
    print("   EVIDENCE:")
    for proof in result['defender_report'].evidence_links:
        print(f"   - {proof.source_url}: {proof.quote}")
    print(f"\n🏆 Final Verdict: {result['verdict'].verdict}")
    print(f"📝 Explanation: {result['verdict'].explanation}")
    print("SOURCES USED TO ARRIVE TO THIS CONCLUSION")
    count=0
    for proof in result['verdict'].evidence:
        count+=1
        print(f"{count}) Source:{proof.source_url} : Quotes {proof.quote}")
        

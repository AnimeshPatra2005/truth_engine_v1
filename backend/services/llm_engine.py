import os
import re
import json
import time
import requests
import operator
from typing import Annotated, List, Optional, TypedDict, Literal
from dotenv import load_dotenv
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# LangGraph & AI
from langgraph.graph import StateGraph, END, START
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from services.tools import search_web 

load_dotenv()

# ==============================================================================
# 1. SETUP
# ==============================================================================
MODEL_NAME = "gemini-2.5-flash"
# Rate limiting configuration
API_CALL_DELAY = 10  # seconds between calls
MAX_RETRIES_ON_QUOTA = 3  # number of retries for quota errors
api_call_count = 0  # Track API calls

# FIX: Ensure we use the stable 1.5 model
llm_analysis = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY_ANALYSIS"), 
    temperature=0
)

llm_search = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY_SEARCH"),   
    temperature=0.7 
)

# ==============================================================================
# 2. ROBUST UTILS & TOOLS
# ==============================================================================

def safe_invoke_json(model, prompt_text, pydantic_object, max_retries=MAX_RETRIES_ON_QUOTA):
    """
    Bulletproof JSON invoker with intelligent rate limiting and quota handling.
    """
    global api_call_count
    schema = pydantic_object.model_json_schema()
    final_prompt = f"{prompt_text}\n\nIMPORTANT: Return ONLY valid JSON matching this schema: \n{json.dumps(schema)}"
    
    for attempt in range(max_retries):
        try:
            api_call_count += 1
            print(f"   ⏳ [API Call #{api_call_count}] Waiting {API_CALL_DELAY} seconds before call...")
            time.sleep(API_CALL_DELAY)
            
            # 1. Invoke LLM
            response = model.invoke(final_prompt)
            
            # 2. Extract content (handle both string and list responses)
            if hasattr(response, 'content'):
                content = response.content
                # Handle list responses (new Gemini format)
                if isinstance(content, list):
                    # Extract text from list of content blocks
                    content = ' '.join([
                        block.get('text', '') if isinstance(block, dict) 
                        else str(block) 
                        for block in content
                    ])
                elif not isinstance(content, str):
                    content = str(content)
            else:
                content = str(response)
            
            # 3. Clean Markdown
            content = re.sub(r'```json\s*', '', content).replace('```', '').strip()
            
            # 4. Extract JSON wrapper
            if "{" in content and "}" in content:
                content = content[content.find("{"):content.rfind("}")+1]
                
            # 5. Parse & Validate
            parsed_dict = json.loads(content)
            validated_obj = pydantic_object(**parsed_dict)
            print(f"   ✅ API Call #{api_call_count} successful")
            return validated_obj.model_dump()

        except Exception as e:
            error_str = str(e)
            
            # Check if it's a quota/rate limit error
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                # Extract retry delay from error message
                retry_match = re.search(r'retry in (\d+\.?\d*)s', error_str)
                if retry_match:
                    retry_delay = float(retry_match.group(1)) + 2  # Add 2 seconds buffer
                else:
                    retry_delay = 60  # Default to 60 seconds
                
                print(f"   ⚠️ QUOTA EXHAUSTED (Attempt {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    print(f"   ⏱️ Waiting {retry_delay:.1f} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"   ❌ All retries exhausted. API quota likely depleted for today.")
                    print(f"   💡 Solution: Wait 24 hours or use a different API key")
                    return {}
            else:
                # Other errors (JSON parsing, etc.)
                print(f"   ⚠️ LLM/JSON ERROR: {e}")
                return {}
    
    return {}

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def check_google_fact_check_tool(query: str):
    """Tool: Queries Google Fact Check API with Error Handling."""
    try:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY_SEARCH")
        url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        params = {"query": query, "key": api_key, "languageCode": "en"}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return f"API Error: {response.status_code}"
            
        data = response.json()
        if "claims" in data and data["claims"]:
            best = data["claims"][0]
            review = best.get("claimReview", [])[0]
            return f"MATCH: {review['publisher']['name']} rates this '{review['textualRating']}' ({review['url']})"
        return "No fact check found."
    except Exception as e:
        print(f"   ⚠️ Fact Check Tool Error: {e}")
        return "Tool Unavailable"

def consensus_search_tool(claim: str):
    """Tool: Performs Majority Vote search with Network Safety."""
    query = f'is it true that "{claim}" -site:quora.com -site:reddit.com -site:stackexchange.com -site:twitter.com'
    print(f"   📊 CONSENSUS CHECK: {query}")
    try:
        results = search_web(query)
        if not results: return "No results found."
        return str(results)[:5000]
    except Exception as e:
        print(f"      ⚠️ Network Error during consensus check: {e}")
        return "Search failed due to network error."

# ==============================================================================
# 3. SCHEMAS
# ==============================================================================

class ContextAnalysis(BaseModel):
    topic_category: Literal["Science/Legal", "Mythology/History", "News/Viral", "General"]
    primary_keywords: List[str] = Field(description="Keywords for Primary Source")
    trusted_domains: List[str] = Field(description="List of domains to trust")

class SearchQuery(BaseModel):
    query: str
    explanation: str

class Evidence(BaseModel):
    source_url: str
    quote: str
    trust_score: Literal["High", "Low"]

class AgentReport(BaseModel):
    role: str
    main_argument: str
    key_claims: List[str]
    evidence_found: List[Evidence]

class VerificationResult(BaseModel):
    claim: str
    method_used: Literal["FactCheckAPI", "PrimarySource", "ConsensusVote"]
    status: Literal["Verified", "Debunked", "Unclear"]
    details: str

class FinalVerdict(BaseModel):
    verdict: Literal["True", "False", "Debatable", "Unverified"]
    summary: str
    verifications: List[VerificationResult]

class CourtroomState(TypedDict):
    transcript: str
    context: Optional[ContextAnalysis]
    prosecutor_report: Optional[AgentReport]
    defender_report: Optional[AgentReport]
    final_verdict: Optional[FinalVerdict]

# ==============================================================================
# 4. NODES (Wrapped in TRY/EXCEPT)
# ==============================================================================

# NODE 1: CONTEXT ANALYZER
def context_analyzer_node(state: CourtroomState):
    print("\n🧠 ANALYZING CONTEXT...")
    try:
        prompt = f"""
        Analyze the claim: "{state['transcript']}"
        Determine Context (Science/Legal, Mythology/History, News, General).
        Output JSON.
        """
        context = safe_invoke_json(llm_analysis, prompt, ContextAnalysis)
        
        # Fallback if LLM fails
        if not context:
            print("   ⚠️ Context Analysis Failed. Defaulting to General.")
            context = {"topic_category": "General", "primary_keywords": [], "trusted_domains": []}
            
        # --- NEW PRINT STATEMENTS ---
        print(f"   📂 Category: {context.get('topic_category')}")
        print(f"   🔑 Keywords: {context.get('primary_keywords')}")
        print(f"   🏰 Trusted Domains: {context.get('trusted_domains')}")
        # ----------------------------

        return {"context": context}
        
    except Exception as e:
        print(f"   ❌ Critical Error in Context Node: {e}")
        return {"context": {"topic_category": "General"}}
    
# AGENT SEARCH HELPER
def run_agent(role: str, state: CourtroomState):
    try:
        transcript = state["transcript"]
        ctx = state.get("context", {})
        
        if role == "Prosecutor":
            intent = "DISPROVE"
            keywords = "myth OR misconception OR interpolation OR false OR 'not in critical edition' OR debunked"
        else:
            intent = "SUPPORT"
            keywords = "proof OR evidence OR citation OR 'original text' OR confirmation OR 'scripture reference'"

        prompt = f"""
        You are the {role}. CLAIM: "{transcript}". CONTEXT: {ctx.get('topic_category')}.
        GOAL: {intent} this claim.
        Combine Context Keywords ({ctx.get('primary_keywords')}) with Adversarial Keywords ({keywords}) into a Google query.
        """
        
        q_data = safe_invoke_json(llm_search, prompt, SearchQuery)
        query = q_data.get('query', transcript)
        
        # --- NEW PRINT ---
        print(f"\n{'🕵️' if role=='Prosecutor' else '🛡️'} {role.upper()} SEARCH: {query}")
        # -----------------
        
        # Search wrapped in try/except
        try:
            raw_results = search_web(query)
            # --- NEW PRINT ---
            print(f"   📄 Found {len(raw_results)} search results.")
            print(f"   📄 Raw Text Content Length: {len(str(raw_results))} characters.")
            # -----------------
        except Exception as e:
            print(f"      ⚠️ Search Tool Error: {e}")
            raw_results = "Search failed."
        
        prompt = f"""
        Role: {role}. Claim: "{transcript}". Evidence: {str(raw_results)[:5000]}
        Task: Build an argument to {intent} the claim. Extract key claims and evidence links.
        """
        return safe_invoke_json(llm_analysis, prompt, AgentReport)
        
    except Exception as e:
        print(f"   ❌ Error running Agent {role}: {e}")
        return {}

# NODE 2: PROSECUTOR
def prosecutor_node(state: CourtroomState):
    try:
        report_data = run_agent("Prosecutor", state)
        if not report_data: raise ValueError("Empty Report")
        return {"prosecutor_report": AgentReport(**report_data)}
    except Exception as e:
        print(f"   ⚠️ Prosecutor Failed: {e}")
        dummy = AgentReport(role="Pros", main_argument="Failed to generate.", key_claims=[], evidence_found=[])
        return {"prosecutor_report": dummy}

# NODE 3: DEFENDER
def defender_node(state: CourtroomState):
    try:
        report_data = run_agent("Defender", state)
        if not report_data: raise ValueError("Empty Report")
        return {"defender_report": AgentReport(**report_data)}
    except Exception as e:
        print(f"   ⚠️ Defender Failed: {e}")
        dummy = AgentReport(role="Def", main_argument="Failed to generate.", key_claims=[], evidence_found=[])
        return {"defender_report": dummy}

# NODE 4: THE JUDGE
def judge_node(state: CourtroomState):
    print("\n⚖️ JUDGE VERIFYING CLAIMS...")
    try:
        pros = state.get('prosecutor_report')
        defs = state.get('defender_report')
        ctx = state.get('context', {})
        
        # 1. Collect Major Claims
        claims_to_check = []
        if pros: claims_to_check.extend(pros.key_claims[:3])
        if defs: claims_to_check.extend(defs.key_claims[:3])
        
        # --- NEW PRINT ---
        print(f"   📋 Claims Selected for Verification: {len(claims_to_check)}")
        for i, c in enumerate(claims_to_check):
            print(f"      {i+1}. {c}")
        # -----------------
        
        verifications = []
        
        for claim in claims_to_check:
            print(f"\n   👉 Processing Claim: '{claim}'")
            
            # LEVEL 1: FACT CHECK
            print("      [Level 1] Checking Fact Check API...")
            fc_result = check_google_fact_check_tool(claim)
            if "MATCH:" in fc_result:
                print(f"      ✅ Level 1 Passed: {fc_result}")
                verifications.append(VerificationResult(
                    claim=claim, method_used="FactCheckAPI", status="Debunked" if "False" in fc_result else "Verified", details=fc_result
                ))
                continue
            print("      ❌ Level 1 Failed (No Official Record)")
                
            # LEVEL 2: PRIMARY SOURCE
            print("      [Level 2] Checking Trusted Domains...")
            found_trusted = False
            all_evidence = (pros.evidence_found if pros else []) + (defs.evidence_found if defs else [])
            for ev in all_evidence:
                if any(d in ev.source_url for d in ctx.get('trusted_domains', [])):
                    print(f"      ✅ Level 2 Passed: Found source {ev.source_url}")
                    verifications.append(VerificationResult(
                        claim=claim, method_used="PrimarySource", status="Verified", details=f"Supported by Trusted Source: {ev.source_url}"
                    ))
                    found_trusted = True
                    break
            if found_trusted: continue
            print("      ❌ Level 2 Failed (No Trusted Source Found)")
            
            # LEVEL 3: CONSENSUS
            print("      [Level 3] Initiating Consensus Vote (LLM Analysis)...")
            consensus_data = consensus_search_tool(claim)
            
            prompt = f"""
            Analyze these search results for the claim: "{claim}"
            Results: {consensus_data}
            
            CRITICAL TASK:
            - If search results say the event appears to be "Misleading","Fake","False","Myth", "Folklore", or "Not in Critical Edition", status is "Debunked".
            - If search results say the event "Historically Happened" or is in the "Original Text", status is "Verified".
            - If sources disagree on the *facts*, status is "Unclear".
            
            Output JSON (Verified/Debunked/Unclear).
            """
            vote = safe_invoke_json(llm_analysis, prompt, VerificationResult)
            if not vote: vote = {"status": "Unclear", "details": "Consensus analysis failed"}
            
            # --- NEW PRINT ---
            print(f"      🗳️ Consensus Result: {vote.get('status')} | {vote.get('details')}")
            # -----------------
            
            verifications.append(VerificationResult(
                claim=claim, method_used="ConsensusVote", status=vote.get('status', 'Unclear'), details=vote.get('details', 'Mixed results')
            ))

        # FINAL VERDICT
        print("\n   🔨 Phase 2: Writing Final Verdict...")
        prompt = f"""
        Judge Verdict. Claim: '{state['transcript']}'. 
        Verifications: {json.dumps([v.model_dump() for v in verifications])}
        
        Task: Write a clear, professional summary strictly involving primary evidences example citations or quotes from original document or text (if applied)
        - Verdict: "False" if the primary claim is Debunked.
        - Verdict: "True" if Verified.
        - Verdict: "Debatable" ONLY if reputable sources disagree.
        """
        verdict_data = safe_invoke_json(llm_analysis, prompt, FinalVerdict)
        
        if not verdict_data:
            raise ValueError("LLM returned empty verdict")
            
        return {"final_verdict": FinalVerdict(**verdict_data)}

    except Exception as e:
        print(f"   ❌ Critical Error in Judge Node: {e}")
        fallback = FinalVerdict(verdict="Unverified", summary=f"System Error: {e}", verifications=[])
        return {"final_verdict": fallback}
# ==============================================================================
# 5. WORKFLOW
# ==============================================================================

workflow = StateGraph(CourtroomState)
workflow.add_node("context_analyzer", context_analyzer_node)
workflow.add_node("prosecutor", prosecutor_node)
workflow.add_node("defender", defender_node)
workflow.add_node("judge", judge_node)

workflow.add_edge(START, "context_analyzer")
workflow.add_edge("context_analyzer", "prosecutor")
workflow.add_edge("prosecutor", "defender")
workflow.add_edge("defender", "judge")
workflow.add_edge("judge", END)

app = workflow.compile()

# ==============================================================================
# 6. WRAPPER FUNCTION FOR API USAGE
# ==============================================================================

def analyze_text(transcript: str) -> dict:
    """Wrapper function to analyze transcript and return verdict result"""
    try:
        result = app.invoke({"transcript": transcript})
        return result.get('final_verdict', {})
    except Exception as e:
        print(f"Error analyzing text: {e}")
        return {"error": str(e)}

# ==============================================================================
# 6. RUNNER
# ==============================================================================

# ==============================================================================
# 6. RUNNER (GOD MODE EDITION)
# ==============================================================================

if __name__ == "__main__":
    transcript = "Umar Khalid was innocent."
    
    print(f"🚀 ENGINE STARTING: '{transcript}'")
    print(f"⏱️ Rate Limiting: {API_CALL_DELAY}s delay")
    print(f"📊 Model: {MODEL_NAME}")
    
    try:
        start_time = time.time()
        result = app.invoke({"transcript": transcript})
        elapsed = time.time() - start_time
        
        v = result.get('final_verdict')
        
        print("\n" + "="*50)
        print("🏆 FINAL VERDICT REPORT")
        print("="*50)
        print(f"⏱️ Total runtime: {elapsed / 60:.1f} minutes")
        print(f"📊 Total API calls made: {api_call_count}")
        
        if v:
            # Handle Pydantic object vs Dict
            verdict_val = v.get('verdict') if isinstance(v, dict) else v.verdict
            summary_val = v.get('summary') if isinstance(v, dict) else v.summary
            verifications = v.get('verifications') if isinstance(v, dict) else v.verifications

            print(f"\n⚖️ JUDGEMENT: {verdict_val.upper()}")
            print(f"📝 SUMMARY:\n{summary_val}")
            
            if verifications:
                print("\n🔍 DETAILED EVIDENCE LOG:")
                for i, check in enumerate(verifications):
                    # Handle Pydantic object vs Dict inside list
                    c_claim = check.get('claim') if isinstance(check, dict) else check.claim
                    c_status = check.get('status') if isinstance(check, dict) else check.status
                    c_method = check.get('method_used') if isinstance(check, dict) else check.method_used
                    c_details = check.get('details') if isinstance(check, dict) else check.details
                    
                    print(f"\n   #{i+1} CLAIM: \"{c_claim}\"")
                    print(f"      📍 METHOD:  {c_method}")
                    print(f"      ✅ STATUS:  {c_status}")
                    print(f"      📜 PROOF:   {c_details}")
                    print("      " + "-"*30)
        else:
            print("❌ No verdict generated.")

    except Exception as e:
        print(f"\n💥 SYSTEM FAILURE: {e}")
        print(f"📊 API calls completed before failure: {api_call_count}")
"""
Compass Engine — Regulatory Communication Verifier for Satya.

Analyzes suspicious emails, messages, and communications against
curated regulatory ground rules (what SEBI/RBI/NSE/BSE provably never do).

Pipeline:
  1. Extract demands/asks from the pasted message (1 LLM call)
  2. Match each ask against regulatory_rules.json (instant, no API)
  3. Web search fallback for unmatched asks
  4. Synthesize structured verdict with risk scoring (1 LLM call)

Risk scoring parameters:
  - Financial exposure (amount of money targeted)
  - Information sensitivity (credentials, OTP, account details)
  - Urgency pressure (artificial deadlines, threats)
  - Authority impersonation (claiming to be SEBI/RBI/boss)
  - Channel anomaly (official entity using WhatsApp/Telegram)
"""

import os
import json
import uuid
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# ==============================================================================
# CONFIGURATION
# ==============================================================================

RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "regulatory_rules.json")
SCAM_CONTEXT_PATH = os.path.join(os.path.dirname(__file__), "..", "scam_context.json")

# LLM for Compass pipeline — uses dedicated GEMINI_API_CHATBOT key
_compass_llm = None

def get_compass_llm():
    """Lazy initialization of Compass LLM."""
    global _compass_llm
    if _compass_llm is None:
        _compass_llm = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            google_api_key=os.getenv("GEMINI_API_CHATBOT"),
            temperature=0.2,
            thinking_level="medium",
            include_thoughts=True,
        )
    return _compass_llm


# ==============================================================================
# KNOWLEDGE BASE LOADING
# ==============================================================================

_regulatory_rules: List[Dict] = []
_scam_context: List[Dict] = []


def load_knowledge_base():
    """Load regulatory rules and scam context at startup."""
    global _regulatory_rules, _scam_context

    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            _regulatory_rules = json.load(f)
        print(f"[OK] Loaded {len(_regulatory_rules)} regulatory rules")
    except Exception as e:
        print(f"[FAIL] Failed to load regulatory rules: {e}")
        _regulatory_rules = []

    try:
        with open(SCAM_CONTEXT_PATH, "r", encoding="utf-8") as f:
            _scam_context = json.load(f)
        print(f"[OK] Loaded {len(_scam_context)} scam context entries")
    except Exception as e:
        print(f"[FAIL] Failed to load scam context: {e}")
        _scam_context = []


def get_rules() -> List[Dict]:
    if not _regulatory_rules:
        load_knowledge_base()
    return _regulatory_rules


def get_scam_context() -> List[Dict]:
    if not _scam_context:
        load_knowledge_base()
    return _scam_context


# ==============================================================================
# STEP 1: EXTRACT DEMANDS FROM MESSAGE
# ==============================================================================

EXTRACTION_PROMPT = """You are a financial fraud analyst specializing in Indian securities market scams.

Analyze the following message/email that a user received and extract ALL demands, asks, or suspicious elements.

MESSAGE:
---
{message}
---

For EACH demand or ask found, extract:
1. "ask": What is being demanded or requested (in plain language)
2. "entity_claimed": Who is the sender claiming to be (e.g., "SEBI", "Boss/CEO", "RBI", "Bank", "Unknown")
3. "type": Category of the ask. Must be one of: "payment_demand", "credential_theft", "impersonation", "guarantee", "communication_channel", "regulatory_fraud", "pump_and_dump", "fake_platform", "behavioral_pattern", "deepfake", "social_engineering"
4. "amount_mentioned": Any specific monetary amount mentioned (null if none)
5. "information_requested": What sensitive information is being asked for (null if none)
6. "urgency_level": How much urgency/pressure is applied ("high", "medium", "low")
7. "channel_used": What communication channel this came through if mentioned ("whatsapp", "email", "sms", "telegram", "phone_call", "letter", "unknown")

Respond ONLY with a valid JSON array. No explanation, no markdown fencing.

Example:
[{{"ask": "Pay ₹50,000 STT to release blocked funds", "entity_claimed": "SEBI", "type": "payment_demand", "amount_mentioned": "₹50,000", "information_requested": null, "urgency_level": "high", "channel_used": "email"}}, {{"ask": "Share bank account details for refund", "entity_claimed": "SEBI", "type": "credential_theft", "amount_mentioned": null, "information_requested": "bank account details", "urgency_level": "medium", "channel_used": "email"}}]
"""


def extract_demands(message: str) -> List[Dict]:
    """Extract demands/asks from a suspicious message using LLM."""
    llm = get_compass_llm()
    prompt = EXTRACTION_PROMPT.format(message=message)

    try:
        response = llm.invoke(prompt)
        content = _extract_text_from_response(response)

        # Clean and parse JSON
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        demands = json.loads(content)
        if not isinstance(demands, list):
            demands = [demands]

        return demands

    except json.JSONDecodeError as e:
        print(f"Failed to parse demand extraction response: {e}")
        print(f"Raw response: {content[:500]}")
        return [{"ask": "Could not parse message", "entity_claimed": "Unknown",
                 "type": "behavioral_pattern", "amount_mentioned": None,
                 "information_requested": None, "urgency_level": "medium",
                 "channel_used": "unknown"}]
    except Exception as e:
        print(f"Demand extraction error: {e}")
        raise


# ==============================================================================
# STEP 2: MATCH AGAINST REGULATORY RULES
# ==============================================================================

def match_rules(demands: List[Dict]) -> List[Dict]:
    """
    For each extracted demand, find matching regulatory rules.
    Uses keyword overlap for fast matching (no API calls).
    Returns demands enriched with matched rules and their citations.
    """
    rules = get_rules()
    enriched_demands = []

    for demand in demands:
        demand_text = (
            f"{demand.get('ask', '')} {demand.get('entity_claimed', '')} "
            f"{demand.get('type', '')} {demand.get('information_requested', '')}"
        ).lower()

        best_match = None
        best_score = 0

        for rule in rules:
            # Score based on keyword overlap
            score = 0
            for keyword in rule.get("keywords", []):
                if keyword.lower() in demand_text:
                    score += 1

            # Category match bonus
            if rule.get("category") == demand.get("type"):
                score += 2

            # Entity match bonus
            if rule.get("entity", "").lower() in demand.get("entity_claimed", "").lower():
                score += 2

            if score > best_score:
                best_score = score
                best_match = rule

        enriched = {**demand}
        if best_match and best_score >= 2:  # Minimum threshold
            enriched["matched_rule"] = {
                "id": best_match["id"],
                "rule": best_match["rule"],
                "what_to_tell_user": best_match["what_to_tell_user"],
                "actionable_steps": best_match["actionable_steps"],
                "proof_links": best_match["proof_links"],
                "severity": best_match["severity"],
                "match_confidence": min(best_score / 5, 1.0)  # Normalize to 0-1
            }
        else:
            enriched["matched_rule"] = None

        enriched_demands.append(enriched)

    return enriched_demands


# ==============================================================================
# STEP 3: WEB SEARCH FALLBACK FOR UNMATCHED DEMANDS
# ==============================================================================

def search_unmatched(demands: List[Dict]) -> List[Dict]:
    """For demands with no rule match, try web search for evidence."""
    try:
        from services.tools import search_web
    except ImportError:
        print("Warning: search_web not available, skipping web search fallback")
        return demands

    for demand in demands:
        if demand.get("matched_rule") is None:
            entity = demand.get("entity_claimed", "")
            ask = demand.get("ask", "")
            query = f"{entity} India fraud scam {ask} SEBI warning"

            try:
                results = search_web(query, intent="compass_verification", max_retries=2)
                if results:
                    demand["web_evidence"] = [
                        {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
                        for r in results[:3]  # Top 3 results
                    ]
                else:
                    demand["web_evidence"] = []
            except Exception as e:
                print(f"Web search fallback failed for demand: {e}")
                demand["web_evidence"] = []

    return demands


# ==============================================================================
# STEP 4: SYNTHESIZE VERDICT WITH RISK SCORING
# ==============================================================================

VERDICT_PROMPT = """You are Satya's Regulatory Compass — a financial fraud analysis expert for the Indian securities market.

A user received a suspicious communication and you have analyzed it. Below are the extracted demands and any matching regulatory rules.

EXTRACTED DEMANDS AND EVIDENCE:
{demands_json}

KNOWN SCAM PATTERNS (for additional context):
{scam_context}

Based on your analysis, provide a comprehensive response to the user. Your response should:

1. Start with an OVERALL RISK ASSESSMENT. Score based on these parameters:
   - Financial Exposure: How much money is at risk? (higher amount = higher risk)
   - Information Sensitivity: Are they asking for credentials, OTP, bank details? (more sensitive = higher risk)
   - Urgency Pressure: Is artificial urgency or threats being used? (more pressure = higher risk)
   - Authority Impersonation: Are they impersonating SEBI/RBI/exchange/boss? (higher authority = higher risk)
   - Channel Anomaly: Is the communication channel unusual for the claimed entity? (more unusual = higher risk)

2. For EACH demand, explain:
   - Whether it violates a known regulatory rule (quote the rule if matched)
   - Why it's suspicious or legitimate
   - Reference the proof links provided

3. End with CLEAR ACTIONABLE STEPS the user should take immediately.

4. If any demand is NOT clearly fraudulent (i.e., you genuinely cannot determine), say so honestly. Do not overstate risk.

Format your risk assessment as:
OVERALL_RISK: HIGH/MEDIUM/LOW
RISK_PARAMETERS:
- Financial Exposure: HIGH/MEDIUM/LOW — [brief reason]
- Information Sensitivity: HIGH/MEDIUM/LOW — [brief reason]  
- Urgency Pressure: HIGH/MEDIUM/LOW — [brief reason]
- Authority Impersonation: HIGH/MEDIUM/LOW — [brief reason]
- Channel Anomaly: HIGH/MEDIUM/LOW — [brief reason]

Then give your detailed analysis in natural, conversational language. Keep it under 500 words.
Reference sources using [Source: label](url) format.

IMPORTANT: Be direct and actionable. This person may be about to lose money."""


def synthesize_verdict(demands: List[Dict], original_message: str) -> Dict:
    """Generate final verdict with risk scoring."""
    llm = get_compass_llm()

    # Build demands JSON for prompt
    demands_for_prompt = []
    for d in demands:
        entry = {
            "ask": d.get("ask"),
            "entity_claimed": d.get("entity_claimed"),
            "type": d.get("type"),
            "amount_mentioned": d.get("amount_mentioned"),
            "information_requested": d.get("information_requested"),
            "urgency_level": d.get("urgency_level"),
        }
        if d.get("matched_rule"):
            entry["matched_regulatory_rule"] = {
                "rule": d["matched_rule"]["rule"],
                "explanation": d["matched_rule"]["what_to_tell_user"],
                "proof_links": d["matched_rule"]["proof_links"],
                "recommended_steps": d["matched_rule"]["actionable_steps"],
            }
        elif d.get("web_evidence"):
            entry["web_evidence"] = d["web_evidence"]
        else:
            entry["no_evidence_found"] = True

        demands_for_prompt.append(entry)

    # Include relevant scam context
    scam_ctx = get_scam_context()
    relevant_scam_entries = []
    message_lower = original_message.lower()
    for entry in scam_ctx:
        desc_lower = entry.get("description", "").lower()
        # Simple relevance check
        if any(word in message_lower for word in desc_lower.split()[:5]):
            relevant_scam_entries.append({
                "title": entry["title"],
                "description": entry["description"],
                "source_url": entry.get("source_url", "")
            })

    prompt = VERDICT_PROMPT.format(
        demands_json=json.dumps(demands_for_prompt, indent=2),
        scam_context=json.dumps(relevant_scam_entries[:5], indent=2) if relevant_scam_entries else "No directly matching scam patterns found."
    )

    try:
        response = llm.invoke(prompt)
        thought_process, answer = _parse_thinking_response(response)

        # Extract risk level from answer
        risk_level = "MEDIUM"  # Default
        for level in ["HIGH", "MEDIUM", "LOW"]:
            if f"OVERALL_RISK: {level}" in answer.upper():
                risk_level = level
                break

        # Extract risk parameters
        risk_parameters = _extract_risk_parameters(answer)

        # Collect all citations
        citations = []
        seen_urls = set()
        for d in demands:
            if d.get("matched_rule"):
                for link in d["matched_rule"].get("proof_links", []):
                    if link["url"] not in seen_urls:
                        citations.append(link)
                        seen_urls.add(link["url"])
            if d.get("web_evidence"):
                for ev in d["web_evidence"]:
                    if ev["url"] not in seen_urls:
                        citations.append({"label": ev["title"], "url": ev["url"]})
                        seen_urls.add(ev["url"])

        # Collect all actionable steps
        all_steps = []
        seen_steps = set()
        for d in demands:
            if d.get("matched_rule"):
                for step in d["matched_rule"].get("actionable_steps", []):
                    if step not in seen_steps:
                        all_steps.append(step)
                        seen_steps.add(step)

        return {
            "overall_risk": risk_level,
            "risk_parameters": risk_parameters,
            "demands": demands,
            "response": answer,
            "thought_process": thought_process,
            "citations": citations,
            "actionable_steps": all_steps,
        }

    except Exception as e:
        print(f"Verdict synthesis error: {e}")
        raise


def _extract_risk_parameters(answer: str) -> Dict[str, Dict]:
    """Extract structured risk parameters from the LLM response."""
    params = {}
    param_names = [
        "Financial Exposure",
        "Information Sensitivity",
        "Urgency Pressure",
        "Authority Impersonation",
        "Channel Anomaly",
    ]

    for name in param_names:
        params[name] = {"level": "MEDIUM", "reason": ""}
        for line in answer.split("\n"):
            if name.lower() in line.lower():
                for level in ["HIGH", "MEDIUM", "LOW"]:
                    if level in line.upper():
                        params[name]["level"] = level
                        # Extract reason after the dash
                        parts = line.split("—")
                        if len(parts) > 1:
                            params[name]["reason"] = parts[-1].strip()
                        elif "–" in line:
                            parts = line.split("–")
                            params[name]["reason"] = parts[-1].strip()
                        break
                break

    return params


# ==============================================================================
# MAIN ANALYSIS FUNCTION
# ==============================================================================

def analyze_message(message: str) -> Dict:
    """
    Full Compass analysis pipeline.
    Returns structured result with risk assessment, citations, and actionable steps.
    """
    print("\n═══════════════════════════════════════════")
    print("  REGULATORY COMPASS — Analysis Started")
    print("═══════════════════════════════════════════")

    # Step 1: Extract demands
    print("\n→ Step 1: Extracting demands from message...")
    demands = extract_demands(message)
    print(f"  Found {len(demands)} demand(s)")

    # Step 2: Match against rules
    print("\n→ Step 2: Matching against regulatory rules...")
    demands = match_rules(demands)
    matched = sum(1 for d in demands if d.get("matched_rule"))
    print(f"  Matched {matched}/{len(demands)} demands to rules")

    # Step 3: Web search for unmatched
    unmatched = sum(1 for d in demands if not d.get("matched_rule"))
    if unmatched > 0:
        print(f"\n→ Step 3: Web search for {unmatched} unmatched demand(s)...")
        demands = search_unmatched(demands)
    else:
        print("\n→ Step 3: All demands matched — skipping web search")

    # Step 4: Synthesize verdict
    print("\n→ Step 4: Synthesizing verdict with risk scoring...")
    result = synthesize_verdict(demands, message)

    print(f"\n  OVERALL RISK: {result['overall_risk']}")
    print(f"  Citations: {len(result['citations'])}")
    print(f"  Action steps: {len(result['actionable_steps'])}")
    print("═══════════════════════════════════════════\n")

    return result


# ==============================================================================
# FOLLOW-UP CHAT
# ==============================================================================

FOLLOWUP_PROMPT = """You are Satya's Regulatory Compass — a financial fraud expert for the Indian securities market.

You previously analyzed a suspicious communication for this user. Here is the full conversation so far:

{conversation_history}

The regulatory rules and evidence from the initial analysis are still available:
{context_summary}

Now answer the user's follow-up question helpfully and directly. You can:
- Give specific steps to report fraud (cybercrime.gov.in, SEBI SCORES, police FIR)
- Explain regulatory rules in more detail
- Clarify risk assessment
- Advise on immediate protective actions (bank alerts, password changes, etc.)

Keep your response conversational, direct, and under 300 words.
Reference sources using [Source: label](url) format when relevant.
If the user asks about something outside your analysis scope, say so honestly."""


def generate_followup(session_data: Dict, user_message: str) -> Dict:
    """Generate response to a follow-up question using conversation history."""
    llm = get_compass_llm()

    # Build conversation history string
    history_parts = []
    for msg in session_data.get("conversation_history", []):
        role = "USER" if msg["role"] == "user" else "SATYA"
        history_parts.append(f"{role}: {msg['content']}")

    # Add current message
    history_parts.append(f"USER: {user_message}")

    # Build context from initial analysis
    analysis = session_data.get("analysis", {})
    context_parts = []

    if analysis.get("citations"):
        context_parts.append("AVAILABLE SOURCES:")
        for cite in analysis["citations"]:
            context_parts.append(f"  - {cite['label']}: {cite['url']}")

    if analysis.get("actionable_steps"):
        context_parts.append("\nRECOMMENDED STEPS:")
        for step in analysis["actionable_steps"]:
            context_parts.append(f"  - {step}")

    if analysis.get("demands"):
        context_parts.append("\nANALYZED DEMANDS:")
        for d in analysis["demands"]:
            rule_info = ""
            if d.get("matched_rule"):
                rule_info = f" [MATCHED RULE: {d['matched_rule']['rule']}]"
            context_parts.append(f"  - {d.get('ask', 'Unknown')}{rule_info}")

    prompt = FOLLOWUP_PROMPT.format(
        conversation_history="\n".join(history_parts),
        context_summary="\n".join(context_parts) if context_parts else "No prior analysis context."
    )

    try:
        response = llm.invoke(prompt)
        thought_process, answer = _parse_thinking_response(response)

        # Extract any citations used in the response
        used_citations = []
        for cite in analysis.get("citations", []):
            if cite["url"] in answer or cite["label"] in answer:
                used_citations.append(cite)

        return {
            "response": answer,
            "thought_process": thought_process,
            "citations": used_citations,
        }

    except Exception as e:
        print(f"Follow-up generation error: {e}")
        raise


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

def _extract_text_from_response(response) -> str:
    """Extract text content from LangChain response, ignoring thinking blocks."""
    content = response.content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text", "")
            elif isinstance(part, str):
                return part
    elif isinstance(content, str):
        return content
    return str(content)


def _parse_thinking_response(response) -> tuple:
    """Parse LangChain response into (thought_process, answer)."""
    content = response.content
    thought_process = ""
    answer = ""

    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "thinking":
                    thought_process = part.get("thinking", "")[:500]
                elif part.get("type") == "text":
                    answer = part.get("text", "")
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

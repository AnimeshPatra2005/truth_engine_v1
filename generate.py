"""
generate_scam_feed.py
=====================
ONE-TIME SCRIPT — run this manually before the demo.

What it does:
  1. Runs targeted Tavily queries for recent Indian financial scams (2025-2026)
  2. Deduplicates results by URL
  3. Passes everything to Gemini to normalize into clean 1-liner JSON entries
  4. Saves output to backend/scam_context.json

That JSON file is then:
  - Displayed as a "Threat Intelligence Feed" on the website
  - Loaded at startup and injected as context into the judge LLM

Usage:
  python generate_scam_feed.py

Requirements (already in your requirements.txt):
  tavily-python, google-generativeai, python-dotenv
"""

import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

# ── Tavily ─────────────────────────────────────────────────────────────────────
from tavily import TavilyClient

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
if not TAVILY_KEY:
    raise SystemExit("TAVILY_API_KEY not set in .env")
tavily = TavilyClient(api_key=TAVILY_KEY)

# ── Gemini ─────────────────────────────────────────────────────────────────────
import google.generativeai as genai

GEMINI_KEY = os.getenv("GEMINI_API_KEY_ANALYSIS") or os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    raise SystemExit("GEMINI_API_KEY_ANALYSIS (or GEMINI_API_KEY) not set in .env")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")

# ── Config ─────────────────────────────────────────────────────────────────────
OUTPUT_PATH = os.path.join("backend", "scam_context.json")

EXCLUDED_DOMAINS = [
    "reddit.com", "quora.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com",
    "youtube.com", "linkedin.com",
]

# Each query covers a different scam angle — no single query covers everything
QUERIES = [
    "SEBI investor alert fraud warning advisory 2026",
    "RBI caution fake investment platform fraud India 2026",
    "deepfake CEO video investment scam India NSE BSE 2026",
    "WhatsApp Telegram stock tip pump dump scam India 2025 2026",
    "boss scam CEO impersonation financial fraud India 2026",
    "fake trading app guaranteed returns fraud SEBI warning 2026",
    "phishing email SMS fake SEBI notice investor fraud India 2026",
]

MIN_RELEVANCE_SCORE = 0.35
MAX_RESULTS_PER_QUERY = 5


# ── Step 1: Collect ────────────────────────────────────────────────────────────
def collect_results() -> list:
    all_results = []
    seen_urls = set()

    for i, query in enumerate(QUERIES, 1):
        print(f"  [{i}/{len(QUERIES)}] Searching: {query[:65]}...")
        try:
            resp = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=MAX_RESULTS_PER_QUERY,
                exclude_domains=EXCLUDED_DOMAINS,
                timeout=30,
            )
            added = 0
            for r in resp.get("results", []):
                url = r.get("url", "")
                score = r.get("score", 0)
                if url and url not in seen_urls and score >= MIN_RELEVANCE_SCORE:
                    seen_urls.add(url)
                    all_results.append({
                        "title":   r.get("title", "").strip(),
                        "url":     url,
                        # Cap content so the Gemini prompt stays reasonable
                        "content": (r.get("content", "") or "")[:600].strip(),
                        "score":   round(score, 3),
                    })
                    added += 1
            print(f"       + {added} new results  (running total: {len(all_results)})")

        except Exception as e:
            print(f"       WARNING: Query failed: {e}")

        # Respect Tavily free-tier rate limit (100 RPM)
        time.sleep(0.7)

    return all_results


# ── Step 2: Normalize with Gemini ─────────────────────────────────────────────
GEMINI_PROMPT = """You are a financial fraud analyst for SEBI's investor protection unit.

Below is a raw list of web articles and press releases about financial scams in India (2025-2026).

Extract ONLY entries genuinely about:
- Deepfake / AI-generated videos impersonating executives or regulators
- Phishing emails / SMS / WhatsApp messages targeting investors
- Fake trading platforms, apps, or investment schemes with guaranteed returns
- Pump-and-dump or finfluencer stock tip scams
- Impersonation of SEBI, RBI, NSE, BSE, or company executives (Boss Scam etc.)
- Voice cloning or synthetic media used for financial fraud

For each valid entry output a JSON object with EXACTLY these fields:
  "id"           : short kebab-case slug, e.g. "boss-scam-2026"
  "title"        : clean title, max 10 words
  "category"     : one of [deepfake, phishing, impersonation, pump_and_dump, fake_platform, voice_cloning, social_engineering, regulatory_fraud]
  "description"  : ONE sentence, max 25 words, describing the scam pattern a retail investor would recognise
  "source_label" : the body that issued the warning, e.g. "SEBI", "RBI", "NSE", "MHA Cybercrime"
  "source_url"   : the original URL from the input
  "date"         : "YYYY-MM" if determinable, otherwise "2026"
  "severity"     : one of [high, medium, low]

Rules:
- DROP entries not about fraud/scam/phishing (general market news, policy updates etc.)
- Do NOT invent facts — use only what is stated in the input
- Deduplicate: if two articles describe the same scam, keep the one with the better source
- Return ONLY a valid JSON array — no markdown fences, no explanation text

Input articles:
{results_json}
"""


def normalize(raw_results: list) -> list:
    prompt = GEMINI_PROMPT.replace(
        "{results_json}",
        json.dumps(raw_results, indent=2, ensure_ascii=False)
    )
    resp = model.generate_content(prompt)
    text = (resp.text or "").strip()

    # Strip markdown fences if Gemini adds them despite instructions
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        data = json.loads(text)
        # Gemini occasionally wraps array in a dict
        if isinstance(data, dict):
            for key in ("entries", "results", "scams", "data"):
                if key in data:
                    data = data[key]
                    break
            else:
                data = list(data.values())[0]
        return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        print(f"\nWARNING: Gemini returned invalid JSON — {e}")
        print("Raw output (first 600 chars):\n", text[:600])
        return []


# ── Step 3: Save ───────────────────────────────────────────────────────────────
def save(data: list) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("\n=== SATYA — Scam Intelligence Feed Generator ===\n")

    print("Step 1 / Collecting raw scam data from the web...")
    raw = collect_results()
    print(f"\n  Total unique articles collected: {len(raw)}\n")

    if not raw:
        print("No results collected. Check TAVILY_API_KEY and internet connection.")
        return

    print("Step 2 / Normalising with Gemini...")
    scam_data = normalize(raw)
    print(f"  Scam entries extracted: {len(scam_data)}\n")

    if not scam_data:
        print("Gemini returned no valid entries.")
        return

    print(f"Step 3 / Saving to {OUTPUT_PATH}")
    save(scam_data)
    print(f"  Saved.\n")

    # ── Preview ────────────────────────────────────────────────────────────────
    print("=" * 65)
    print("PREVIEW")
    print("=" * 65)
    for e in scam_data:
        print(f"[{e.get('severity','?').upper()}] ({e.get('category','?')}) {e.get('title','')}")
        print(f"       {e.get('description','')}")
        print(f"       {e.get('source_label','')}  |  {e.get('source_url','')}")
        print()
    print("=" * 65)
    print(f"Done — {len(scam_data)} entries written to {OUTPUT_PATH}")
    print("Load this file at app startup and inject into the judge system prompt.\n")


if __name__ == "__main__":
    main()

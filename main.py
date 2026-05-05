from fastapi import FastAPI
import requests
import json
from bs4 import BeautifulSoup
import re

app = FastAPI()

# =========================
# 🔍 Search News
# =========================
def search_news(query):
    url = f"https://newsapi.org/v2/everything?q={query}&language=en&sortBy=relevancy&apiKey=YOUR_API_KEY"

    try:
        res = requests.get(url, timeout=10).json()
        return res.get("articles", [])[:3]
    except:
        return []


# =========================
# 🌐 Extract text
# =========================
def extract_text_from_url(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        paragraphs = soup.find_all("p")
        return " ".join([p.get_text() for p in paragraphs])
    except:
        return ""


# =========================
# 🧠 SAFE AI CALL (IMPORTANT FIX)
# =========================
def call_llm(prompt):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "stream": False
            },
            timeout=60  # 🔥 FIX: was 15
        )

        return response.json().get("response", "")

    except Exception as e:
        return None


# =========================
# 🤖 Check Claim
# =========================
def check_claim(claim, articles):

    content = " ".join([
        (a.get("title", "") + " " + a.get("description", ""))
        for a in articles
    ])

    prompt = f"""
You are a strict fact-checking AI.

Claim:
{claim}

Sources:
{content}

Return ONLY JSON:
{{
 "verdict": "TRUE or FALSE or UNKNOWN",
 "reason": "short explanation"
}}
"""

    raw = call_llm(prompt)

    # 🔥 fallback لو AI فشل
    if not raw:
        return {
            "verdict": "UNKNOWN",
            "reason": "LLM timeout or unavailable",
            "confidence": 0.3
        }

    # 🔥 safer JSON parsing
    match = re.search(r"\{.*\}", raw, re.DOTALL)

    try:
        result = json.loads(match.group()) if match else {}
    except:
        result = {"verdict": "UNKNOWN", "reason": "Parse error"}

    # confidence
    confidence = 0.5
    if result.get("verdict") == "TRUE":
        confidence = 0.8
    elif result.get("verdict") == "FALSE":
        confidence = 0.8

    result["confidence"] = confidence
    return result


# =========================
# 📊 Verdict
# =========================
def get_overall_verdict(verification):
    true_count = sum(1 for v in verification if v["verdict"] == "TRUE")
    false_count = sum(1 for v in verification if v["verdict"] == "FALSE")

    if false_count > true_count:
        return "LIKELY FAKE ❌"
    elif true_count > false_count:
        return "LIKELY TRUE ✅"
    else:
        return "UNCERTAIN ⚠️"


# =========================
# 🚀 MAIN API
# =========================
@app.post("/analyze")
def analyze(data: dict):

    text = data.get("text")
    url = data.get("url")

    if url:
        text = extract_text_from_url(url)

    if not text:
        return {"error": "No text provided"}

    # =========================
    # 🧠 Extract Claims
    # =========================
    prompt = f"""
Return ONLY valid JSON.

Rules:
- Extract 3-5 factual claims
- Do NOT invent facts
- Keep claims short

Format:
{{
  "summary": "...",
  "claims": ["...", "...", "..."]
}}

Text:
{text}
"""

    raw = call_llm(prompt)

    if not raw:
        return {
            "error": "LLM timeout (claims extraction failed)"
        }

    match = re.search(r"\{.*\}", raw, re.DOTALL)

    try:
        result = json.loads(match.group()) if match else {}
    except:
        return {"error": "Invalid AI JSON", "raw": raw}

    claims = result.get("claims", [])

    verification = []

    # =========================
    # 🔍 Verification loop
    # =========================
    for claim in claims:

        articles = search_news(claim)

        if not articles:
            verification.append({
                "claim": claim,
                "verdict": "UNKNOWN",
                "reason": "No sources found",
                "confidence": 0.3,
                "sources": []
            })
            continue

        verdict_data = check_claim(claim, articles)

        verification.append({
            "claim": claim,
            "verdict": verdict_data.get("verdict"),
            "reason": verdict_data.get("reason"),
            "confidence": verdict_data.get("confidence"),
            "sources": articles
        })

    return {
        "summary": result.get("summary"),
        "overall_verdict": get_overall_verdict(verification),
        "verification": verification
    }
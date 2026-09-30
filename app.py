import os
import json
import io
import re
import concurrent.futures
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from groq import Groq
import google.generativeai as genai
from PIL import Image
import requests
from bs4 import BeautifulSoup

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB max upload

# ---------- API clients ----------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Prefer a widely available flash model; change if your account has another
        gemini_model = genai.GenerativeModel("gemini-3.8-flash")
    except Exception as e:
        print(f"Gemini init warning: {e}")
        gemini_model = None

# ---------- Shared analysis prompt ----------
SYSTEM_PROMPT = """You are an expert fact-checker and misinformation analyst.
Analyze the provided content (text and/or image of a news article, screenshot, social media post, meme, or claim) and return ONLY a valid JSON object with these exact keys:

{
  "verdict": "REAL" | "FAKE" | "UNCERTAIN",
  "confidence": 0-100,
  "summary": "One concise sentence summarizing your conclusion",
  "reasons": ["reason 1", "reason 2", "reason 3"],
  "red_flags": ["any suspicious claims, emotional language, lack of sources, manipulated image, etc."],
  "suggested_checks": ["what the reader should verify next"],
  "extracted_text": "If an image was provided, extract the main visible text/headline/claims here. Otherwise empty string."
}

Rules:
- Be objective and evidence-based.
- For images: carefully read all visible text, check for signs of editing, mismatched fonts, unusual metadata clues, or classic fake-news visual patterns.
- If the content is too short, unclear, or lacks verifiable claims, return UNCERTAIN.
- confidence is an integer 0-100.
- Do not include any text outside the JSON object.
"""

# ---------- URL helpers ----------
def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def fetch_article_text(url: str) -> tuple[str, str | None]:
    """
    Fetch a news page and extract the main article text.
    Returns (extracted_text, error_message).
    """
    if not is_valid_url(url):
        return "", "Invalid URL. Please use a full http:// or https:// link."

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        resp.raise_for_status()

        # Limit size
        if len(resp.content) > 2_000_000:  # ~2 MB
            return "", "Page is too large to process."

        content_type = resp.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return "", "URL does not point to an HTML page."

        soup = BeautifulSoup(resp.content, "lxml")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript", "svg"]):
            tag.decompose()

        # Try common article selectors first
        article_selectors = [
            "article",
            "[role='main']",
            ".article-body",
            ".article-content",
            ".post-content",
            ".entry-content",
            ".story-body",
            ".content-body",
            "main",
            "#content",
            ".content",
        ]

        text_parts = []
        for selector in article_selectors:
            nodes = soup.select(selector)
            if nodes:
                for node in nodes:
                    # Prefer paragraphs inside
                    paras = node.find_all(["p", "h1", "h2", "h3"])
                    if paras:
                        for p in paras:
                            t = p.get_text(strip=True)
                            if len(t) > 40:  # skip short noise
                                text_parts.append(t)
                    else:
                        t = node.get_text(separator=" ", strip=True)
                        if len(t) > 100:
                            text_parts.append(t)
                if text_parts:
                    break

        # Fallback: all paragraphs
        if not text_parts:
            for p in soup.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 50:
                    text_parts.append(t)

        # Title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True) or title

        full_text = ""
        if title:
            full_text += f"Title: {title}\n\n"
        full_text += "\n\n".join(text_parts)

        # Clean excessive whitespace
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()

        if len(full_text) < 80:
            return "", "Could not extract enough readable article text from this page. It may be behind a paywall, heavily JavaScript-based, or blocked."

        # Truncate very long articles
        if len(full_text) > 12000:
            full_text = full_text[:12000] + "\n\n[... truncated ...]"

        return full_text, None

    except requests.exceptions.Timeout:
        return "", "Request timed out. The website took too long to respond."
    except requests.exceptions.HTTPError as e:
        return "", f"HTTP error: {e.response.status_code}. The page may be blocked or unavailable."
    except requests.exceptions.RequestException as e:
        return "", f"Failed to fetch URL: {str(e)}"
    except Exception as e:
        return "", f"Error extracting content: {str(e)}"


def analyze_with_groq(text: str) -> dict:
    if not groq_client:
        return {"error": "GROQ_API_KEY not configured"}
    if not text or not text.strip():
        return {"error": "No text provided for Groq analysis"}

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this news text:\n\n{text}"}
            ],
            temperature=0.2,
            max_tokens=1024,
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        return {"error": f"Groq error: {str(e)}"}


def analyze_with_gemini(text: str = "", image_bytes: bytes = None, mime_type: str = "image/jpeg") -> dict:
    if not gemini_model:
        return {"error": "GEMINI_API_KEY not configured"}

    try:
        parts = [SYSTEM_PROMPT]

        if text and text.strip():
            parts.append(f"\nAdditional text provided by user:\n{text}")

        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            parts.append(img)
            parts.append("\n(Analyze the image above carefully – extract all visible text and evaluate authenticity.)")
        elif not text.strip():
            return {"error": "No text or image provided"}

        response = gemini_model.generate_content(
            parts,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=1500,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        return {"error": f"Gemini error: {str(e)}"}


def combine_results(groq_res: dict, gemini_res: dict) -> dict:
    """Confidence-weighted combination of the two models."""
    if "error" in groq_res and "error" in gemini_res:
        return {
            "final_verdict": "ERROR",
            "final_confidence": 0,
            "explanation": "Both models failed."
        }

    candidates = []
    if "error" not in groq_res:
        candidates.append(("Groq", groq_res))
    if "error" not in gemini_res:
        candidates.append(("Gemini", gemini_res))

    if not candidates:
        return {"final_verdict": "ERROR", "final_confidence": 0, "explanation": "No valid results"}

    verdict_scores = {"REAL": 0, "FAKE": 0, "UNCERTAIN": 0}
    total_conf = 0
    for name, res in candidates:
        v = res.get("verdict", "UNCERTAIN").upper()
        c = int(res.get("confidence", 50))
        if v in verdict_scores:
            verdict_scores[v] += c
        total_conf += c

    final_verdict = max(verdict_scores, key=verdict_scores.get)
    final_confidence = round(total_conf / len(candidates))

    explanation_parts = []
    for name, res in candidates:
        explanation_parts.append(f"{name}: {res.get('summary', 'No summary')}")

    return {
        "final_verdict": final_verdict,
        "final_confidence": final_confidence,
        "explanation": " | ".join(explanation_parts)
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    text = ""
    image_bytes = None
    mime_type = "image/jpeg"
    source_url = None
    fetch_error = None

    # Support both JSON and multipart form
    if request.content_type and "multipart/form-data" in request.content_type:
        text = (request.form.get("text") or "").strip()
        url = (request.form.get("url") or "").strip()
        file = request.files.get("image")

        if file and file.filename:
            allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
            mime_type = file.mimetype or "image/jpeg"
            if mime_type not in allowed:
                return jsonify({"error": "Unsupported image type. Use JPG, PNG, WEBP or GIF."}), 400
            image_bytes = file.read()
            if len(image_bytes) > 8 * 1024 * 1024:
                return jsonify({"error": "Image too large (max 8 MB)."}), 400

        # If URL is provided, try to fetch article text
        if url:
            source_url = url
            fetched, err = fetch_article_text(url)
            if err:
                fetch_error = err
            elif fetched:
                # Prepend fetched content; keep any user-typed text as extra context
                if text:
                    text = f"{fetched}\n\n--- Additional context from user ---\n{text}"
                else:
                    text = fetched
    else:
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        url = (data.get("url") or "").strip()
        if url:
            source_url = url
            fetched, err = fetch_article_text(url)
            if err:
                fetch_error = err
            elif fetched:
                if text:
                    text = f"{fetched}\n\n--- Additional context from user ---\n{text}"
                else:
                    text = fetched

    if not text and not image_bytes:
        msg = "Please provide text, an image, or a valid article URL."
        if fetch_error:
            msg = fetch_error
        return jsonify({"error": msg}), 400

    if text and len(text) > 15000:
        return jsonify({"error": "Extracted / provided text is too long."}), 400

    # Run models in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_groq = executor.submit(analyze_with_groq, text) if text else None
        future_gemini = executor.submit(analyze_with_gemini, text, image_bytes, mime_type)

        groq_result = future_groq.result() if future_groq else {"error": "No text provided – Groq skipped"}
        gemini_result = future_gemini.result()

    combined = combine_results(groq_result, gemini_result)

    response = {
        "combined": combined,
        "groq": groq_result,
        "gemini": gemini_result,
    }
    if source_url:
        response["source_url"] = source_url
    if fetch_error:
        response["fetch_warning"] = fetch_error

    return jsonify(response)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "groq_configured": bool(GROQ_API_KEY),
        "gemini_configured": bool(GEMINI_API_KEY)
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

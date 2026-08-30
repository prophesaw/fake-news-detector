# Fake News Detector (Flask + Groq + Gemini)

A clean web app that uses **two powerful free-tier AI APIs** to analyze news for authenticity:

- **Groq** → Llama 3.3 70B (very fast text analysis)
- **Google Gemini** → Gemini 2.5 Flash (text + **image** multimodal analysis)

Supports three input methods:

1. **Article URL** – paste a news link, the app fetches & extracts the content
2. **Pasted text** – any claim or article body
3. **Image** – screenshot of article, tweet, meme, etc.

Both models run in parallel and a confidence-weighted combination produces a final verdict.

## Features

- Paste a news article **URL** → automatic content extraction
- Paste any news text / claim
- Upload or drag-and-drop an image (JPG, PNG, WEBP, GIF)
- Gemini extracts visible text from images and evaluates authenticity
- Side-by-side analysis from both models
- Combined verdict + confidence score
- Reasons, red flags, and suggested verification steps
- Modern dark UI, fully responsive

## Quick Start

### 1. Go into the project folder

```bash
cd fake-news-detector
```

### 2. Create virtual environment & install

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Add your API keys

```bash
cp .env.example .env
```

Edit `.env` and put your keys:

| Service | Get free key |
|---------|--------------|
| Groq    | https://console.groq.com/keys |
| Gemini  | https://aistudio.google.com/apikey |

### 4. Run

```bash
python app.py
```

Open → http://localhost:5000

## How it works

1. User provides a **URL**, text, and/or image.
2. If a URL is given, the backend:
   - Fetches the page
   - Extracts the main article title + body (using BeautifulSoup)
3. Text is sent to **Groq** (Llama 3.3)
4. Text + image (if any) are sent to **Gemini** (multimodal)
5. Both return structured JSON (verdict, confidence, reasons…)
6. A weighted combination produces the final verdict

## Project Structure

```
fake-news-detector/
├── app.py
├── requirements.txt
├── .env.example
├── templates/
│   └── index.html
└── static/
    ├── css/style.css
    └── js/app.js
```

## Notes & Limitations

- Both APIs have generous free tiers.
- Image size limit: 8 MB.
- Some sites (paywalls, heavy JavaScript, anti-bot protection) may fail to extract cleanly.
- This tool is for **educational / research** purposes only. Always verify with primary sources.
- Models can still make mistakes — treat the output as a helpful second opinion.

## Optional: Production

```bash
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

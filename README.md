# 🚀 JobPilot — Free ATS Resume Optimizer

A free, open-source AI resume optimizer. Paste your resume + any job description and get an ATS-optimized version in seconds.

🌐 **Live demo: https://jobpilot-production-df41.up.railway.app**

---

## ✨ Features
- Upload resume — PDF, DOCX, or TXT (or paste text)
- ATS score before & after (0–100) with visual ring indicators
- Keyword gap analysis — added, present, and missing keywords
- Side-by-side original vs optimized resume
- Full breakdown of every change made and why
- One-click copy & download of optimized resume

---

## 🛠 Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, Flask |
| AI | Groq API (free tier — Llama 3.3 70B) |
| PDF parsing | PyMuPDF |
| DOCX parsing | python-docx |
| Frontend | HTML, CSS, Vanilla JS |
| Hosting | Railway (free tier) |

---

## 🚀 Run locally

### 1. Get a free Groq API key
Sign up at [console.groq.com](https://console.groq.com) — free, no credit card required.

### 2. Clone & install
```bash
git clone https://github.com/learnwithnikhil-bot/jobpilot.git
cd jobpilot
python3 -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 3. Add your API key
```bash
cp .env.example .env
# Open .env and add: GROQ_API_KEY=your_key_here
```

### 4. Run
```bash
python app.py
# Open http://localhost:8080
```

---

## ☁️ Deploy your own (free)

1. Fork this repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select this repo
4. Add environment variable: `GROQ_API_KEY=your_key`
5. Click deploy — you get a free public URL in ~2 minutes

---

## 📁 Project Structure

# 🚀 JobPilot — Free ATS Resume Optimizer

A 100% free, open-source AI resume optimizer that runs entirely on your machine.  
**No API keys. No accounts. No data sent anywhere. Ever.**

Powered by [Ollama](https://ollama.com) (local AI) + Python Flask.

---

## ✨ Features
- Upload resume (PDF, DOCX, TXT) or paste text
- ATS score before & after (0–100)
- Keyword gap analysis — added, present, missing
- Side-by-side original vs optimized resume
- One-click copy & download
- 100% private — everything stays on your machine

---

## 🛠 Requirements
- Python 3.9+
- [Ollama](https://ollama.com/download) installed

---

## 🚀 Setup (3 steps)

### 1. Install Ollama + download the AI model
```bash
# Download Ollama from https://ollama.com/download
# Then pull the free AI model (one time, ~4GB):
ollama pull llama3
```

### 2. Clone & install
```bash
git clone https://github.com/YOUR_USERNAME/jobpilot.git
cd jobpilot
python3 -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 3. Run
```bash
# Terminal 1 — start Ollama
ollama serve

# Terminal 2 — start JobPilot
python app.py
```

Open **http://localhost:5000** in your browser. That's it.

---

## 📁 Project Structure
```
jobpilot/
├── app.py                  # Flask backend
├── requirements.txt
├── templates/
│   └── index.html
└── static/
    ├── css/style.css
    └── js/app.js
```

---

## 🔄 Want to use a different model?
```bash
# Faster, smaller (recommended for older machines)
ollama pull mistral

# Then run with:
OLLAMA_MODEL=mistral python app.py
```

---

## 📄 License
MIT — free to use, modify, and distribute.

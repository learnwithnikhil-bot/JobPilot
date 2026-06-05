import os
import json
import re
from flask import Flask, request, jsonify, render_template
import ollama

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")

# ── File extraction ───────────────────────────────────────────────────

def extract_pdf(file_bytes):
    import fitz
    text = ""
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text() + "\n"
    return text.strip()

def extract_docx(file_bytes):
    import docx, io
    doc = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

# ── Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    name = file.filename.lower()
    data = file.read()

    try:
        if name.endswith(".pdf"):
            text = extract_pdf(data)
        elif name.endswith(".docx") or name.endswith(".doc"):
            text = extract_docx(data)
        elif name.endswith(".txt"):
            text = data.decode("utf-8", errors="ignore")
        else:
            return jsonify({"error": "Use PDF, DOCX, or TXT"}), 400

        if not text or len(text.strip()) < 20:
            return jsonify({"error": "Could not extract text — try pasting manually"}), 400

        return jsonify({"text": text.strip()})
    except Exception as e:
        return jsonify({"error": f"File read failed: {e}"}), 500

@app.route("/health", methods=["GET"])
def health():
    """Check if Ollama is running and model is available."""
    try:
        models = ollama.list()
        available = [m.model for m in models.models]
        has_model = any(OLLAMA_MODEL in m for m in available)
        return jsonify({
            "ollama": "running",
            "model": OLLAMA_MODEL,
            "model_ready": has_model,
            "available_models": available
        })
    except Exception as e:
        return jsonify({"ollama": "not running", "error": str(e)}), 503

@app.route("/optimize", methods=["POST"])
def optimize():
    data       = request.get_json()
    resume     = (data.get("resume") or "").strip()
    jd         = (data.get("job_description") or "").strip()
    role       = (data.get("target_role") or "the target role").strip()
    experience = data.get("experience", "mid")

    if len(resume) < 50:
        return jsonify({"error": "Resume too short or missing"}), 400
    if len(jd) < 50:
        return jsonify({"error": "Job description too short or missing"}), 400

    exp_map = {
        "entry":  "entry-level (0-2 years)",
        "mid":    "mid-level (3-5 years)",
        "senior": "senior (6-10 years)",
        "staff":  "staff/principal (10+ years)",
    }
    exp_label = exp_map.get(experience, "mid-level")

    prompt = f"""You are an expert ATS resume optimizer. Analyze the resume against the job description and return ONLY a valid JSON object. No markdown, no explanation, no extra text — just the raw JSON.

Return exactly this structure:
{{
  "ats_score_before": 45,
  "ats_score_after": 82,
  "job_title": "job title from JD",
  "keywords_added": ["keyword1", "keyword2", "keyword3"],
  "keywords_missing": ["missing1", "missing2"],
  "keywords_present": ["present1", "present2"],
  "optimized_resume": "full rewritten resume as plain text",
  "changes": [
    {{"type": "keyword",   "title": "Added missing keywords",      "detail": "one sentence explaining what was added"}},
    {{"type": "bullet",    "title": "Strengthened impact bullets",  "detail": "one sentence explaining rewrites"}},
    {{"type": "structure", "title": "Reordered skills section",     "detail": "one sentence explaining restructure"}},
    {{"type": "tone",      "title": "Adjusted seniority tone",      "detail": "one sentence explaining tone changes"}}
  ]
}}

Rules:
- NEVER invent experience, education, or skills not in the original resume
- Naturally weave missing JD keywords into existing bullets where truthful
- Rewrite weak bullets with strong action verbs and quantified results where possible
- Add a 2-3 sentence professional summary at the top targeting this role
- Keep formatting ATS-friendly: no tables, no columns, plain text only
- ats_score_before and ats_score_after are integers 0-100

TARGET ROLE: {role} ({exp_label})

CURRENT RESUME:
{resume[:5000]}

JOB DESCRIPTION:
{jd[:3000]}

Return ONLY the JSON object:"""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_predict": 3000}
        )
        raw = response["message"]["content"].strip()

        # Extract JSON robustly
        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            return jsonify({"error": "Model returned unexpected output. Try again."}), 500

        result = json.loads(match.group(0))
        return jsonify(result)

    except ollama.ResponseError as e:
        if "not found" in str(e).lower():
            return jsonify({
                "error": f"Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}"
            }), 503
        return jsonify({"error": f"Ollama error: {e}"}), 500
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse model response. Try again."}), 500
    except Exception as e:
        return jsonify({"error": f"Optimization failed: {e}"}), 500

if __name__ == "__main__":
    print("\n🚀 JobPilot is running!")
    print("   Open http://localhost:5000 in your browser\n")
    print(f"   Using model: {OLLAMA_MODEL}")
    print("   Make sure Ollama is running: ollama serve\n")
    app.run(debug=True, port=5001)

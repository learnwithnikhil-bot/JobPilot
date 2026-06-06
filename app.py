import os
import json
import re
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

GROQ_MODEL = "llama-3.3-70b-versatile"

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
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return jsonify({"status": "no_key"}), 200
    return jsonify({"status": "ready", "model": GROQ_MODEL})

@app.route("/optimize", methods=["POST"])
def optimize():
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return jsonify({"error": "GROQ_API_KEY not set."}), 503

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
        "entry": "entry-level (0-2 years)", "mid": "mid-level (3-5 years)",
        "senior": "senior (6-10 years)", "staff": "staff/principal (10+ years)",
    }

    prompt = f"""You are an expert ATS resume optimizer. Analyze the resume against the job description and return ONLY a valid JSON object. No markdown fences, no explanation, just raw JSON.

Return exactly this structure:
{{
  "ats_score_before": 45,
  "ats_score_after": 82,
  "job_title": "extracted job title from JD",
  "keywords_added": ["keyword1", "keyword2", "keyword3"],
  "keywords_missing": ["missing1", "missing2"],
  "keywords_present": ["present1", "present2"],
  "optimized_resume": "full rewritten resume as plain text",
  "changes": [
    {{"type": "keyword",   "title": "Added missing keywords",     "detail": "one sentence"}},
    {{"type": "bullet",    "title": "Strengthened impact bullets", "detail": "one sentence"}},
    {{"type": "structure", "title": "Reordered skills section",    "detail": "one sentence"}},
    {{"type": "tone",      "title": "Adjusted seniority tone",     "detail": "one sentence"}}
  ]
}}

Rules:
- NEVER invent experience, education, or skills not in the original
- Weave missing JD keywords into existing bullets where truthful
- Rewrite weak bullets with strong action verbs and quantified results
- Add a 2-3 sentence professional summary targeting this specific role
- ATS-friendly formatting: no tables, no columns, plain text only
- ats_score_before and ats_score_after are integers 0-100

TARGET ROLE: {role} ({exp_map.get(experience, 'mid-level')})

CURRENT RESUME:
{resume[:5000]}

JOB DESCRIPTION:
{jd[:3000]}

Return ONLY the JSON:"""

    try:
        client   = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        raw = re.sub(r'```json|```', '', raw).strip()

        # Extract JSON object
        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            return jsonify({"error": "Model returned unexpected output. Try again."}), 500

        # Fix invalid control characters before parsing
        json_str = match.group(0)
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', json_str)

        result = json.loads(json_str)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Optimization failed: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🚀 JobPilot running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

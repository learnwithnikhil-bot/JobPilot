import os
import json
import re
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Database ──────────────────────────────────────────────────────────

def get_db():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception:
        return None

def init_db():
    conn = get_db()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    id VARCHAR(12) PRIMARY KEY,
                    job_title TEXT,
                    target_role TEXT,
                    ats_score_before INT,
                    ats_score_after INT,
                    keywords_added TEXT,
                    keywords_present TEXT,
                    keywords_missing TEXT,
                    optimized_resume TEXT,
                    changes TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    except Exception as e:
        print(f"DB init error: {e}")
    finally:
        conn.close()

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

@app.route("/r/<share_id>")
def shared_result(share_id):
    conn = get_db()
    if not conn:
        return "Database not configured", 503
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM results WHERE id = %s", (share_id,))
            row = cur.fetchone()
        if not row:
            return render_template("404.html"), 404
        return render_template("share.html", result=row)
    except Exception as e:
        return f"Error: {e}", 500
    finally:
        conn.close()

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

@app.route("/share", methods=["POST"])
def save_share():
    conn = get_db()
    if not conn:
        return jsonify({"error": "Database not available"}), 503

    data = request.get_json()
    share_id = uuid.uuid4().hex[:12]

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO results
                (id, job_title, target_role, ats_score_before, ats_score_after,
                 keywords_added, keywords_present, keywords_missing,
                 optimized_resume, changes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                share_id,
                data.get("job_title", ""),
                data.get("target_role", ""),
                int(data.get("ats_score_before", 0)),
                int(data.get("ats_score_after", 0)),
                json.dumps(data.get("keywords_added", [])),
                json.dumps(data.get("keywords_present", [])),
                json.dumps(data.get("keywords_missing", [])),
                data.get("optimized_resume", ""),
                json.dumps(data.get("changes", []))
            ))
        conn.commit()
        base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", request.host)
        scheme = "https" if "railway" in base_url else request.scheme
        share_url = f"{scheme}://{base_url}/r/{share_id}"
        return jsonify({"share_url": share_url, "share_id": share_id})
    except Exception as e:
        return jsonify({"error": f"Could not save: {e}"}), 500
    finally:
        conn.close()

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
        raw = re.sub(r'```json|```', '', raw).strip()
        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            return jsonify({"error": "Model returned unexpected output. Try again."}), 500
        json_str = match.group(0)
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', json_str)
        result = json.loads(json_str)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Optimization failed: {str(e)}"}), 500

# Init DB on startup
with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🚀 JobPilot running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

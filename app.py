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


@app.route("/optimize-linkedin", methods=["POST"])
def optimize_linkedin():
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return jsonify({"error": "GROQ_API_KEY not set."}), 503

    data    = request.get_json()
    profile = (data.get("profile") or "").strip()
    role    = (data.get("target_role") or "the target role").strip()
    industry = data.get("industry", "tech")

    if len(profile) < 50:
        return jsonify({"error": "Profile text too short — paste more of your LinkedIn profile"}), 400

    prompt = f"""You are an expert LinkedIn profile optimizer and personal branding coach. Analyze the LinkedIn profile and return ONLY a valid JSON object. No markdown fences, no explanation, just raw JSON.

Return exactly this structure:
{{
  "score_before": 45,
  "score_after": 88,
  "target_role": "{role}",
  "headline": {{
    "original": "current headline from profile",
    "optimized": "powerful new headline targeting {role}"
  }},
  "about": {{
    "original": "current about section",
    "optimized": "compelling new about section (3-4 paragraphs, keyword-rich, first person)"
  }},
  "experience_bullets": [
    {{
      "company": "company name",
      "original": "weak original bullet or description",
      "optimized": "strong rewritten bullet with metrics and impact"
    }}
  ],
  "skills_to_add": ["skill1", "skill2", "skill3", "skill4", "skill5"],
  "recommendations": [
    {{"type": "headline", "tip": "specific actionable tip"}},
    {{"type": "about", "tip": "specific actionable tip"}},
    {{"type": "activity", "tip": "specific actionable tip"}},
    {{"type": "network", "tip": "specific actionable tip"}}
  ]
}}

Rules:
- score_before and score_after are integers 0-100 representing LinkedIn profile strength
- headline must be under 220 characters, keyword-rich, attention-grabbing
- about section must start with a hook, include keywords for {role} in {industry} industry
- rewrite at least 2-3 experience bullet points from the profile
- skills_to_add are missing but relevant skills for {role}
- recommendations are specific, actionable tips (not generic advice)
- NEVER invent job titles, companies, or dates not in the original profile

LINKEDIN PROFILE:
{profile[:5000]}

TARGET ROLE: {role} ({industry} industry)

Return ONLY the JSON:"""

    try:
        client   = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{{"role": "user", "content": prompt}}],
            temperature=0.3,
            max_tokens=3000,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'```json|```', '', raw).strip()
        match = re.search(r'\{{[\s\S]*\}}', raw)
        if not match:
            return jsonify({{"error": "Model returned unexpected output. Try again."}}), 500
        json_str = match.group(0)
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', json_str)
        result = json.loads(json_str)
        return jsonify(result)
    except Exception as e:
        return jsonify({{"error": f"Optimization failed: {{str(e)}}"}}), 500


@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    """Generate PDF using only Python stdlib — no external dependencies."""
    import io, struct, zlib, time
    from flask import make_response

    data      = request.get_json(force=True, silent=True) or {}
    resume    = (data.get("resume") or "").strip()
    job_title = (data.get("job_title") or "Resume").strip()

    if not resume:
        return jsonify({"error": "No resume content"}), 400

    SECTION_KEYWORDS = [
        'EXPERIENCE','EDUCATION','SKILLS','SUMMARY','PROFESSIONAL',
        'TECHNICAL','CERTIFICATIONS','PROJECTS','AWARDS','OBJECTIVE',
        'WORK HISTORY','EMPLOYMENT','PUBLICATIONS'
    ]

    def is_section(line):
        u = line.upper().strip()
        return (u == u and u.replace(' ','').isalpha() and len(u) > 2 and u == line.strip().upper())                or any(u.startswith(k) for k in SECTION_KEYWORDS)

    # ── Build HTML then convert to PDF via weasyprint if available,
    #    otherwise return a well-formatted HTML file the user can print-to-PDF
    lines = resume.split("\n")
    html_lines = []
    first = True
    contact_done = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        esc  = line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

        if not line:
            i += 1
            continue

        if first:
            html_lines.append(f'<h1 class="name">{esc}</h1>')
            first = False
            i += 1
            # contact lines
            while i < len(lines):
                cl = lines[i].strip()
                if not cl or is_section(cl): break
                ec = cl.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                html_lines.append(f'<p class="contact">{ec}</p>')
                i += 1
            html_lines.append('<hr class="name-divider"/>')
            continue

        if is_section(line):
            html_lines.append(f'<h2 class="section">{esc}</h2>')
            i += 1
            continue

        if line[:2] in ('- ','• ','* ','· '):
            html_lines.append(f'<p class="bullet">• {esc[2:]}</p>')
            i += 1
            continue

        html_lines.append(f'<p class="body">{esc}</p>')
        i += 1

    safe_job = re.sub(r"[^a-zA-Z0-9_-]", "_", job_title)[:40]
    body_html = "\n".join(html_lines)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{safe_job}</title>
<style>
  @page {{ size: letter; margin: 0.75in; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 10pt; color: #222; line-height: 1.5; }}
  .name {{ font-size: 22pt; font-weight: 700; color: #1a1a1a; margin-bottom: 3px; }}
  .contact {{ font-size: 9pt; color: #555; margin-bottom: 2px; }}
  .name-divider {{ border: none; border-top: 2px solid #534AB7; margin: 10px 0 14px; }}
  .section {{ font-size: 10pt; font-weight: 700; color: #534AB7; text-transform: uppercase;
              letter-spacing: 0.08em; margin-top: 14px; margin-bottom: 4px;
              border-bottom: 1px solid #e0e0e0; padding-bottom: 3px; }}
  .bullet {{ font-size: 10pt; color: #333; padding-left: 14px; margin-bottom: 3px; }}
  .body {{ font-size: 10pt; color: #222; margin-bottom: 3px; }}
  .print-note {{ display: none; }}
  @media screen {{
    body {{ max-width: 750px; margin: 40px auto; padding: 40px; background: #fff;
            box-shadow: 0 2px 20px rgba(0,0,0,0.1); border-radius: 4px; }}
    .print-note {{ display: block; background: #534AB7; color: #fff; padding: 12px 16px;
                   border-radius: 6px; font-size: 13px; text-align: center; margin-bottom: 24px; }}
  }}
</style>
</head>
<body>
<div class="print-note">
  📄 To save as PDF: Press <strong>Ctrl+P</strong> (or Cmd+P on Mac) → Select "Save as PDF" → Click Save
</div>
{body_html}
</body>
</html>"""

    response = make_response(html)
    response.headers['Content-Type']        = 'text/html; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{safe_job}_resume.html"'
    return response

# Init DB on startup
with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🚀 JobPilot running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

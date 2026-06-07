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
        # Remove all control characters except tab and newline at top level
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', json_str)
        # Fix unescaped newlines/tabs inside JSON string values
        def fix_json_string(m):
            s = m.group(0)
            s = s.replace('\n', '\\n').replace('\r', ' ').replace('\t', ' ')
            return s
        json_str = re.sub(r'(?s)"(.*?)"', fix_json_string, json_str)
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            # Last resort: use ast literal eval after sanitizing
            json_str2 = re.sub(r'[\x00-\x1f\x7f]', ' ', match.group(0))
            result = json.loads(json_str2)
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
    import io
    from flask import make_response

    data      = request.get_json(force=True, silent=True) or {}
    resume    = (data.get("resume") or "").strip()
    job_title = (data.get("job_title") or "Resume").strip()
    template  = data.get("template", "classic")

    if not resume:
        return jsonify({"error": "No resume content"}), 400

    SECTION_KEYWORDS = [
        'EXPERIENCE','EDUCATION','SKILLS','SUMMARY','PROFESSIONAL SUMMARY',
        'TECHNICAL SKILLS','CERTIFICATIONS','PROJECTS','AWARDS','OBJECTIVE',
        'WORK HISTORY','EMPLOYMENT','PUBLICATIONS','VOLUNTEER','LANGUAGES',
        'INTERESTS','ACHIEVEMENTS'
    ]

    def is_section_header(line):
        u = line.strip().upper()
        if not u or len(u) < 2:
            return False
        return (line.strip() == line.strip().upper() and len(u) > 2 and not u.startswith('-') and not u.startswith('•')) \
               or any(u.startswith(k) for k in SECTION_KEYWORDS)

    def esc(text):
        return (text or "").replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    # Parse resume into structured parts
    lines  = resume.split("\n")
    name   = ""
    contacts = []
    sections = []  # list of {title, items: [{type: "bullet"|"text"|"job", content, company, date}]}

    i = 0
    # First line = name
    if lines:
        name = lines[0].strip()
        i = 1

    # Contact lines (until first section header or blank+section)
    while i < len(lines):
        l = lines[i].strip()
        if not l:
            i += 1
            # peek ahead
            if i < len(lines) and is_section_header(lines[i].strip()):
                break
            continue
        if is_section_header(l):
            break
        contacts.append(l)
        i += 1

    # Parse remaining into sections
    current_section = None
    while i < len(lines):
        l = lines[i].strip()
        if not l:
            i += 1
            continue

        if is_section_header(l):
            if current_section:
                sections.append(current_section)
            current_section = {"title": l, "items": []}
            i += 1
            continue

        if current_section is None:
            current_section = {"title": "EXPERIENCE", "items": []}

        if l.startswith(('- ','• ','* ','· ')):
            current_section["items"].append({"type": "bullet", "content": l[2:].strip()})
        else:
            current_section["items"].append({"type": "text", "content": l})
        i += 1

    if current_section:
        sections.append(current_section)

    # ── Template styles ──────────────────────────────────────────────
    templates = {
        "classic": {
            "accent":      "#2C3E50",
            "accent_light":"#ECF0F1",
            "header_bg":   "#2C3E50",
            "header_text": "#FFFFFF",
            "section_border": "#2C3E50",
            "bullet_color": "#2C3E50",
            "font":        "'Georgia', 'Times New Roman', serif",
            "name_size":   "28px",
        },
        "modern": {
            "accent":      "#534AB7",
            "accent_light":"#EEEDFE",
            "header_bg":   "#534AB7",
            "header_text": "#FFFFFF",
            "section_border": "#534AB7",
            "bullet_color": "#534AB7",
            "font":        "'Helvetica Neue', 'Arial', sans-serif",
            "name_size":   "30px",
        },
        "minimal": {
            "accent":      "#1a1a1a",
            "accent_light":"#f5f5f5",
            "header_bg":   "#FFFFFF",
            "header_text": "#1a1a1a",
            "section_border": "#1a1a1a",
            "bullet_color": "#555",
            "font":        "'Arial', sans-serif",
            "name_size":   "26px",
        },
        "executive": {
            "accent":      "#0F6E56",
            "accent_light":"#E1F5EE",
            "header_bg":   "#0F6E56",
            "header_text": "#FFFFFF",
            "section_border": "#0F6E56",
            "bullet_color": "#0F6E56",
            "font":        "'Garamond','Georgia',serif",
            "name_size":   "32px",
        },
    }

    t = templates.get(template, templates["modern"])

    # Build contacts HTML
    contact_html = " &nbsp;|&nbsp; ".join(esc(c) for c in contacts[:5]) if contacts else ""

    # Build sections HTML
    sections_html = ""
    for sec in sections:
        items_html = ""
        j = 0
        items = sec["items"]
        while j < len(items):
            item = items[j]
            if item["type"] == "text":
                content = esc(item["content"])
                # Check if next items are bullets (job entry pattern)
                bullets = []
                k = j + 1
                while k < len(items) and items[k]["type"] == "bullet":
                    bullets.append(esc(items[k]["content"]))
                    k += 1

                if bullets:
                    # This text line is a job title/company line
                    items_html += f'''
                    <div class="job-entry">
                        <div class="job-header">{content}</div>
                        <ul class="bullet-list">
                            {"".join(f'<li>{b}</li>' for b in bullets)}
                        </ul>
                    </div>'''
                    j = k
                else:
                    items_html += f'<p class="body-text">{content}</p>'
                    j += 1
            elif item["type"] == "bullet":
                items_html += f'<ul class="bullet-list"><li>{esc(item["content"])}</li></ul>'
                j += 1
            else:
                j += 1

        sections_html += f'''
        <div class="section">
            <div class="section-header">
                <h2>{esc(sec["title"])}</h2>
                <div class="section-line"></div>
            </div>
            <div class="section-body">{items_html}</div>
        </div>'''

    header_style = f'background:{t["header_bg"]};color:{t["header_text"]};' if t["header_bg"] != "#FFFFFF" else f'border-bottom:3px solid {t["accent"]};padding-bottom:16px;'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{esc(name)} — Resume</title>
<style>
  @page {{ size: letter; margin: 0.6in 0.7in; }}
  @media print {{
    .print-bar {{ display: none !important; }}
    body {{ margin: 0; padding: 0; background: white; }}
    .resume {{ box-shadow: none; border-radius: 0; max-width: 100%; }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: {t["font"]};
    font-size: 10.5pt;
    color: #222;
    background: #f0f0f0;
    line-height: 1.5;
  }}

  /* Print bar */
  .print-bar {{
    background: {t["accent"]};
    color: white;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .print-bar p {{ font-size: 13px; opacity: 0.95; }}
  .print-bar strong {{ font-size: 14px; }}
  .print-actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .print-btn {{
    padding: 7px 18px; border: 2px solid white; border-radius: 6px;
    background: white; color: {t["accent"]}; font-size: 13px;
    font-weight: 700; cursor: pointer; transition: all 0.15s;
  }}
  .print-btn:hover {{ background: {t["accent"]}; color: white; }}
  .template-select {{
    padding: 6px 10px; border: 2px solid white; border-radius: 6px;
    background: transparent; color: white; font-size: 13px; cursor: pointer;
  }}
  .template-select option {{ color: #222; background: white; }}

  /* Resume */
  .resume {{
    max-width: 780px;
    margin: 24px auto;
    background: white;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    border-radius: 4px;
    overflow: hidden;
  }}

  /* Header */
  .resume-header {{
    {header_style}
    padding: 28px 36px 24px;
  }}
  .resume-header h1 {{
    font-size: {t["name_size"]};
    font-weight: 700;
    letter-spacing: -0.5px;
    margin-bottom: 10px;
    line-height: 1.1;
  }}
  .contact-line {{
    font-size: 9.5pt;
    opacity: 0.88;
    line-height: 1.6;
  }}

  /* Body */
  .resume-body {{ padding: 24px 36px 32px; }}

  /* Sections */
  .section {{ margin-bottom: 22px; }}
  .section-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }}
  .section-header h2 {{
    font-size: 10pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: {t["accent"]};
    white-space: nowrap;
  }}
  .section-line {{
    flex: 1;
    height: 1.5px;
    background: {t["accent"]};
    opacity: 0.25;
  }}

  /* Job entries */
  .job-entry {{ margin-bottom: 14px; }}
  .job-header {{
    font-size: 10.5pt;
    font-weight: 700;
    color: #1a1a1a;
    margin-bottom: 5px;
    line-height: 1.4;
  }}

  /* Bullets */
  .bullet-list {{
    list-style: none;
    padding-left: 0;
    margin-bottom: 4px;
  }}
  .bullet-list li {{
    position: relative;
    padding-left: 16px;
    margin-bottom: 4px;
    font-size: 10pt;
    color: #333;
    line-height: 1.55;
  }}
  .bullet-list li::before {{
    content: "▸";
    position: absolute;
    left: 0;
    color: {t["bullet_color"]};
    font-size: 9pt;
    top: 1px;
  }}

  /* Body text */
  .body-text {{
    font-size: 10pt;
    color: #333;
    margin-bottom: 6px;
    line-height: 1.6;
  }}
</style>
</head>
<body>

<div class="print-bar">
  <div>
    <strong>📄 {esc(name)} — Resume</strong>
    <p>To save as PDF: <strong>Cmd+P → Save as PDF → Save</strong></p>
  </div>
  <div class="print-actions">
    <select class="template-select" onchange="changeTemplate(this.value)">
      <option value="modern" {'selected' if template=='modern' else ''}>Modern (Purple)</option>
      <option value="classic" {'selected' if template=='classic' else ''}>Classic (Navy)</option>
      <option value="executive" {'selected' if template=='executive' else ''}>Executive (Green)</option>
      <option value="minimal" {'selected' if template=='minimal' else ''}>Minimal (Black)</option>
    </select>
    <button class="print-btn" onclick="window.print()">🖨 Print / Save PDF</button>
  </div>
</div>

<div class="resume">
  <div class="resume-header">
    <h1>{esc(name)}</h1>
    {f'<div class="contact-line">{contact_html}</div>' if contact_html else ""}
  </div>
  <div class="resume-body">
    {sections_html}
  </div>
</div>

<script>
function changeTemplate(t) {{
  const params = new URLSearchParams(window.location.search);
  params.set('template', t);
  // Re-request with new template
  const data = JSON.parse(sessionStorage.getItem('resumeData') || '{{}}');
  data.template = t;
  fetch('/download-pdf', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(data)
  }}).then(r => r.blob()).then(blob => {{
    const url = URL.createObjectURL(blob);
    document.open();
    document.write('');
    window.location.href = url;
  }});
}}
</script>

</body>
</html>"""

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name or job_title)[:40]
    filename  = f"{safe_name}_resume.html"

    response = make_response(html)
    response.headers['Content-Type']        = 'text/html; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"' 
    return response

# Init DB on startup
with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🚀 JobPilot running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

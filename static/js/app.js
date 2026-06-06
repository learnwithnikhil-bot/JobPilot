let resumeInput, jdInput, runBtn;
let aiReady = false;

document.addEventListener('DOMContentLoaded', () => {
  resumeInput = document.getElementById('resume-input');
  jdInput     = document.getElementById('jd-input');
  runBtn      = document.getElementById('run-btn');

  resumeInput.addEventListener('input', () => {
    document.getElementById('resume-chars').textContent =
      resumeInput.value.length.toLocaleString() + ' chars';
    checkReady();
  });
  jdInput.addEventListener('input', () => {
    document.getElementById('jd-chars').textContent =
      jdInput.value.length.toLocaleString() + ' chars';
    checkReady();
  });

  checkHealth();
});

// ── Health check ──────────────────────────────────────────────────────
async function checkHealth() {
  const dot    = document.getElementById('status-dot');
  const label  = document.getElementById('status-label');
  const model  = document.getElementById('status-model');
  const banner = document.getElementById('setup-banner');

  dot.className   = 'status-dot';
  label.textContent = 'Checking...';
  model.textContent = '';

  try {
    const res  = await fetch('/health');
    const data = await res.json();

    if (data.status === 'ready') {
      dot.className     = 'status-dot ok';
      label.textContent = 'Groq AI ready';
      model.textContent = '· ' + data.model;
      banner.style.display = 'none';
      aiReady = true;
      checkReady();
    } else if (data.status === 'no_key') {
      dot.className     = 'status-dot err';
      label.textContent = 'API key missing';
      banner.style.display = 'block';
      aiReady = false;
    } else {
      throw new Error();
    }
  } catch {
    dot.className     = 'status-dot err';
    label.textContent = 'Connection failed';
    banner.style.display = 'block';
    aiReady = false;
  }
}

function checkReady() {
  const ok = aiReady &&
             resumeInput.value.trim().length > 50 &&
             jdInput.value.trim().length > 50;
  runBtn.disabled = !ok;
  updateSteps();
}

function updateSteps() {
  const hasResume = resumeInput.value.trim().length > 50;
  const hasJD     = jdInput.value.trim().length > 50;
  ['s1','s2'].forEach((id, i) => {
    const done = i === 0 ? hasResume : hasJD;
    const el   = document.getElementById(id);
    el.className   = 'step-circle ' + (done ? 'done' : 'active');
    el.textContent = done ? '✓' : (i + 1);
  });
}

// ── File upload ───────────────────────────────────────────────────────
function handleDragOver(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.add('drag-over');
}
function handleDragLeave() {
  document.getElementById('upload-zone').classList.remove('drag-over');
}
function handleDrop(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
}
function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) uploadFile(file);
}

function setUploadState(state, filename) {
  const zone = document.getElementById('upload-zone');
  const text = document.getElementById('upload-text');
  const hint = document.getElementById('upload-hint');
  if (state === 'loading') {
    zone.classList.remove('has-file');
    text.innerHTML   = '<span class="upload-spinner"></span>Reading ' + filename + '...';
    hint.textContent = 'Extracting text';
  } else if (state === 'done') {
    zone.classList.add('has-file');
    text.innerHTML   = '✅ <strong>' + filename + '</strong> loaded';
    hint.textContent = 'Click to replace';
  } else {
    zone.classList.remove('has-file');
    text.innerHTML   = '❌ Could not read — try pasting manually';
    hint.textContent = filename;
  }
}

async function uploadFile(file) {
  setUploadState('loading', file.name);
  const form = new FormData();
  form.append('file', file);
  try {
    const res  = await fetch('/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Upload failed');
    resumeInput.value = data.text;
    resumeInput.dispatchEvent(new Event('input'));
    setUploadState('done', file.name);
  } catch (err) {
    setUploadState('error', file.name);
    showError(err.message);
  }
}

// ── Loading animation ─────────────────────────────────────────────────
let loadingInterval, progressInterval;

function startLoading() {
  const steps = ['ls1','ls2','ls3','ls4','ls5'];
  let i = 0;
  steps.forEach(id => { document.getElementById(id).className = 'lstep'; });
  document.getElementById(steps[0]).className = 'lstep active';

  loadingInterval = setInterval(() => {
    if (i < steps.length - 1) {
      document.getElementById(steps[i]).className = 'lstep done';
      i++;
      document.getElementById(steps[i]).className = 'lstep active';
    }
  }, 2200);

  // Animate progress bar
  const fill = document.getElementById('progress-fill');
  let progress = 0;
  fill.style.width = '0%';
  progressInterval = setInterval(() => {
    progress += (95 - progress) * 0.04;
    fill.style.width = Math.min(progress, 94) + '%';
  }, 300);
}

function stopLoading() {
  clearInterval(loadingInterval);
  clearInterval(progressInterval);
  document.getElementById('progress-fill').style.width = '100%';
  ['ls1','ls2','ls3','ls4','ls5'].forEach(id => {
    document.getElementById(id).className = 'lstep done';
  });
}

// ── Optimize ──────────────────────────────────────────────────────────
async function optimize() {
  const resume = resumeInput.value.trim();
  const jd     = jdInput.value.trim();
  const role   = document.getElementById('target-role').value.trim() || 'the target role';
  const exp    = document.getElementById('experience').value;

  hideError();
  document.getElementById('input-section').style.display = 'none';
  document.getElementById('loading').style.display       = 'block';
  document.getElementById('results').style.display       = 'none';
  startLoading();

  try {
    const res  = await fetch('/optimize', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ resume, job_description: jd, target_role: role, experience: exp })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Optimization failed');
    stopLoading();
    renderResults(data, role, resume);
  } catch (err) {
    stopLoading();
    document.getElementById('loading').style.display       = 'none';
    document.getElementById('input-section').style.display = 'block';
    showError(err.message);
  }
}

// ── Score ring SVG ────────────────────────────────────────────────────
function scoreRing(score, color, label, delta) {
  const r = 30, cx = 36, cy = 36;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  const deltaHtml = delta !== null
    ? `<div class="score-delta" style="color:${color};">+${delta} pts</div>` : '';
  return `
    <div class="score-card">
      <div class="score-ring">
        <svg width="72" height="72" viewBox="0 0 72 72">
          <circle class="score-ring-bg" cx="${cx}" cy="${cy}" r="${r}"/>
          <circle class="score-ring-fill" cx="${cx}" cy="${cy}" r="${r}"
            stroke="${color}"
            stroke-dasharray="${circ}"
            stroke-dashoffset="${offset}"
          />
        </svg>
        <div class="score-num" style="color:${color};">${score}</div>
      </div>
      <div class="score-lbl">${label}</div>
      ${deltaHtml}
    </div>`;
}

// ── Render results ────────────────────────────────────────────────────
function renderResults(r, role, originalResume) {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('s3').className   = 'step-circle done';
  document.getElementById('s3').textContent = '✓';

  const delta      = r.ats_score_after - r.ats_score_before;
  const afterColor = r.ats_score_after >= 80 ? '#3B6D11' : r.ats_score_after >= 60 ? '#BA7517' : '#A32D2D';
  const beforeColor = '#aaa';

  const typeIcon = { keyword: '🔑', bullet: '✍️', structure: '📐', tone: '🎯' };
  const typeBg   = { keyword: '#EEEDFE', bullet: '#E1F5EE', structure: '#E6F1FB', tone: '#FAEEDA' };

  const changesHtml = (r.changes || []).map(c => `
    <div class="change-item">
      <div class="change-icon" style="background:${typeBg[c.type] || '#F1EFE8'};">${typeIcon[c.type] || '✅'}</div>
      <div class="change-body">
        <div class="change-title">${c.title}</div>
        <div class="change-detail">${c.detail}</div>
      </div>
    </div>`).join('');

  const kwAdded   = (r.keywords_added   || []).map(k => `<span class="kw kw-added">+ ${k}</span>`).join('');
  const kwMissing = (r.keywords_missing || []).map(k => `<span class="kw kw-missing">✗ ${k}</span>`).join('');
  const kwPresent = (r.keywords_present || []).map(k => `<span class="kw kw-present">✓ ${k}</span>`).join('');

  document.getElementById('results').innerHTML = `
    <div class="r-topbar">
      <div class="r-title">Optimized for <span>${escHtml(r.job_title || role)}</span></div>
      <div class="r-actions">
        <button class="btn-ghost" onclick="copyResume()">📋 Copy resume <span class="copy-feedback" id="copy-fb">Copied!</span></button>
        <button class="btn-ghost" onclick="downloadResume()">⬇ Download .txt</button>
        <button class="btn-solid" onclick="resetApp()">↩ New resume</button>
      </div>
    </div>

    <div class="score-grid">
      ${scoreRing(r.ats_score_before, beforeColor, 'Score before', null)}
      ${scoreRing(r.ats_score_after,  afterColor,  'Score after',  delta)}
      <div class="stat-card">
        <div class="stat-big" style="color:#27500A;">${(r.keywords_added||[]).length}</div>
        <div class="stat-lbl2">Keywords added</div>
      </div>
      <div class="stat-card">
        <div class="stat-big" style="color:${(r.keywords_missing||[]).length > 0 ? '#BA7517' : '#27500A'};">${(r.keywords_missing||[]).length}</div>
        <div class="stat-lbl2">Still missing</div>
      </div>
    </div>

    <div class="kw-section">
      <div class="kw-title">Keyword analysis</div>
      ${kwAdded   ? `<div class="kw-group"><div class="kw-group-label">Added to your resume</div><div class="kw-row">${kwAdded}</div></div>`     : ''}
      ${kwPresent ? `<div class="kw-group"><div class="kw-group-label">Already present</div><div class="kw-row">${kwPresent}</div></div>`         : ''}
      ${kwMissing ? `<div class="kw-group"><div class="kw-group-label">Could not fit naturally</div><div class="kw-row">${kwMissing}</div></div>` : ''}
    </div>

    <div class="resume-grid">
      <div>
        <div class="resume-panel-label" style="color:#888;">📄 Original resume</div>
        <div class="resume-box">${escHtml(originalResume)}</div>
      </div>
      <div>
        <div class="resume-panel-label" style="color:#185FA5;">✨ ATS-optimized resume</div>
        <div class="resume-box optimized">${escHtml(r.optimized_resume || '')}</div>
      </div>
    </div>

    <div class="changes-section">
      <div class="kw-title" style="margin-bottom:14px;">What was changed & why</div>
      ${changesHtml}
    </div>

    <p class="footer-note">
      100% private · your resume never leaves your machine · always review before submitting
    </p>
  `;

  window._optimizedResume = r.optimized_resume || '';
  window._lastResult = r;
  document.getElementById('results').style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Helpers ───────────────────────────────────────────────────────────
function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function copyResume() {
  navigator.clipboard.writeText(window._optimizedResume || '').then(() => {
    const fb = document.getElementById('copy-fb');
    fb.classList.add('show');
    setTimeout(() => fb.classList.remove('show'), 2000);
  });
}
function downloadResume() {
  const blob = new Blob([window._optimizedResume || ''], { type: 'text/plain' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'optimized-resume.txt'; a.click();
}
function resetApp() {
  document.getElementById('results').style.display       = 'none';
  document.getElementById('input-section').style.display = 'block';
  ['s1','s2'].forEach((id,i) => {
    const el = document.getElementById(id);
    el.className   = 'step-circle ' + (i === 0 ? 'active' : 'idle');
    el.textContent = i + 1;
  });
  document.getElementById('s3').className   = 'step-circle idle';
  document.getElementById('s3').textContent = '3';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function showError(msg) {
  const eb = document.getElementById('error-box');
  eb.textContent   = '⚠ ' + msg;
  eb.style.display = 'block';
}
function hideError() {
  document.getElementById('error-box').style.display = 'none';
}

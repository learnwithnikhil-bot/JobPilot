let resumeInput, jdInput, runBtn;
let ollamaReady = false;

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

// ── Ollama health check ───────────────────────────────────────────────
async function checkHealth() {
  const dot   = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  const model = document.getElementById('status-model');
  const banner = document.getElementById('setup-banner');

  dot.className   = 'status-dot';
  label.textContent = 'Checking Ollama...';
  model.textContent = '';

  try {
    const res  = await fetch('/health');
    const data = await res.json();

    if (data.ollama === 'running' && data.model_ready) {
      dot.className     = 'status-dot ok';
      label.textContent = 'Ollama ready';
      model.textContent = '· ' + data.model;
      banner.style.display = 'none';
      ollamaReady = true;
      checkReady();
    } else if (data.ollama === 'running' && !data.model_ready) {
      dot.className     = 'status-dot err';
      label.textContent = 'Model not found';
      model.textContent = '';
      banner.style.display = 'block';
      banner.querySelector('.setup-text').innerHTML =
        `Ollama is running but model <code>${data.model}</code> is not installed. ` +
        `Open a terminal and run: <code>ollama pull ${data.model}</code>`;
      ollamaReady = false;
    } else {
      throw new Error('not running');
    }
  } catch {
    dot.className     = 'status-dot err';
    label.textContent = 'Ollama not running';
    banner.style.display = 'block';
    ollamaReady = false;
  }
}

function checkReady() {
  const ok = ollamaReady &&
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
    el.className  = 'step-num ' + (done ? 'done' : 'active');
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
    text.innerHTML    = '<span class="upload-spinner"></span>Reading ' + filename + '...';
    hint.textContent  = 'Extracting text from file';
  } else if (state === 'done') {
    zone.classList.add('has-file');
    text.innerHTML    = '✅ <strong>' + filename + '</strong> loaded';
    hint.textContent  = 'Click to replace with a different file';
  } else {
    zone.classList.remove('has-file');
    text.innerHTML    = '❌ Could not read file — try pasting manually';
    hint.textContent  = filename;
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
let loadingInterval;
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
  }, 2000);
}
function stopLoading() {
  clearInterval(loadingInterval);
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

// ── Render results ────────────────────────────────────────────────────
function renderResults(r, role, originalResume) {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('s3').className  = 'step-num done';
  document.getElementById('s3').textContent = '✓';

  const delta      = r.ats_score_after - r.ats_score_before;
  const scoreColor = r.ats_score_after >= 80 ? '#27500A' : r.ats_score_after >= 60 ? '#633806' : '#791F1F';
  const typeIcon   = { keyword: '🔑', bullet: '✍️', structure: '📐', tone: '🎯' };

  const changesHtml = (r.changes || []).map(c => `
    <div class="suggestion-item">
      <span class="sug-icon">${typeIcon[c.type] || '✅'}</span>
      <div class="sug-body"><span class="sug-label">${c.title}</span>${c.detail}</div>
    </div>`).join('');

  const kwAdded   = (r.keywords_added   || []).map(k => `<span class="kw kw-added">+ ${k}</span>`).join('');
  const kwMissing = (r.keywords_missing || []).map(k => `<span class="kw kw-missing">✗ ${k}</span>`).join('');
  const kwPresent = (r.keywords_present || []).map(k => `<span class="kw kw-present">✓ ${k}</span>`).join('');

  const resultsEl = document.getElementById('results');
  resultsEl.innerHTML = `
    <div class="results-topbar">
      <span class="results-title">Optimized for: ${escHtml(r.job_title || role)}</span>
      <div class="results-actions">
        <button class="btn-outline" onclick="copyResume()">📋 Copy <span class="copy-feedback" id="copy-fb">Copied!</span></button>
        <button class="btn-outline" onclick="downloadResume()">⬇ Download .txt</button>
        <button class="btn-primary" onclick="resetApp()">↩ Optimize another</button>
      </div>
    </div>
    <div class="score-row">
      <div class="score-card">
        <div class="score-val" style="color:#888;">${r.ats_score_before}<span style="font-size:16px;color:#bbb;">/100</span></div>
        <div class="score-lbl">ATS score before</div>
      </div>
      <div class="score-card">
        <div class="score-val" style="color:${scoreColor};">${r.ats_score_after}<span style="font-size:15px;">/100</span></div>
        <div class="score-lbl">ATS score after</div>
        <div class="score-delta" style="color:${scoreColor};">+${delta} improvement</div>
      </div>
      <div class="score-card">
        <div class="score-val" style="color:#27500A;">${(r.keywords_added||[]).length}</div>
        <div class="score-lbl">Keywords added</div>
      </div>
      <div class="score-card">
        <div class="score-val" style="color:${(r.keywords_missing||[]).length > 0 ? '#633806' : '#27500A'};">${(r.keywords_missing||[]).length}</div>
        <div class="score-lbl">Still missing</div>
      </div>
    </div>
    <div class="kw-section">
      <div class="kw-title">Keyword analysis</div>
      ${kwAdded   ? `<div class="kw-group-label">Added to your resume</div><div class="kw-row">${kwAdded}</div>`     : ''}
      ${kwPresent ? `<div class="kw-group-label">Already present</div><div class="kw-row">${kwPresent}</div>`         : ''}
      ${kwMissing ? `<div class="kw-group-label">Could not fit naturally</div><div class="kw-row">${kwMissing}</div>` : ''}
    </div>
    <div class="results-grid">
      <div>
        <p class="resume-label" style="color:#888;">Original resume</p>
        <div class="resume-box">${escHtml(originalResume)}</div>
      </div>
      <div>
        <p class="resume-label" style="color:#185FA5;">✨ ATS-optimized resume</p>
        <div class="resume-box optimized">${escHtml(r.optimized_resume || '')}</div>
      </div>
    </div>
    <div class="suggestions">
      <div class="kw-title" style="margin-bottom:12px;">What was changed & why</div>
      ${changesHtml}
    </div>
    <p class="footer-note">100% local · your data never leaves your machine · always review before submitting</p>
  `;

  window._optimizedResume = r.optimized_resume || '';
  resultsEl.style.display = 'block';
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
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'optimized-resume.txt';
  a.click();
}
function resetApp() {
  document.getElementById('results').style.display       = 'none';
  document.getElementById('input-section').style.display = 'block';
  ['s1','s2'].forEach((id, i) => {
    const el = document.getElementById(id);
    el.className   = 'step-num ' + (i === 0 ? 'active' : 'idle');
    el.textContent = i + 1;
  });
  document.getElementById('s3').className   = 'step-num idle';
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

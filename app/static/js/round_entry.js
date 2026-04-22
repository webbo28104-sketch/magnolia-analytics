/**
 * Magnolia Analytics — Round Entry (shot-by-shot)
 */

// ── Module-level tee-shot SVG state ──────────────────────────────────────────
var _tsDir = null;   // 'fairway' | 'left' | 'right' | null
var _tsMod = null;   // 'bunker' | 'penalty' | null
var _tsSyncUI = null;

// ── Shot list state ───────────────────────────────────────────────────────────
var _shots    = [];
var _penalties = 0;
var _editIdx  = null;   // null = adding new, integer = editing existing
var _activeType = null; // currently open panel type
var _appMissed  = false;

// ── Global multi-pill delegated click handler ─────────────────────────────────
// Handles groups: miss-dir, app-miss-dir, lie-type, app-lie, atg-lie, tee-mod
document.addEventListener('click', function(e) {
  const pill = e.target.closest('.he-pill--multi');
  if (!pill) return;
  const group = pill.dataset.group;
  const value = pill.dataset.value;

  if (group === 'miss-dir' || group === 'app-miss-dir') {
    if (pill.classList.contains('is-active')) {
      pill.classList.remove('is-active');
    } else {
      const conflict = { left: 'right', right: 'left', long: 'short', short: 'long' }[value];
      const container = pill.closest('.he-pills');
      if (conflict && container) {
        container.querySelectorAll(`.he-pill--multi[data-value="${conflict}"]`)
                 .forEach(p => p.classList.remove('is-active'));
      }
      pill.classList.add('is-active');
    }

  } else if (group === 'lie-type' || group === 'app-lie' || group === 'atg-lie') {
    pill.classList.toggle('is-active');

  } else if (group === 'tee-mod') {
    _tsMod = (_tsMod === value) ? null : value;
    if (_tsMod && _tsDir === 'fairway') _tsDir = null;
    if (_tsSyncUI) _tsSyncUI(true);
    return;
  }

  // Sync hidden input via data-target on the container
  const container = pill.closest('[data-target]');
  if (container) {
    const input = document.getElementById(container.dataset.target);
    if (input) {
      input.value = Array.from(container.querySelectorAll('.he-pill--multi.is-active'))
                         .map(p => p.dataset.value).join(',');
    }
  }
  if (navigator.vibrate) navigator.vibrate(10);
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function reveal(el, show) {
  if (!el) return;
  if (show) el.classList.add('is-visible');
  else      el.classList.remove('is-visible');
}

function getPar() {
  return parseInt(document.getElementById('par-input')?.value) || 4;
}

function getScore() {
  return _shots.length + _penalties;
}

// ── Shot rendering ────────────────────────────────────────────────────────────
function shotTypeLabel(type) {
  return { ott: 'OTT', app: 'App', atg: 'ATG', putt: 'Putt', gimme: 'Gimme' }[type] || type;
}

function shotSummary(shot) {
  switch (shot.type) {
    case 'ott': {
      const parts = [];
      if (shot.direction === 'fairway') parts.push('Fairway');
      else if (shot.direction === 'left') parts.push('Left rough');
      else if (shot.direction === 'right') parts.push('Right rough');
      if (shot.mod === 'bunker') parts.push('Bunker');
      else if (shot.mod === 'penalty') parts.push('Penalty');
      return parts.join(' · ') || 'Tee shot';
    }
    case 'app': {
      const parts = [];
      if (shot.distance) parts.push(shot.distance + 'y');
      if (shot.miss) parts.push('Miss ' + shot.miss.replace(',', '/'));
      if (shot.lie) parts.push(shot.lie.charAt(0).toUpperCase() + shot.lie.slice(1));
      return parts.join(' · ') || 'Approach';
    }
    case 'atg': {
      const parts = [];
      if (shot.distance) parts.push(shot.distance + 'y');
      if (shot.lie) parts.push(shot.lie.charAt(0).toUpperCase() + shot.lie.slice(1));
      return parts.join(' · ') || 'Short game';
    }
    case 'putt':
      return shot.putt_distance ? shot.putt_distance + 'ft' : 'Putt';
    case 'gimme':
      return 'Conceded';
    default:
      return '';
  }
}

function renderShotList() {
  const container = document.getElementById('shot-list');
  if (!container) return;
  if (_shots.length === 0) {
    container.innerHTML = '<div class="he-no-shots">Tap a shot type below to begin</div>';
    return;
  }
  container.innerHTML = _shots.map((shot, i) => `
    <div class="he-shot-row${_editIdx === i ? ' is-editing' : ''}" data-idx="${i}">
      <span class="he-shot-badge he-shot-badge--${shot.type}">${shotTypeLabel(shot.type)}</span>
      <span class="he-shot-summary">${shotSummary(shot)}</span>
      <button type="button" class="he-shot-del" data-del="${i}" aria-label="Remove shot">×</button>
    </div>
  `).join('');
}

function updateScoreDisplay() {
  const score = getScore();
  const par   = getPar();
  const diff  = score - par;
  const el    = document.getElementById('auto-score');
  const lbl   = document.getElementById('score-vs-par');
  if (el) el.textContent = score;
  if (lbl) {
    const texts = { '-3': 'Albatross', '-2': 'Eagle', '-1': 'Birdie', '0': 'Par', '1': 'Bogey', '2': 'Double', '3': 'Triple' };
    lbl.textContent = texts[diff] ?? (diff > 0 ? `+${diff}` : String(diff));
    lbl.className = 'he-score-vs-par' + (diff <= -1 ? ' he-score-vs-par--birdie' : diff === 0 ? ' he-score-vs-par--par' : diff === 1 ? ' he-score-vs-par--bogey' : ' he-score-vs-par--double');
  }
}

// ── State serialisation ───────────────────────────────────────────────────────
function setHidden(name, value) {
  const el = document.querySelector(`#hole-form input[name="${name}"]`);
  if (el) el.value = (value == null) ? '' : value;
}

function saveState() {
  setHidden('shots_json', JSON.stringify(_shots));
  setHidden('score', getScore());
  setHidden('penalties', _penalties);

  // Derive legacy fields from shots for SG calculations
  const ott   = _shots.find(s => s.type === 'ott');
  const apps  = _shots.filter(s => s.type === 'app');
  const atgs  = _shots.filter(s => s.type === 'atg');
  const putts = _shots.filter(s => s.type === 'putt' || s.type === 'gimme');
  const par   = getPar();

  // tee_shot
  if (ott) {
    let val = '';
    if (ott.direction === 'fairway') val = 'fairway';
    else { const p = [ott.mod, ott.direction].filter(Boolean); val = p.join(','); }
    setHidden('tee_shot', val);
  }

  // approach_distance, approach_miss, lie_type, second_shot_distance
  if (par === 5 && apps.length >= 2) {
    setHidden('second_shot_distance', apps[0].distance || '');
    const last = apps[apps.length - 1];
    setHidden('approach_distance', last.distance || '');
    setHidden('approach_miss',     last.miss || '');
    setHidden('lie_type',          last.lie  || '');
  } else if (apps.length) {
    setHidden('approach_distance', apps[0].distance || '');
    setHidden('approach_miss',     apps[0].miss || '');
    setHidden('lie_type',          apps[0].lie  || '');
  }

  // scramble_distance (first ATG), atg_strokes, sand_save
  setHidden('atg_strokes', atgs.length || 0);
  if (atgs.length) {
    setHidden('scramble_distance',  atgs[0].distance || '');
    const bunkerAtg = atgs.find(s => s.lie === 'bunker');
    setHidden('sand_save_attempt',  bunkerAtg ? 'true' : '');
  }

  // GIR → sent via approach_miss being empty = GIR (server recalculates)
  // putts, first_putt_distance
  setHidden('putts', putts.length);
  if (putts.length) setHidden('first_putt_distance', putts[0].putt_distance || '');
}

// ── Panel management ──────────────────────────────────────────────────────────
function openPanel(type, editing) {
  _activeType = type;
  document.querySelectorAll('.he-type-btn').forEach(b => b.classList.toggle('is-active', b.dataset.type === type));
  document.querySelectorAll('.he-shot-panel').forEach(p => p.classList.remove('is-visible'));
  const panel = document.getElementById('panel-' + type);
  if (panel) panel.classList.add('is-visible');
  const btn = document.getElementById('panel-add-btn');
  if (btn) { btn.style.display = 'block'; btn.textContent = editing ? 'Update Shot' : 'Add Shot'; }
}

function closePanel() {
  _activeType = null;
  _editIdx = null;
  document.querySelectorAll('.he-type-btn').forEach(b => b.classList.remove('is-active'));
  document.querySelectorAll('.he-shot-panel').forEach(p => p.classList.remove('is-visible'));
  const btn = document.getElementById('panel-add-btn');
  if (btn) btn.style.display = 'none';
}

function clearPanel(type) {
  if (type === 'ott') {
    _tsDir = null; _tsMod = null;
    if (_tsSyncUI) _tsSyncUI(false);
  } else if (type === 'app') {
    const d = document.getElementById('app-dist-exact'); if (d) d.value = '';
    document.querySelectorAll('#app-miss-dir-pills .he-pill--multi').forEach(p => p.classList.remove('is-active'));
    document.querySelectorAll('#app-lie-pills .he-pill--multi').forEach(p => p.classList.remove('is-active'));
    const mi = document.getElementById('app-miss-input'); if (mi) mi.value = '';
    const li = document.getElementById('app-lie-input');  if (li) li.value = '';
    _appMissed = false;
    document.getElementById('app-hit-green')?.classList.add('is-active');
    document.getElementById('app-missed-green')?.classList.remove('is-active');
    reveal(document.getElementById('app-miss-reveal'), false);
  } else if (type === 'atg') {
    const d = document.getElementById('atg-dist-exact'); if (d) d.value = '';
    document.querySelectorAll('#atg-lie-pills .he-pill--multi').forEach(p => p.classList.remove('is-active'));
    const li = document.getElementById('atg-lie-input'); if (li) li.value = '';
  } else if (type === 'putt') {
    const d = document.getElementById('putt-dist-exact'); if (d) d.value = '';
  }
}

function populatePanel(shot) {
  const type = shot.type;
  if (type === 'ott') {
    _tsDir = shot.direction || null;
    _tsMod = shot.mod || null;
    if (_tsSyncUI) _tsSyncUI(false);
  } else if (type === 'app') {
    const d = document.getElementById('app-dist-exact'); if (d) d.value = shot.distance || '';
    _appMissed = !!shot.miss;
    document.getElementById('app-hit-green')?.classList.toggle('is-active', !_appMissed);
    document.getElementById('app-missed-green')?.classList.toggle('is-active', _appMissed);
    reveal(document.getElementById('app-miss-reveal'), _appMissed);
    // Set miss direction pills
    const missVals = new Set((shot.miss || '').split(',').filter(Boolean));
    document.querySelectorAll('#app-miss-dir-pills .he-pill--multi').forEach(p => {
      p.classList.toggle('is-active', missVals.has(p.dataset.value));
    });
    const mi = document.getElementById('app-miss-input'); if (mi) mi.value = shot.miss || '';
    // Set lie pills
    const lieVal = shot.lie || '';
    document.querySelectorAll('#app-lie-pills .he-pill--multi').forEach(p => {
      p.classList.toggle('is-active', p.dataset.value === lieVal);
    });
    const li = document.getElementById('app-lie-input'); if (li) li.value = lieVal;
  } else if (type === 'atg') {
    const d = document.getElementById('atg-dist-exact'); if (d) d.value = shot.distance || '';
    const lieVal = shot.lie || '';
    document.querySelectorAll('#atg-lie-pills .he-pill--multi').forEach(p => {
      p.classList.toggle('is-active', p.dataset.value === lieVal);
    });
    const li = document.getElementById('atg-lie-input'); if (li) li.value = lieVal;
  } else if (type === 'putt') {
    const d = document.getElementById('putt-dist-exact'); if (d) d.value = shot.putt_distance || '';
  }
}

function collectPanelShot(type) {
  const shot = { type };
  if (type === 'ott') {
    shot.direction = _tsDir || null;
    shot.mod = _tsMod || null;
  } else if (type === 'app') {
    const raw = document.getElementById('app-dist-exact')?.value;
    shot.distance = raw ? parseInt(raw) : null;
    shot.miss = _appMissed ? (document.getElementById('app-miss-input')?.value || null) : null;
    shot.lie  = _appMissed ? (document.getElementById('app-lie-input')?.value || null) : null;
  } else if (type === 'atg') {
    const raw = document.getElementById('atg-dist-exact')?.value;
    shot.distance = raw ? parseInt(raw) : null;
    shot.lie = document.getElementById('atg-lie-input')?.value || null;
  } else if (type === 'putt') {
    const raw = document.getElementById('putt-dist-exact')?.value;
    shot.putt_distance = raw ? parseInt(raw) : null;
  }
  return shot;
}

// ── Shot CRUD ─────────────────────────────────────────────────────────────────
function commitShot() {
  if (!_activeType) return;
  const shot = collectPanelShot(_activeType);
  if (_editIdx !== null) {
    _shots[_editIdx] = shot;
  } else {
    _shots.push(shot);
  }
  closePanel();
  saveState();
  renderShotList();
  updateScoreDisplay();
  scheduleAutosave();
  if (navigator.vibrate) navigator.vibrate(10);
}

// Called via delegated click on shot-list
function handleShotListClick(e) {
  const delBtn = e.target.closest('[data-del]');
  if (delBtn) {
    const idx = parseInt(delBtn.dataset.del);
    _shots.splice(idx, 1);
    if (_editIdx !== null && _editIdx >= idx) { closePanel(); }
    saveState(); renderShotList(); updateScoreDisplay(); scheduleAutosave();
    return;
  }
  const row = e.target.closest('.he-shot-row');
  if (row) {
    const idx = parseInt(row.dataset.idx);
    _editIdx = idx;
    populatePanel(_shots[idx]);
    openPanel(_shots[idx].type, true);
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

// ── Validation ────────────────────────────────────────────────────────────────
function getHoleIssues() {
  const score = getScore();
  const par   = getPar();
  const diff  = score - par;
  const putts = _shots.filter(s => s.type === 'putt' || s.type === 'gimme').length;
  const issues = [];

  if (_shots.length === 0) {
    issues.push('No shots recorded — add at least one shot before saving');
    return issues;
  }
  if (score === 1) issues.push(`Score of 1 on par ${par} — confirming hole in one`);
  if (score <= par - 2 && score > 1) issues.push(`Score of ${score} on par ${par} — that's an eagle or better. Please confirm.`);
  if (putts === 0 && score > 1) issues.push(`No putts or gimmes recorded — did you hole out from off the green?`);
  if (putts >= 4) issues.push(`${putts} putting shots is unusual — please confirm`);
  return issues;
}

function showValidationModal(issues) {
  const overlay = document.getElementById('he-validation-overlay');
  const listEl  = document.getElementById('he-modal-issues');
  const parEl   = document.getElementById('he-modal-par');
  if (!overlay || !listEl) return;
  if (parEl) parEl.textContent = `Par ${getPar()} · hole ${getScore() - getPar() >= 0 ? '+' : ''}${getScore() - getPar()} · double-check:`;
  listEl.innerHTML = issues.map(i => `<li>${i}</li>`).join('');
  overlay.style.display = 'flex';
}

function hideValidationModal() {
  const overlay = document.getElementById('he-validation-overlay');
  if (overlay) overlay.style.display = 'none';
}

// ── Autosave ──────────────────────────────────────────────────────────────────
let _saveTimer = null;

async function triggerAutosave() {
  saveState(); // ensure hidden inputs are current
  const form = document.getElementById('hole-form');
  const url  = form?.dataset.autosaveUrl;
  if (!form || !url) return;
  const statusEl = document.getElementById('autosave-status');
  if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.className = 'autosave-status autosave-saving'; }
  try {
    const resp = await fetch(url, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (statusEl) {
      if (resp.ok) { statusEl.textContent = 'Saved'; statusEl.className = 'autosave-status autosave-saved'; }
      else         { statusEl.textContent = 'Save failed'; statusEl.className = 'autosave-status autosave-error'; }
    }
  } catch {
    if (statusEl) { statusEl.textContent = 'Save failed'; statusEl.className = 'autosave-status autosave-error'; }
  }
}

function scheduleAutosave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(triggerAutosave, 1500);
}

// ── OTT SVG ───────────────────────────────────────────────────────────────────
function initTeeShotSVG() {
  const input      = document.getElementById('tee-shot-svg-hidden');
  const tsLeft     = document.getElementById('ts-left');
  const tsFairway  = document.getElementById('ts-fairway');
  const tsRight    = document.getElementById('ts-right');
  const tsCheck    = document.getElementById('ts-check');
  if (!tsLeft || !tsFairway || !tsRight) return;

  const ROUGH_BASE   = '#c4a35a', ROUGH_ACTIVE = '#c8860b';
  const FW_BASE      = '#2d5a27', FW_ACTIVE    = '#4caf50';

  function syncUI(vibrate) {
    tsLeft.setAttribute('fill',    _tsDir === 'left'    ? ROUGH_ACTIVE : ROUGH_BASE);
    tsFairway.setAttribute('fill', _tsDir === 'fairway' ? FW_ACTIVE    : FW_BASE);
    tsRight.setAttribute('fill',   _tsDir === 'right'   ? ROUGH_ACTIVE : ROUGH_BASE);
    if (tsCheck) tsCheck.setAttribute('visibility', _tsDir === 'fairway' ? 'visible' : 'hidden');
    document.getElementById('ts-bunker-btn')?.classList.toggle('is-active', _tsMod === 'bunker');
    document.getElementById('ts-penalty-btn')?.classList.toggle('is-active', _tsMod === 'penalty');
    if (vibrate && navigator.vibrate) navigator.vibrate(10);
  }
  _tsSyncUI = syncUI;

  tsLeft.addEventListener('click',    () => { _tsDir = (_tsDir === 'left')    ? null : 'left';    syncUI(true); });
  tsFairway.addEventListener('click', () => { _tsDir = 'fairway'; _tsMod = null; syncUI(true); });
  tsRight.addEventListener('click',   () => { _tsDir = (_tsDir === 'right')   ? null : 'right';   syncUI(true); });
  syncUI(false);
}

// ── Main init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // Init shot state from server-rendered initial data
  try { _shots    = JSON.parse(window.INITIAL_SHOTS || '[]'); } catch { _shots = []; }
  _penalties = parseInt(window.INITIAL_PENALTIES) || 0;
  renderShotList();
  updateScoreDisplay();

  // Update penalties display
  const penDisplay = document.getElementById('pen-display');
  if (penDisplay) penDisplay.textContent = _penalties;

  // Init OTT SVG
  initTeeShotSVG();

  // Shot type buttons
  document.querySelectorAll('.he-type-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      if (type === 'gimme') {
        _shots.push({ type: 'gimme' });
        saveState(); renderShotList(); updateScoreDisplay(); scheduleAutosave();
        if (navigator.vibrate) navigator.vibrate(10);
        return;
      }
      if (_activeType === type && _editIdx === null) { closePanel(); return; }
      _editIdx = null;
      clearPanel(type);
      openPanel(type, false);
    });
  });

  // Shot list delegation (edit + delete)
  document.getElementById('shot-list')?.addEventListener('click', handleShotListClick);

  // Panel add/update button
  document.getElementById('panel-add-btn')?.addEventListener('click', commitShot);

  // App hit/miss toggle
  document.getElementById('app-hit-green')?.addEventListener('click', () => {
    _appMissed = false;
    document.getElementById('app-hit-green')?.classList.add('is-active');
    document.getElementById('app-missed-green')?.classList.remove('is-active');
    reveal(document.getElementById('app-miss-reveal'), false);
  });
  document.getElementById('app-missed-green')?.addEventListener('click', () => {
    _appMissed = true;
    document.getElementById('app-missed-green')?.classList.add('is-active');
    document.getElementById('app-hit-green')?.classList.remove('is-active');
    reveal(document.getElementById('app-miss-reveal'), true);
  });

  // Penalties stepper
  const penDown = document.getElementById('pen-down');
  const penUp   = document.getElementById('pen-up');
  const penDisp = document.getElementById('pen-display');
  if (penDown && penUp && penDisp) {
    penDown.addEventListener('click', () => {
      if (_penalties > 0) { _penalties--; penDisp.textContent = _penalties; updateScoreDisplay(); saveState(); scheduleAutosave(); if (navigator.vibrate) navigator.vibrate(8); }
    });
    penUp.addEventListener('click', () => {
      if (_penalties < 10) { _penalties++; penDisp.textContent = _penalties; updateScoreDisplay(); saveState(); scheduleAutosave(); if (navigator.vibrate) navigator.vibrate(8); }
    });
  }

  // Nav interception — save before navigating away
  document.querySelectorAll('.he-nav-dot').forEach(a => {
    a.addEventListener('click', async e => {
      if (a.classList.contains('he-nav-dot--current')) return;
      e.preventDefault();
      await triggerAutosave();
      window.location.href = a.getAttribute('href');
    });
  });
  document.querySelector('.he-skip-btn')?.addEventListener('click', async e => {
    e.preventDefault();
    const href = e.currentTarget.getAttribute('href');
    await triggerAutosave();
    window.location.href = href;
  });

  // Validation modal buttons
  document.getElementById('he-modal-fix')?.addEventListener('click', hideValidationModal);
  document.getElementById('he-modal-confirm')?.addEventListener('click', () => {
    hideValidationModal();
    _validationOverride = true;
    document.getElementById('hole-form')?.requestSubmit();
  });

  // Form submit
  let _validationOverride = false;
  document.getElementById('hole-form')?.addEventListener('submit', e => {
    saveState();
    if (!_validationOverride) {
      const issues = getHoleIssues();
      if (issues.length > 0) { e.preventDefault(); showValidationModal(issues); return; }
    }
    _validationOverride = false;
  });

});

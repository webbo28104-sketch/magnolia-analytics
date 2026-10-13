/**
 * Magnolia Analytics — Round Entry (shot-by-shot)
 */

// ── Module-level tee-shot SVG state ──────────────────────────────────────────
var _tsDir = null;   // 'fairway' | 'left' | 'right' | null
var _tsMod = null;   // 'bunker' | 'penalty' | null
var _tsSyncUI = null;

// ── Shot list state ───────────────────────────────────────────────────────────
var _shots     = [];
var _penalties = 0;
var _editIdx   = null;   // null = adding new, integer = editing existing
var _activeType = null;
var _club      = null;   // club key selected in the open panel (My Bag clubs)
var _appLie    = null;   // 'fairway' | 'rough' | 'bunker' for the open approach panel

// ── Global multi-pill delegated click handler ─────────────────────────────────
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
  } else if (group === 'app-shot-type') {
    // Exclusive single-select — deactivate siblings, activate this one
    pill.closest('.he-pills')?.querySelectorAll('.he-pill--multi').forEach(p => p.classList.remove('is-active'));
    pill.classList.add('is-active');
    _appShotType = value;
    _syncAppShotType();
    return;
  } else if (group === 'lie-type' || group === 'app-lie' || group === 'atg-lie') {
    pill.classList.toggle('is-active');
  } else if (group === 'tee-mod') {
    _tsMod = (_tsMod === value) ? null : value;
    if (_tsMod && _tsDir === 'fairway') _tsDir = null;
    if (_tsSyncUI) _tsSyncUI(true);
    return;
  }

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

// ── Panel warning helpers ─────────────────────────────────────────────────────
// Inline style overrides CSS cascade — guarantees visibility regardless of specificity
function showPanelWarn(type, msg) {
  const el = document.getElementById('warn-' + type);
  if (!el) return;
  if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
  el.innerHTML = '⚠ ' + msg;
  el.style.display = 'block';
}
function hidePanelWarn(type) { showPanelWarn(type, ''); }

// ── Sequence-aware context warning rules ──────────────────────────────────────
// Called when a panel opens. Returns nothing — directly updates the warn div.
// Rules are positional (based on what shots already exist), not hard-coded scenarios.
function applyPanelContextWarn(type) {
  hidePanelWarn(type);
  if (_editIdx !== null) return; // no warnings when editing an existing shot

  const par      = getPar();
  const count    = _shots.length;
  const lastShot = count > 0 ? _shots[count - 1] : null;
  const lastType = lastShot ? lastShot.type : null;
  const hasOTT   = _shots.some(s => s.type === 'ott');
  const hasPenalty = _shots.some(s => s.mod === 'penalty') || _penalties > 0;

  if (type === 'ott') {
    if (count === 0 && par === 3) {
      showPanelWarn('ott',
        'On a par 3, tee shots are classified as Approach in the standard strokes-gained method (Broadie). ' +
        'Recording as OTT will count toward SG Off the Tee rather than SG Approach.');
    } else if (count > 0 && !hasPenalty) {
      showPanelWarn('ott',
        `Shot #${count + 1}: Off the Tee is for your first shot from the tee box. ` +
        'A second OTT only makes sense after a penalty stroke (OB/water re-tee). ' +
        'Consider Approach or ATG instead.');
    }

  } else if (type === 'app') {
    const prevOTT = _shots.find(s => s.type === 'ott');
    const appsSoFar = _shots.filter(s => s.type === 'app').length;
    if (prevOTT && prevOTT.mod === 'trees' && appsSoFar === 0) {
      showPanelWarn('app',
        'Recovery shot — enter the distance you punched out to. ' +
        'This shot will be attributed to SG Off the Tee, not SG Approach, ' +
        'keeping your approach stats fair.');
    } else if (count === 0 && par !== 3) {
      showPanelWarn('app',
        `No tee shot recorded yet. On a par ${par}, the first shot is usually Off the Tee. ` +
        'Use Approach for shots played from the fairway or rough after the tee shot.');
    } else if (lastType === 'putt' || lastType === 'gimme') {
      showPanelWarn('app',
        'You\'re adding an Approach after a putting shot. This typically means you putted ' +
        'past the hole and are left with a long approach back — confirm this is correct.');
    }

  } else if (type === 'atg') {
    if (count === 0) {
      showPanelWarn('atg',
        'ATG is for short-game shots played close to the green. Starting with ATG is unusual — ' +
        'are you sure you don\'t want to begin with Off the Tee or Approach?');
    } else if (lastType === 'putt' || lastType === 'gimme') {
      showPanelWarn('atg',
        'Adding ATG after a putt means you putted past or off the green and need to chip back ' +
        '(degreening). Only log this if that\'s what happened.');
    }

  } else if (type === 'putt') {
    if (count === 0) {
      showPanelWarn('putt',
        'Putt as your first shot is unusual. Are you already on the green ' +
        'without a tee shot or approach? (e.g. a short par 3 tee shot that landed on the green)');
    } else if (lastType === 'atg') {
      // Normal flow — no warning needed
    }
  }
}

// ── Shot rendering ────────────────────────────────────────────────────────────
function shotTypeLabel(type) {
  return { ott: 'OTT', app: 'App', atg: 'ATG', putt: 'Putt', gimme: 'Gimme' }[type] || type;
}

function clubLabel(key) {
  if (!key) return '';
  var c = (window.MAG_BAG || []).find(function (b) { return b.key === key; });
  if (c) return c.label;
  return /^\d+$/.test(key) ? key + '°' : key;
}

function shotSummary(shot) {
  var text = _shotSummaryText(shot);
  if (shot.club && shot.type !== 'putt' && shot.type !== 'gimme') return clubLabel(shot.club) + ' · ' + text;
  return text;
}

function _shotSummaryText(shot) {
  switch (shot.type) {
    case 'ott': {
      const parts = [];
      if (shot.direction === 'fairway') parts.push('Fairway');
      else if (shot.direction === 'left') parts.push('Left rough');
      else if (shot.direction === 'right') parts.push('Right rough');
      if (shot.mod === 'bunker') parts.push('Bunker');
      else if (shot.mod === 'penalty') parts.push('Penalty');
      else if (shot.mod === 'trees') parts.push('Trees');
      return parts.join(' · ') || 'Tee shot';
    }
    case 'app': {
      const parts = [];
      if (shot.is_layup)          parts.push('Lay Up');
      else if (shot.lie === 'recovery') parts.push('Recovery');
      if (shot.distance) parts.push(shot.distance + 'y');
      if (shot.lie && shot.lie !== 'recovery' && shot.lie !== 'fairway') parts.push(shot.lie.charAt(0).toUpperCase() + shot.lie.slice(1));
      if (shot.miss) parts.push('Miss ' + shot.miss.replace(',', '/'));
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
      return shot.gimme_distance ? `Conceded (${shot.gimme_distance}ft)` : 'Conceded';
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
    lbl.className = 'he-score-vs-par' +
      (diff <= -1 ? ' he-score-vs-par--birdie' :
       diff === 0 ? ' he-score-vs-par--par' :
       diff === 1 ? ' he-score-vs-par--bogey' :
                   ' he-score-vs-par--double');
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

  const ott   = _shots.find(s => s.type === 'ott');
  const apps  = _shots.filter(s => s.type === 'app');
  const atgs  = _shots.filter(s => s.type === 'atg');
  const putts = _shots.filter(s => s.type === 'putt' || s.type === 'gimme');
  const par   = getPar();

  if (ott) {
    let val = '';
    if (ott.direction === 'fairway') val = 'fairway';
    else { const p = [ott.mod, ott.direction].filter(Boolean); val = p.join(','); }
    setHidden('tee_shot', val);
  }

  // Par 5 second shots, par 4 trees punch-outs, and deliberate lay-ups all use
  // second_shot_distance for the intermediate shot; approach_distance = real approach.
  const hasTreesOTT = ott && ott.mod === 'trees';
  const hasLayup    = apps.some(s => s.is_layup);
  const needsSplit  = (par === 5 || hasTreesOTT || hasLayup) && apps.length >= 2;
  if (needsSplit) {
    setHidden('second_shot_distance', apps[0].distance || '');
    const last = apps[apps.length - 1];
    setHidden('approach_distance', last.distance || '');
    // Par 4 layup: player can't hit GIR (3+ shots to reach green) — force a miss marker
    // so the server correctly sets gir = False regardless of how the last approach lands.
    if (par === 4 && hasLayup && !last.miss) {
      setHidden('approach_miss', 'layup');
    } else {
      setHidden('approach_miss', last.miss || '');
    }
  } else if (apps.length) {
    setHidden('approach_distance', apps[0].distance || '');
    setHidden('approach_miss',     apps[0].miss || '');
  }

  // Record lie_type = 'recovery' when any approach is a recovery shot, so the
  // aggregate strokes_gained_approach() uses the correct baseline.
  const recoveryApp = apps.find(s => s.lie === 'recovery');
  setHidden('lie_type', recoveryApp ? 'recovery' : '');

  setHidden('atg_strokes', atgs.length || 0);
  if (atgs.length) {
    setHidden('scramble_distance', atgs[0].distance || '');
    const bunkerAtg = atgs.find(s => s.lie === 'bunker');
    setHidden('sand_save_attempt', bunkerAtg ? 'true' : '');
  }

  setHidden('putts', putts.length);
  // first_putt_distance = distance before the first putting-type shot.
  // If the only putt is a gimme, use its gimme_distance (ATG/Approach SG
  // needs to know where the ball was left — the conceded distance).
  const firstPutt = putts.length > 0 ? putts[0] : null;
  let firstPuttDist = '';
  if (firstPutt) {
    firstPuttDist = firstPutt.type === 'gimme'
      ? (firstPutt.gimme_distance || 3)   // 3 ft standard gimme distance
      : (firstPutt.putt_distance  || '');
  }
  setHidden('first_putt_distance', firstPuttDist);
  const lastPutt = putts.length > 0 ? putts[putts.length - 1] : null;
  setHidden('last_putt_gimme', (lastPutt && lastPutt.type === 'gimme') ? 'true' : '');
  setHidden('gimme_distance', (lastPutt && lastPutt.type === 'gimme' && lastPutt.gimme_distance) ? lastPutt.gimme_distance : '');
}

// ── Panel management ──────────────────────────────────────────────────────────
function openPanel(type, editing) {
  _activeType = type;
  document.querySelectorAll('.he-type-btn').forEach(b => b.classList.toggle('is-active', b.dataset.type === type));
  document.querySelectorAll('.he-shot-panel').forEach(p => p.classList.remove('is-visible'));
  const panel = document.getElementById('panel-' + type);
  if (panel) panel.classList.add('is-visible');
  const btn = document.getElementById('panel-add-btn');
  if (btn) {
    btn.style.display = 'block';
    btn.textContent = type === 'gimme'
      ? (editing ? 'Update Gimme' : 'Add Gimme')
      : (editing ? 'Update Shot' : 'Add Shot');
  }
  applyPanelContextWarn(type);
  syncClubUI();
  syncLieUI();
  resetCaddy();
  if (type === 'ott') requestCaddy('ott');
  if (type === 'app' && document.getElementById('app-dist-exact')?.value) requestCaddy('app');
}

// ── Club row (My Bag) ─────────────────────────────────────────────────────────
function buildClubRows() {
  var bag = window.MAG_BAG || [];
  document.querySelectorAll('[data-club-for]').forEach(function (box) {
    var row = box.closest('.he-club-row');
    if (!bag.length) { if (row) row.style.display = 'none'; return; }
    var clubs = bag.filter(function (c) { return c.key !== 'P'; });
    box.innerHTML = clubs.map(function (c) {
      return '<button type="button" class="he-pill he-club-pill" data-club="' + c.key + '" title="' + c.name + '">' + c.label + '</button>';
    }).join('');
    if (row) row.style.display = '';
  });
}

function syncClubUI() {
  document.querySelectorAll('.he-club-pill').forEach(function (p) {
    p.classList.toggle('is-active', p.dataset.club === _club);
    p.setAttribute('aria-pressed', p.dataset.club === _club ? 'true' : 'false');
  });
}

// ── Approach lie ─────────────────────────────────────────────────────────────
// Default lie for a new approach, inferred from the shot before it (mirrors
// _lie_after in app/utils/shot_sg.py).
function defaultAppLie() {
  var idx  = (_editIdx !== null) ? _editIdx : _shots.length;
  var prev = idx > 0 ? _shots[idx - 1] : null;
  if (!prev) return 'fairway';
  if (prev.type === 'ott') {
    if (prev.mod === 'bunker') return 'bunker';
    if (prev.mod === 'penalty' || prev.mod === 'trees') return 'rough';
    return prev.direction === 'fairway' ? 'fairway' : 'rough';
  }
  if (prev.type === 'app') return (prev.is_layup || !prev.miss) ? 'fairway' : 'rough';
  if (prev.type === 'atg') return 'rough';
  return 'fairway';
}

function syncLieUI() {
  var row = document.getElementById('app-lie-row');
  if (row) row.style.display = (_appShotType === 'recovery') ? 'none' : '';
  document.querySelectorAll('.he-lie-pill').forEach(function (p) {
    p.classList.toggle('is-active', p.dataset.lie === _appLie);
    p.setAttribute('aria-pressed', p.dataset.lie === _appLie ? 'true' : 'false');
  });
}

// ── Caddy ────────────────────────────────────────────────────────────────────
var _caddyTimer = null;
var _caddySeq   = 0;

function resetCaddy() {
  document.querySelectorAll('.he-caddy').forEach(function (el) { el.style.display = 'none'; el.innerHTML = ''; });
}

function scheduleCaddy(type) {
  clearTimeout(_caddyTimer);
  _caddyTimer = setTimeout(function () { requestCaddy(type); }, 450);
}

function requestCaddy(type) {
  if (!window.CADDY_ENABLED || !window.CADDY_URL) return;
  var box = document.getElementById('caddy-' + type);
  if (!box) return;
  var params = new URLSearchParams({ type: type });
  if (type === 'app') {
    var d = document.getElementById('app-dist-exact')?.value;
    if (!d) { box.style.display = 'none'; return; }
    params.set('distance', d);
    if (_appLie) params.set('lie', _appLie);
  } else if (window.HOLE_YARDAGE) {
    params.set('hole_yardage', window.HOLE_YARDAGE);
  }
  var seq = ++_caddySeq;
  fetch(window.CADDY_URL + '?' + params.toString(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function (r) { return r.json(); })
    .then(function (res) { if (seq === _caddySeq) renderCaddy(box, res, type); })
    .catch(function () { box.style.display = 'none'; });
}

function _sg(v) {
  if (v === null || v === undefined) return '—';
  return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);
}

function renderCaddy(box, res, type) {
  if (!res || res.status === 'locked' || res.status === 'error' || res.status === 'need_distance') {
    box.style.display = 'none';
    return;
  }
  var wx = res.weather ? (Math.round(res.weather.temp_c) + '°C · wind ' + Math.round(res.weather.wind_kph) + ' km/h') : '';
  if (res.status === 'learning') {
    box.innerHTML = '<div class="he-caddy-h"><span>Caddy</span><span>' + wx + '</span></div>' +
      '<p class="he-caddy-note">' + (res.message || ('Still learning your game: ' + res.logged + ' of ' + res.needed +
      ' shots logged with a club. Keep tagging clubs and recommendations will appear here.')) + '</p>';
    box.style.display = 'block';
    return;
  }
  var b = res.best;
  var sub = type === 'app'
    ? (res.plays_like && res.plays_like !== res.distance ? 'Plays like ' + res.plays_like + ' yds today' : (b.avg_dist ? 'You average ' + b.avg_dist + ' yds' : ''))
    : (b.avg_dist ? 'You average ' + b.avg_dist + ' yds' : '');
  var stat = b.n ? (_sg(b.per) + ' SG/shot · ' + b.n + ' shot' + (b.n === 1 ? '' : 's') + (type === 'app' ? ' from here' : ' on similar holes'))
                 : 'No shots from this distance yet';
  var alts = (res.alts || []).map(function (a) {
    return '<button type="button" class="he-caddy-alt" data-club="' + a.club + '"><span class="k">' + a.label + '</span>' +
      '<span class="m">' + (a.n ? a.n + ' shots · ' + _sg(a.per) + '/shot' : (a.avg_dist ? 'avg ' + a.avg_dist + ' yds' : '')) + '</span></button>';
  }).join('');
  box.innerHTML =
    '<div class="he-caddy-h"><span>Caddy</span><span>' + wx + '</span></div>' +
    '<div class="he-caddy-main"><div><div class="he-caddy-club">' + b.label + '</div><div class="he-caddy-sub">' + sub + '</div></div>' +
    '<button type="button" class="he-caddy-use" data-club="' + b.club + '">Use ' + b.label + '</button></div>' +
    '<div class="he-caddy-stat">' + stat + '</div>' + (alts ? '<div class="he-caddy-alts">' + alts + '</div>' : '');
  box.style.display = 'block';
}

function closePanel() {
  _activeType = null;
  _editIdx    = null;
  document.querySelectorAll('.he-type-btn').forEach(b => b.classList.remove('is-active'));
  document.querySelectorAll('.he-shot-panel').forEach(p => p.classList.remove('is-visible'));
  const btn = document.getElementById('panel-add-btn');
  if (btn) btn.style.display = 'none';
}

var _appShotType  = 'standard'; // 'standard' | 'layup' | 'recovery'

function _syncAppShotType() {
  // Active class is managed by the delegated handler; this only handles show/hide.
  // Also called from clearPanel/populatePanel to restore state when editing a shot.
  document.getElementById('app-type-standard')?.classList.toggle('is-active', _appShotType === 'standard');
  document.getElementById('app-type-layup')?.classList.toggle('is-active',    _appShotType === 'layup');
  document.getElementById('app-type-recovery')?.classList.toggle('is-active', _appShotType === 'recovery');
  const isLayup   = _appShotType === 'layup';
  const missRow   = document.getElementById('app-miss-row');
  const layupNote = document.getElementById('app-layup-note');
  if (missRow)   missRow.style.display   = isLayup ? 'none'  : '';
  if (layupNote) layupNote.style.display = isLayup ? 'block' : 'none';
  syncLieUI();
}

function clearPanel(type) {
  hidePanelWarn(type);
  _club = null;
  if (type === 'app') _appLie = defaultAppLie();
  if (type === 'ott') {
    _tsDir = null; _tsMod = null;
    if (_tsSyncUI) _tsSyncUI(false);
  } else if (type === 'app') {
    const d = document.getElementById('app-dist-exact'); if (d) d.value = '';
    document.querySelectorAll('#app-miss-dir-pills .he-pill--multi').forEach(p => p.classList.remove('is-active'));
    const mi = document.getElementById('app-miss-input'); if (mi) mi.value = '';
    _appShotType = 'standard';
    _syncAppShotType();
  } else if (type === 'atg') {
    const d = document.getElementById('atg-dist-exact'); if (d) d.value = '';
    document.querySelectorAll('#atg-lie-pills .he-pill--multi').forEach(p => p.classList.remove('is-active'));
    const li = document.getElementById('atg-lie-input'); if (li) li.value = '';
  } else if (type === 'putt') {
    const d = document.getElementById('putt-dist-exact'); if (d) d.value = '';
  } else if (type === 'gimme') {
    const d = document.getElementById('gimme-dist-exact'); if (d) d.value = '';
  }
}

function populatePanel(shot) {
  const type = shot.type;
  hidePanelWarn(type);
  _club = shot.club || null;
  if (type === 'app') {
    _appLie = (['fairway', 'rough', 'bunker'].indexOf(shot.lie) !== -1) ? shot.lie : defaultAppLie();
  }
  if (type === 'ott') {
    _tsDir = shot.direction || null;
    _tsMod = shot.mod || null;
    if (_tsSyncUI) _tsSyncUI(false);
  } else if (type === 'app') {
    const d = document.getElementById('app-dist-exact'); if (d) d.value = shot.distance || '';
    _appShotType = shot.is_layup ? 'layup' : (shot.lie === 'recovery' ? 'recovery' : 'standard');
    _syncAppShotType();
    const missVals = new Set((shot.miss || '').split(',').filter(Boolean));
    document.querySelectorAll('#app-miss-dir-pills .he-pill--multi').forEach(p => {
      p.classList.toggle('is-active', missVals.has(p.dataset.value));
    });
    const mi = document.getElementById('app-miss-input'); if (mi) mi.value = shot.miss || '';
  } else if (type === 'atg') {
    const d = document.getElementById('atg-dist-exact'); if (d) d.value = shot.distance || '';
    const lieVal = shot.lie || '';
    document.querySelectorAll('#atg-lie-pills .he-pill--multi').forEach(p => {
      p.classList.toggle('is-active', p.dataset.value === lieVal);
    });
    const li = document.getElementById('atg-lie-input'); if (li) li.value = lieVal;
  } else if (type === 'putt') {
    const d = document.getElementById('putt-dist-exact'); if (d) d.value = shot.putt_distance || '';
  } else if (type === 'gimme') {
    const d = document.getElementById('gimme-dist-exact'); if (d) d.value = shot.gimme_distance || '';
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
    if (_appShotType === 'layup') {
      shot.is_layup = true;
      shot.miss     = null;
      if (_appLie) shot.lie = _appLie;
    } else {
      if (_appShotType === 'recovery') shot.lie = 'recovery';
      else if (_appLie) shot.lie = _appLie;
      shot.miss = document.getElementById('app-miss-input')?.value || null;
    }
  } else if (type === 'atg') {
    const raw = document.getElementById('atg-dist-exact')?.value;
    shot.distance = raw ? parseInt(raw) : null;
    shot.lie = document.getElementById('atg-lie-input')?.value || null;
  } else if (type === 'putt') {
    const raw = document.getElementById('putt-dist-exact')?.value;
    shot.putt_distance = raw ? parseInt(raw) : null;
  } else if (type === 'gimme') {
    const raw = document.getElementById('gimme-dist-exact')?.value;
    shot.gimme_distance = raw ? parseInt(raw) : null;
  }
  if (_club && (type === 'ott' || type === 'app' || type === 'atg')) shot.club = _club;
  return shot;
}

// ── Auto-open next panel ──────────────────────────────────────────────────────
// Called after a new shot is committed (not on edits). Opens the most likely
// next panel based on the current shot sequence and par. Never forces a decision.
function _autoOpenNext() {
  const par  = getPar();
  const last = _shots.length > 0 ? _shots[_shots.length - 1] : null;

  if (!last) {
    // Fresh hole: par 3 starts with approach, par 4/5 starts off the tee
    const type = par === 3 ? 'app' : 'ott';
    clearPanel(type); openPanel(type, false);
    return;
  }

  if (last.type === 'gimme') {
    // Hole complete — scroll to the Next Hole button
    closePanel();
    setTimeout(() => document.querySelector('.he-next-btn')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
    return;
  }

  if (last.type === 'ott') {
    // Penalty on tee shot → re-tee (another OTT); otherwise next is approach
    const type = last.mod === 'penalty' ? 'ott' : 'app';
    clearPanel(type); openPanel(type, false);
    return;
  }

  if (last.type === 'app') {
    // Lay up → another approach; hit green → putt; missed green → around the green
    if (last.is_layup) { clearPanel('app'); openPanel('app', false); return; }
    const type = last.miss ? 'atg' : 'putt';
    clearPanel(type); openPanel(type, false);
    return;
  }

  if (last.type === 'atg') {
    clearPanel('putt'); openPanel('putt', false);
    return;
  }

  // After a putt: don't auto-open (might be done, or need another putt)
  closePanel();
}

// ── Shot CRUD ─────────────────────────────────────────────────────────────────
function _doCommitShot() {
  if (!_activeType) return;
  const wasEdit = _editIdx !== null;
  const shot = collectPanelShot(_activeType);
  if (wasEdit) {
    _shots[_editIdx] = shot;
  } else {
    _shots.push(shot);
  }
  closePanel();
  saveState();
  renderShotList();
  updateScoreDisplay();
  triggerAutosave();
  if (navigator.vibrate) navigator.vibrate(10);
  if (!wasEdit) _autoOpenNext();
}

// ── Commit-time guards ─────────────────────────────────────────────────────────
// Guards check the standard strokes-gained distance thresholds and sequence rules.
// Returns a guard object { msg, toType, dist } if a modal should fire, else null.
function _getCommitGuard() {
  const type = _activeType;
  const isNew = _editIdx === null;

  if (type === 'app') {
    const dist = parseInt(document.getElementById('app-dist-exact')?.value);
    if (dist > 0 && dist <= 30) {
      // Standard SG ATG boundary: ≤30y = Around the Green
      return {
        msg: `${dist} yards is within the standard 30-yard around-the-green boundary. At this distance ` +
             `you are likely chipping or pitching — "Around the Green" will produce more ` +
             `accurate Strokes Gained data.`,
        toType: 'atg', dist
      };
    }
  }

  if (type === 'atg') {
    const dist = parseInt(document.getElementById('atg-dist-exact')?.value);
    if (dist > 0 && dist > 50) {
      // System ATG baselines only cover up to 50 yards
      return {
        msg: `${dist} yards exceeds the ATG baseline range (max 50 yards). The standard ATG ` +
             `category covers shots within 30 yards. Beyond 50 yards, Approach will give ` +
             `more accurate Strokes Gained data.`,
        toType: 'app', dist
      };
    }
    if (isNew && _shots.length === 0) {
      // ATG as very first shot — unusual, confirm
      return {
        msg: `ATG is for short-game shots played close to the green. Adding it as your ` +
             `first shot is unusual — on most holes you'd start with Off the Tee or Approach. ` +
             `Are you sure this is correct?`,
        toType: null, dist: null
      };
    }
  }

  if (type === 'ott' && isNew) {
    const hasPenalty = _shots.some(s => s.mod === 'penalty') || _penalties > 0;
    if (_shots.length > 0 && !hasPenalty) {
      return {
        msg: `You're logging a tee shot as shot #${_shots.length + 1} without a penalty ` +
             `on the previous shot. Off the Tee is only for your first shot from the tee ` +
             `box (or a re-tee after OB/water). Are you sure?`,
        toType: null, dist: null
      };
    }
  }

  return null;
}

function commitShot() {
  if (!_activeType) return;
  const guard = _getCommitGuard();
  if (guard) {
    showTypeSwitchModal(_activeType, guard.toType, guard.dist, guard.msg);
    return;
  }
  _doCommitShot();
}

// ── Type-switch / confirm modal ───────────────────────────────────────────────
function showTypeSwitchModal(fromType, toType, dist, msg) {
  const overlay   = document.getElementById('he-typeswitch-overlay');
  const msgEl     = document.getElementById('he-typeswitch-msg');
  const switchBtn = document.getElementById('he-typeswitch-switch');
  const keepBtn   = document.getElementById('he-typeswitch-keep');
  if (!overlay) { _doCommitShot(); return; } // fallback if modal missing
  if (msgEl) msgEl.textContent = msg;
  const labels = { app: 'Approach', atg: 'ATG', ott: 'OTT', putt: 'Putt' };
  if (toType) {
    if (switchBtn) { switchBtn.textContent = `Switch to ${labels[toType]}`; switchBtn.style.display = ''; }
    overlay.dataset.toType = toType;
    overlay.dataset.dist   = dist != null ? String(dist) : '';
  } else {
    if (switchBtn) switchBtn.style.display = 'none';
    overlay.dataset.toType = '';
    overlay.dataset.dist   = '';
  }
  if (keepBtn) keepBtn.textContent = `Keep as ${labels[fromType] || fromType}`;
  overlay.dataset.fromType = fromType;
  overlay.style.display = 'flex';
}

function hideTypeSwitchModal() {
  const overlay = document.getElementById('he-typeswitch-overlay');
  if (overlay) overlay.style.display = 'none';
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

// ── Hole-level validation (submit time) ──────────────────────────────────────
function getHoleIssues() {
  const score = getScore();
  const par   = getPar();
  const diff  = score - par;
  const putts = _shots.filter(s => s.type === 'putt' || s.type === 'gimme').length;
  const issues = [];

  if (_shots.length === 0) {
    issues.push('No shots recorded — add at least one shot before saving.');
    return issues;
  }
  if (score === 1)                           issues.push(`Score of 1 on par ${par} — confirming hole in one.`);
  if (score <= par - 2 && score > 1)         issues.push(`Score of ${score} on par ${par} — that's an eagle or better. Please confirm.`);
  if (putts === 0 && score > 1)              issues.push(`No putts or gimmes recorded — did you hole out from off the green?`);
  if (putts >= 4)                            issues.push(`${putts} putting shots recorded — please confirm.`);
  if (diff >= 5)                             issues.push(`Score of +${diff} on par ${par} — please confirm.`);
  return issues;
}

function showValidationModal(issues) {
  const overlay = document.getElementById('he-validation-overlay');
  const listEl  = document.getElementById('he-modal-issues');
  const parEl   = document.getElementById('he-modal-par');
  if (!overlay || !listEl) return;
  const d = getScore() - getPar();
  if (parEl) parEl.textContent = `Par ${getPar()} · ${d >= 0 ? '+' : ''}${d} · double-check:`;
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
  saveState();
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
  const tsLeft    = document.getElementById('ts-left');
  const tsFairway = document.getElementById('ts-fairway');
  const tsRight   = document.getElementById('ts-right');
  const tsCheck   = document.getElementById('ts-check');
  if (!tsLeft || !tsFairway || !tsRight) return;

  const ROUGH_BASE = '#c4a35a', ROUGH_ACTIVE = '#c8860b';
  const FW_BASE    = '#2d5a27', FW_ACTIVE    = '#4caf50';

  function syncUI(vibrate) {
    tsLeft.setAttribute('fill',    _tsDir === 'left'    ? ROUGH_ACTIVE : ROUGH_BASE);
    tsFairway.setAttribute('fill', _tsDir === 'fairway' ? FW_ACTIVE    : FW_BASE);
    tsRight.setAttribute('fill',   _tsDir === 'right'   ? ROUGH_ACTIVE : ROUGH_BASE);
    if (tsCheck) tsCheck.setAttribute('visibility', _tsDir === 'fairway' ? 'visible' : 'hidden');
    document.getElementById('ts-bunker-btn')?.classList.toggle('is-active', _tsMod === 'bunker');
    document.getElementById('ts-trees-btn')?.classList.toggle('is-active',  _tsMod === 'trees');
    document.getElementById('ts-penalty-btn')?.classList.toggle('is-active', _tsMod === 'penalty');
    if (vibrate && navigator.vibrate) navigator.vibrate(10);
  }
  _tsSyncUI = syncUI;

  tsLeft.addEventListener('click',    () => { _tsDir = (_tsDir === 'left')  ? null : 'left';    syncUI(true); });
  tsFairway.addEventListener('click', () => { _tsDir = 'fairway'; _tsMod = null; syncUI(true); });
  tsRight.addEventListener('click',   () => { _tsDir = (_tsDir === 'right') ? null : 'right';   syncUI(true); });
  syncUI(false);
}

// ── Main init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  let _validationOverride = false;

  // Init shot state from server-rendered data
  try { _shots = JSON.parse(window.INITIAL_SHOTS || '[]'); } catch { _shots = []; }
  _penalties = parseInt(window.INITIAL_PENALTIES) || 0;
  renderShotList();
  updateScoreDisplay();
  const penDisplay = document.getElementById('pen-display');
  if (penDisplay) penDisplay.textContent = _penalties;

  initTeeShotSVG();
  buildClubRows();

  // Club, lie and caddy clicks (delegated — club rows are built from the bag)
  document.addEventListener('click', function (e) {
    var pick = e.target.closest('.he-club-pill, .he-caddy-use, .he-caddy-alt');
    if (pick) {
      var key = pick.dataset.club;
      _club = (pick.classList.contains('he-club-pill') && _club === key) ? null : key;
      syncClubUI();
      if (navigator.vibrate) navigator.vibrate(10);
      return;
    }
    var lie = e.target.closest('.he-lie-pill');
    if (lie) {
      _appLie = lie.dataset.lie;
      syncLieUI();
      scheduleCaddy('app');
      if (navigator.vibrate) navigator.vibrate(10);
    }
  });
  document.getElementById('app-dist-exact')?.addEventListener('input', function () { scheduleCaddy('app'); });

  // Auto-open the predicted first panel on fresh holes only
  if (_shots.length === 0) _autoOpenNext();

  // Shot type buttons
  document.querySelectorAll('.he-type-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      if (_activeType === type && _editIdx === null) { closePanel(); return; }
      _editIdx = null;
      clearPanel(type);
      openPanel(type, false);
    });
  });

  // Shot list delegation
  document.getElementById('shot-list')?.addEventListener('click', handleShotListClick);

  // Panel add/update button
  document.getElementById('panel-add-btn')?.addEventListener('click', commitShot);

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

  // Distance inline hints (real-time, non-blocking)
  document.getElementById('app-dist-exact')?.addEventListener('input', function() {
    const val = parseInt(this.value);
    if (!val || val <= 0) { hidePanelWarn('app'); applyPanelContextWarn('app'); return; }
    if (val <= 30) {
      showPanelWarn('app', `${val} yards — Strokes gained classifies shots within 30 yards as Around the Green (ATG). Consider switching type.`);
    } else if (val <= 50) {
      showPanelWarn('app', `${val} yards is in the 30–50 yard scoring zone. The standard ATG boundary is 30 yards; this system's ATG baseline covers up to 50 yards. Use ATG if this is a chip or pitch.`);
    } else {
      hidePanelWarn('app');
    }
  });

  document.getElementById('atg-dist-exact')?.addEventListener('input', function() {
    const val = parseInt(this.value);
    if (!val || val <= 0) { hidePanelWarn('atg'); applyPanelContextWarn('atg'); return; }
    if (val > 50) {
      showPanelWarn('atg', `${val} yards exceeds the ATG baseline range (50 yards max). The standard ATG threshold is 30 yards — beyond 50 yards is Approach territory.`);
    } else if (val > 30) {
      showPanelWarn('atg', `${val} yards is between the standard 30-yard ATG limit and this system's 50-yard ATG range. If this is a full wedge shot, Approach may be more accurate.`);
    } else {
      hidePanelWarn('atg');
    }
  });

  // Type-switch modal — "Keep as [type]" commits as-is
  document.getElementById('he-typeswitch-keep')?.addEventListener('click', () => {
    hideTypeSwitchModal();
    _doCommitShot();
  });

  // Type-switch modal — "Switch to [type]" clears and opens new panel with distance pre-filled
  document.getElementById('he-typeswitch-switch')?.addEventListener('click', () => {
    const overlay  = document.getElementById('he-typeswitch-overlay');
    const fromType = overlay?.dataset.fromType;
    const toType   = overlay?.dataset.toType;
    const dist     = parseInt(overlay?.dataset.dist) || null;
    hideTypeSwitchModal();
    if (!toType) return;
    clearPanel(fromType);
    _activeType = null;
    _editIdx    = null;
    clearPanel(toType);
    openPanel(toType, false);
    if (dist) {
      const distInput = document.getElementById(toType + '-dist-exact');
      if (distInput) { distInput.value = dist; distInput.dispatchEvent(new Event('input')); }
    }
  });

  // Validation modal buttons
  document.getElementById('he-modal-fix')?.addEventListener('click', hideValidationModal);
  document.getElementById('he-modal-confirm')?.addEventListener('click', () => {
    hideValidationModal();
    _validationOverride = true;
    document.getElementById('hole-form')?.requestSubmit();
  });

  // Form submit with validation
  document.getElementById('hole-form')?.addEventListener('submit', e => {
    saveState();
    if (!_validationOverride) {
      const issues = getHoleIssues();
      if (issues.length > 0) { e.preventDefault(); showValidationModal(issues); return; }
    }
    _validationOverride = false;
  });

});

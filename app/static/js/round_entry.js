/**
 * Magnolia Analytics — Round Entry JavaScript
 * Works with the redesigned hole.html (he-pill / is-active / he-reveal / is-visible).
 */

document.addEventListener('DOMContentLoaded', () => {

  // ── Reveal helper ──────────────────────────────────────────────────────────
  function reveal(el, show) {
    if (!el) return;
    if (show) el.classList.add('is-visible');
    else       el.classList.remove('is-visible');
  }


  // ── Multi-select pill groups (miss direction + lie type) ──────────────────
  // Fix: use document-level event delegation instead of per-element listeners.
  // Per-element listeners attached at DOMContentLoaded don't reliably fire on
  // iOS Safari when the element lives inside an overflow:hidden / 0-height
  // .he-reveal container. Delegation catches the bubble at the document level.
  //
  // Group A (miss-dir): Left/Right mutually exclusive; Long/Short mutually exclusive.
  // Group B (lie-type): fully multi-select, no exclusions.

  function getMissDirValue() {
    return Array.from(document.querySelectorAll('#miss-dir-pills .he-pill--multi.is-active'))
                .map(p => p.dataset.value).join(',');
  }

  function getLieTypeValue() {
    return Array.from(document.querySelectorAll('#lie-type-pills .he-pill--multi.is-active'))
                .map(p => p.dataset.value).join(',');
  }

  document.addEventListener('click', e => {
    const pill = e.target.closest('.he-pill--multi');
    if (!pill) return;

    const group = pill.dataset.group;
    const value = pill.dataset.value;

    if (group === 'miss-dir') {
      if (pill.classList.contains('is-active')) {
        // Tap active pill to deselect
        pill.classList.remove('is-active');
      } else {
        // Auto-deselect the conflicting opposite before activating
        const conflict = { left: 'right', right: 'left', long: 'short', short: 'long' }[value];
        if (conflict) {
          document.querySelectorAll(`#miss-dir-pills .he-pill--multi[data-value="${conflict}"]`)
                  .forEach(p => p.classList.remove('is-active'));
        }
        pill.classList.add('is-active');
      }
      const newVal = getMissDirValue();
      const missInput = document.getElementById('approach-miss-input');
      if (missInput) missInput.value = newVal;
      handleApproachMissChange(newVal);
      // Reset miss-label error colour if a direction is now selected
      if (newVal) {
        const lbl = document.querySelector('#miss-dir-pills')
                             ?.closest('.he-field')?.querySelector('.he-label');
        if (lbl) lbl.style.color = '';
      }

    } else if (group === 'lie-type') {
      // Fully multi-select: toggle freely
      pill.classList.toggle('is-active');
      const lieInput = document.getElementById('lie-type-input');
      if (lieInput) lieInput.value = getLieTypeValue();
    }

    if (navigator.vibrate) navigator.vibrate(10);
  });


  // ── Radio pill tap-button groups (all non-multi pills) ────────────────────
  // Each .he-pill carries data-field and data-value.
  // Tap again = stays selected (radio behaviour).
  document.querySelectorAll('.he-pill:not(.he-pill--multi)').forEach(pill => {
    pill.addEventListener('click', () => {
      const field  = pill.dataset.field;
      if (!field) return; // handled separately (e.g. tee-shot SVG penalty btn)
      const value  = pill.dataset.value;
      const target = pill.dataset.target;

      const group = pill.closest('.he-pills');

      // Deactivate siblings
      if (group) {
        group.querySelectorAll('.he-pill').forEach(b => b.classList.remove('is-active'));
      }
      pill.classList.add('is-active');

      // Write to hidden input
      const inputId = target || `${field.replace(/_/g, '-')}-input`;
      const input = document.getElementById(inputId)
                 || document.querySelector(`input[name="${field}"]`);
      if (input) input.value = value;

      if (navigator.vibrate) navigator.vibrate(10);
    });
  });


  // ── Approach miss → show/hide scramble reveal ───────────
  function handleApproachMissChange(missValue) {
    const scrambleReveal = document.getElementById('scramble-reveal');
    reveal(scrambleReveal, !!missValue);
    if (!missValue) clearScrambleInputs();
  }


  // ── GIR toggle ──────────────────────────────────────────
  const girYes     = document.getElementById('gir-yes');
  const girNo      = document.getElementById('gir-no');
  const missReveal = document.getElementById('miss-reveal');

  if (girYes) {
    girYes.addEventListener('click', () => {
      girYes.classList.add('is-active');
      girNo.classList.remove('is-active');
      reveal(missReveal, false);
      const missInput = document.getElementById('approach-miss-input');
      if (missInput) missInput.value = '';
      document.querySelectorAll('#miss-dir-pills .he-pill--multi').forEach(b => b.classList.remove('is-active'));
      document.querySelectorAll('#lie-type-pills .he-pill--multi').forEach(b => b.classList.remove('is-active'));
      const lieInput = document.getElementById('lie-type-input');
      if (lieInput) lieInput.value = '';
      handleApproachMissChange('');
      if (navigator.vibrate) navigator.vibrate(10);
    });
  }

  if (girNo) {
    girNo.addEventListener('click', () => {
      girNo.classList.add('is-active');
      girYes.classList.remove('is-active');
      reveal(missReveal, true);
      if (navigator.vibrate) navigator.vibrate(10);
    });
  }


  // ── On-load: apply initial conditional state from server-rendered values ────
  const parInput = document.getElementById('par-input');
  const initPar  = parInput ? parseInt(parInput.value) : 4;

  // Tee shot: hide for par 3
  const teeShotReveal  = document.getElementById('tee-shot-reveal');
  reveal(teeShotReveal, initPar !== 3);

  // Second shot: show for par 5
  const secondShotReveal = document.getElementById('second-shot-reveal');
  reveal(secondShotReveal, initPar === 5);

  // Approach miss — sync scramble reveal from server-rendered value
  const missInput = document.getElementById('approach-miss-input');
  const initMiss  = missInput ? missInput.value : '';
  if (initMiss) {
    handleApproachMissChange(initMiss);
  }


  // ── Exact number inputs → hidden inputs ───────────────────────────────────
  // Pills are removed; exact inputs are now the sole input method for distances.
  function bindExactInput(exactId, hiddenInputId) {
    const exactEl  = document.getElementById(exactId);
    const hiddenEl = document.getElementById(hiddenInputId);
    if (!exactEl || !hiddenEl) return;

    // Sync on load (in case the field has a pre-filled value)
    if (exactEl.value.trim() !== '') hiddenEl.value = exactEl.value.trim();

    exactEl.addEventListener('input', () => {
      hiddenEl.value = exactEl.value.trim();
    });
  }

  bindExactInput('approach-dist-exact',  'approach-distance-input');
  bindExactInput('second-shot-exact',    'second-shot-distance-input');
  bindExactInput('first-putt-exact',     'first-putt-input');

  // Scramble — store as integer string
  (function bindScrambleExact() {
    const exactEl  = document.getElementById('scramble-dist-exact');
    const hiddenEl = document.getElementById('scramble-distance-input');
    if (!exactEl || !hiddenEl) return;

    exactEl.addEventListener('input', () => {
      const val = parseInt(exactEl.value);
      hiddenEl.value = (!isNaN(val) && exactEl.value.trim() !== '') ? String(val) : '';
    });
  })();


  // ── Steppers ───────────────────────────────────────────────────────────────
  function initStepper(downId, upId, displayId, inputId, min, max) {
    const downBtn = document.getElementById(downId);
    const upBtn   = document.getElementById(upId);
    const display = document.getElementById(displayId);
    const input   = document.getElementById(inputId);
    if (!downBtn || !upBtn || !display || !input) return;

    function update(val) {
      display.textContent = val;
      input.value = val;
      if (navigator.vibrate) navigator.vibrate(8);
    }

    downBtn.addEventListener('click', () => {
      const val = parseInt(input.value) || 0;
      if (val > min) update(val - 1);
    });
    upBtn.addEventListener('click', () => {
      const val = parseInt(input.value) || 0;
      if (val < max) update(val + 1);
    });
  }

  initStepper('score-down',     'score-up',     'score-display',     'score-input',     1, 15);
  initStepper('putts-down',     'putts-up',     'putts-display',     'putts-input',     0, 10);
  initStepper('penalties-down', 'penalties-up', 'penalties-display', 'penalties-input', 0, 10);


  // ── Clear helpers ──────────────────────────────────────────────────────────
  function clearScrambleInputs() {
    const distInput = document.getElementById('scramble-distance-input');
    const exactEl   = document.getElementById('scramble-dist-exact');
    if (distInput) distInput.value = '';
    if (exactEl)   exactEl.value = '';
  }


  // ── Score vs par live label ────────────────────────────────────────────────
  (function initScoreVsParLabel() {
    const scoreInputEl = document.getElementById('score-input');
    const parInputEl   = document.getElementById('par-input');
    const label        = document.getElementById('score-vs-par');
    if (!scoreInputEl || !parInputEl || !label) return;

    function update() {
      const score = parseInt(scoreInputEl.value) || 4;
      const par   = parseInt(parInputEl.value)   || 4;
      const diff  = score - par;
      let text, cls;
      if      (diff <= -2)  { text = diff === -2 ? 'Eagle' : 'Albatross'; cls = '--birdie'; }
      else if (diff === -1) { text = 'Birdie';   cls = '--birdie'; }
      else if (diff ===  0) { text = 'Par';      cls = '--par';    }
      else if (diff ===  1) { text = 'Bogey';    cls = '--bogey';  }
      else if (diff ===  2) { text = 'Double';   cls = '--double'; }
      else                  { text = 'Triple+';  cls = '--double'; }
      label.textContent = text;
      label.className   = 'he-score-vs-par he-score-vs-par' + cls;
    }

    document.getElementById('score-down')?.addEventListener('click', update);
    document.getElementById('score-up')?.addEventListener('click',   update);
    update();
  })();


  // ── Tee shot SVG ──────────────────────────────────────────────────────────
  (function initTeeShotSVG() {
    const input      = document.getElementById('tee-shot-input');
    const tsLeft     = document.getElementById('ts-left');
    const tsFairway  = document.getElementById('ts-fairway');
    const tsRight    = document.getElementById('ts-right');
    const tsCheck    = document.getElementById('ts-check');
    const penaltyBtn = document.getElementById('ts-penalty-btn');
    if (!input || !tsLeft || !tsFairway || !tsRight) return;

    const ROUGH_BASE    = '#c4a35a';
    const ROUGH_ACTIVE  = '#c8860b';
    const FW_BASE       = '#2d5a27';
    const FW_ACTIVE     = '#4caf50';

    function reset() {
      tsLeft.setAttribute('fill',    ROUGH_BASE);
      tsFairway.setAttribute('fill', FW_BASE);
      tsRight.setAttribute('fill',   ROUGH_BASE);
      if (tsCheck)    tsCheck.setAttribute('visibility', 'hidden');
      if (penaltyBtn) penaltyBtn.classList.remove('is-active');
    }

    function select(area) {
      reset();
      input.value = area;
      if (area === 'fairway') {
        tsFairway.setAttribute('fill', FW_ACTIVE);
        if (tsCheck) tsCheck.setAttribute('visibility', 'visible');
      } else if (area === 'left') {
        tsLeft.setAttribute('fill', ROUGH_ACTIVE);
      } else if (area === 'right') {
        tsRight.setAttribute('fill', ROUGH_ACTIVE);
      } else if (area === 'penalty') {
        if (penaltyBtn) penaltyBtn.classList.add('is-active');
      }
      if (area && navigator.vibrate) navigator.vibrate(10);
    }

    tsLeft.addEventListener('click',    () => select('left'));
    tsFairway.addEventListener('click', () => select('fairway'));
    tsRight.addEventListener('click',   () => select('right'));

    if (penaltyBtn) {
      penaltyBtn.addEventListener('click', () => {
        if (input.value === 'penalty') { reset(); input.value = ''; }
        else select('penalty');
      });
    }

    if (input.value) select(input.value);
  })();


  // ── Arithmetic validation ─────────────────────────────────────────────────
  // Derives impossible/unusual combinations from first principles.
  // Does NOT block submission — shows a confirmation modal instead.

  function getHoleIssues() {
    const par   = parseInt(document.getElementById('par-input')?.value)   || 4;
    const score = parseInt(document.getElementById('score-input')?.value) || par;
    const putts = parseInt(document.getElementById('putts-input')?.value) || 0;
    // GIR = Yes when gir-yes pill is active; default to true for first render
    const girYesEl = document.getElementById('gir-yes');
    const girNoEl  = document.getElementById('gir-no');
    let gir = true; // default: assume GIR unless No is active
    if (girNoEl?.classList.contains('is-active'))  gir = false;
    if (girYesEl?.classList.contains('is-active')) gir = true;

    const issues = [];

    // Putts ≥ score: need at least 1 non-putt stroke (the tee shot)
    if (putts >= score) {
      issues.push(
        `${putts} putt${putts !== 1 ? 's' : ''} with a score of ${score} — ` +
        `you need at least 1 non-putt stroke`
      );
    }

    // GIR = Yes but shots-to-green exceeds par − 2
    // GIR requires reaching the green in at most (par − 2) shots.
    if (gir) {
      const shotsToGreen = score - putts;
      const maxForGIR    = par - 2;   // par3→1, par4→2, par5→3
      if (shotsToGreen > maxForGIR) {
        issues.push(
          `GIR marked Yes, but ${shotsToGreen} shot${shotsToGreen !== 1 ? 's' : ''} to the green — ` +
          `a par ${par} allows at most ${maxForGIR} for GIR`
        );
      }
    }

    // Score = 1 (hole in one): valid but always confirm
    if (score === 1) {
      issues.push(`Score of 1 on a par ${par} — confirming this as a hole in one`);
    }

    return issues;
  }

  function showValidationModal(issues) {
    const overlay  = document.getElementById('he-validation-overlay');
    const listEl   = document.getElementById('he-modal-issues');
    const parEl    = document.getElementById('he-modal-par');
    if (!overlay || !listEl) return;

    const par = parseInt(document.getElementById('par-input')?.value) || 4;
    if (parEl) parEl.textContent = `Par ${par} · your stats look unusual:`;
    listEl.innerHTML = issues.map(i => `<li>${i}</li>`).join('');
    overlay.style.display = 'flex';
  }

  function hideValidationModal() {
    const overlay = document.getElementById('he-validation-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  // Modal buttons
  document.getElementById('he-modal-fix')?.addEventListener('click', hideValidationModal);

  document.getElementById('he-modal-confirm')?.addEventListener('click', () => {
    hideValidationModal();
    validationOverride = true;
    document.getElementById('hole-form')?.requestSubmit();
  });


  // ── Form submit: miss direction check + arithmetic validation ──────────────
  let validationOverride = false;
  const holeForm = document.getElementById('hole-form');

  if (holeForm) {
    holeForm.addEventListener('submit', e => {

      // 1. Require at least one miss direction when GIR = No
      const mr = document.getElementById('miss-reveal');
      const mi = document.getElementById('approach-miss-input');
      if (mr && mr.classList.contains('is-visible') && mi && !mi.value) {
        e.preventDefault();
        const lbl = document.querySelector('#miss-dir-pills')
                             ?.closest('.he-field')?.querySelector('.he-label');
        if (lbl) {
          lbl.style.color = 'var(--he-red)';
          lbl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return;
      }

      // 2. Arithmetic validation — skip if user already confirmed
      if (!validationOverride) {
        const issues = getHoleIssues();
        if (issues.length > 0) {
          e.preventDefault();
          showValidationModal(issues);
          return;
        }
      }
      validationOverride = false; // reset after each submit attempt
    });
  }

});

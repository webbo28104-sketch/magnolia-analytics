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


  // ── Pill tap-button groups ─────────────────────────────────────────────────
  // Each .he-pill carries data-field and data-value.
  // Tapping an already-active pill deselects it (toggles off) for approach_miss only.
  // Other fields behave as radio buttons (tap again = stays selected).
  document.querySelectorAll('.he-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const field  = pill.dataset.field;
      if (!field) return; // handled separately (e.g. tee-shot SVG penalty btn)
      const value  = pill.dataset.value;
      const target = pill.dataset.target; // optional explicit hidden input id

      const group = pill.closest('.he-pills');

      // Toggle-off support for approach_miss (tap active pill to deselect)
      if (field === 'approach_miss' && pill.classList.contains('is-active')) {
        pill.classList.remove('is-active');
        const missInput = document.getElementById('approach-miss-input');
        if (missInput) missInput.value = '';
        handleApproachMissChange('');
        if (navigator.vibrate) navigator.vibrate(10);
        return;
      }

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

      // Conditional visibility handlers
      if (field === 'approach_miss') handleApproachMissChange(value);

      // Bucket tap clears the paired exact input (bucket wins until exact overrides)
      const exactMap = {
        first_putt_distance:  'first-putt-exact',
        approach_dist_bucket: 'approach-dist-exact',
        second_shot_bucket:   'second-shot-exact',
        scramble_distance:    'scramble-dist-exact',
      };
      if (exactMap[field]) {
        const exactEl = document.getElementById(exactMap[field]);
        if (exactEl) exactEl.value = '';
      }

      if (navigator.vibrate) navigator.vibrate(10);
    });
  });


  // ── Approach miss → show/hide scramble reveal + sand save reveal ───────────
  function handleApproachMissChange(missValue) {
    const scrambleReveal  = document.getElementById('scramble-reveal');
    const sandSaveReveal  = document.getElementById('sand-save-reveal');

    reveal(scrambleReveal, !!missValue);

    if (!missValue) {
      clearScrambleInputs();
    }

    if (missValue === 'bunker') {
      reveal(sandSaveReveal, true);
      const attemptInput = document.getElementById('sand-save-attempt-input');
      if (attemptInput) attemptInput.value = 'true';
    } else {
      reveal(sandSaveReveal, false);
      clearSandSave();
    }
  }


  // ── On-load: apply initial conditional state from server-rendered values ────
  // Par-based visibility (tee shot, second shot) — par is fixed from course_par
  const parInput = document.getElementById('par-input');
  const initPar  = parInput ? parseInt(parInput.value) : 4;

  // Tee shot: hide for par 3
  const teeShotReveal  = document.getElementById('tee-shot-reveal');
  reveal(teeShotReveal, initPar !== 3);

  // Second shot: show for par 5
  const secondShotReveal = document.getElementById('second-shot-reveal');
  reveal(secondShotReveal, initPar === 5);

  // Approach miss — apply to scramble/sand save (Jinja already sets is-visible on reveal
  // elements from server data, but we still run JS logic for sand save sub-reveal)
  const missInput = document.getElementById('approach-miss-input');
  const initMiss  = missInput ? missInput.value : '';
  if (initMiss) {
    handleApproachMissChange(initMiss);
  }


  // ── Exact number inputs override bucket selections ─────────────────────────
  function bindExactInput(exactId, pillsContainerId, hiddenInputId) {
    const exactEl  = document.getElementById(exactId);
    const hiddenEl = document.getElementById(hiddenInputId);
    const pillsEl  = document.getElementById(pillsContainerId);
    if (!exactEl || !hiddenEl) return;

    exactEl.addEventListener('input', () => {
      const val = exactEl.value.trim();
      if (val !== '') {
        // Deactivate all pills in the group
        if (pillsEl) {
          pillsEl.querySelectorAll('.he-pill').forEach(b => b.classList.remove('is-active'));
        }
        hiddenEl.value = val;
      } else {
        hiddenEl.value = '';
      }
    });
  }

  bindExactInput('first-putt-exact',   'first-putt-pills',   'first-putt-input');
  bindExactInput('approach-dist-exact', 'approach-dist-pills', 'approach-distance-input');
  bindExactInput('second-shot-exact',   'second-shot-pills',   'second-shot-distance-input');

  // Scramble exact — stores integer yardage string
  (function bindExactScramble() {
    const exactEl  = document.getElementById('scramble-dist-exact');
    const hiddenEl = document.getElementById('scramble-distance-input');
    const pillsEl  = document.getElementById('scramble-pills');
    if (!exactEl || !hiddenEl) return;

    exactEl.addEventListener('input', () => {
      const val = parseInt(exactEl.value);
      if (!isNaN(val) && exactEl.value.trim() !== '') {
        if (pillsEl) {
          pillsEl.querySelectorAll('.he-pill').forEach(b => b.classList.remove('is-active'));
        }
        hiddenEl.value = String(val);
      } else {
        hiddenEl.value = '';
      }
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
    const distInput  = document.getElementById('scramble-distance-input');
    const exactEl    = document.getElementById('scramble-dist-exact');
    const pillsEl    = document.getElementById('scramble-pills');
    if (distInput) distInput.value = '';
    if (exactEl)   exactEl.value = '';
    if (pillsEl)   pillsEl.querySelectorAll('.he-pill').forEach(b => b.classList.remove('is-active'));
    clearSandSave();
  }

  function clearSandSave() {
    const sandInput    = document.getElementById('sand-save-input');
    const attemptInput = document.getElementById('sand-save-attempt-input');
    if (sandInput)    sandInput.value = '';
    if (attemptInput) attemptInput.value = '';
    // Deactivate sand save pills
    const sandSaveReveal = document.getElementById('sand-save-reveal');
    if (sandSaveReveal) {
      sandSaveReveal.querySelectorAll('.he-pill').forEach(b => b.classList.remove('is-active'));
    }
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
    update(); // set label on page load
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

    // Restore from server-rendered existing value
    if (input.value) select(input.value);
  })();

});

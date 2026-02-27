/**
 * Magnolia Analytics — Round Entry JavaScript
 * Handles tap-button interactions, steppers, and conditional field visibility.
 */

document.addEventListener('DOMContentLoaded', () => {

  // ── Tap-button groups ─────────────────────────────────────────────────────
  // Each tap-btn has data-field (hidden input name) and data-value.
  document.querySelectorAll('.tap-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.dataset.field;
      const value = btn.dataset.value;

      // Deactivate siblings in the same tap-group
      btn.closest('.tap-group').querySelectorAll('.tap-btn').forEach(b => {
        b.classList.remove('tap-btn--active');
      });
      btn.classList.add('tap-btn--active');

      // Update hidden input
      const input = document.getElementById(`${field.replace(/_/g, '-')}-input`)
                 || document.querySelector(`input[name="${field}"]`);
      if (input) input.value = value;

      // Handle conditional visibility
      if (field === 'gir') handleGirChange(value === 'true');
      if (field === 'approach_miss') handleApproachMissChange(value);
      if (field === 'par') handleParChange(parseInt(value));
    });
  });


  // ── GIR conditional fields ────────────────────────────────────────────────
  function handleGirChange(girMade) {
    const scrambleFields = document.getElementById('scramble-fields');
    if (!scrambleFields) return;

    if (girMade) {
      scrambleFields.classList.add('hidden');
      // Clear scramble inputs when GIR
      const missInput = document.getElementById('approach-miss-input');
      const distInput = document.getElementById('scramble-distance-input');
      const sandInput = document.getElementById('sand-save-input');
      if (missInput) missInput.value = '';
      if (distInput) distInput.value = '';
      if (sandInput) sandInput.value = '';
    } else {
      scrambleFields.classList.remove('hidden');
    }
  }


  // ── Approach miss → show/hide sand save ───────────────────────────────────
  function handleApproachMissChange(missValue) {
    const sandSaveGroup = document.getElementById('sand-save-group');
    if (!sandSaveGroup) return;

    if (missValue === 'bunker') {
      sandSaveGroup.style.display = 'flex';
      sandSaveGroup.style.flexDirection = 'column';
      sandSaveGroup.style.gap = '8px';
    } else {
      sandSaveGroup.style.display = 'none';
      const sandInput = document.getElementById('sand-save-input');
      if (sandInput) sandInput.value = '';
    }
  }


  // ── Par change → show/hide tee shot ──────────────────────────────────────
  function handleParChange(par) {
    const teeShotGroup = document.getElementById('tee-shot-group');
    if (!teeShotGroup) return;

    if (par === 3) {
      teeShotGroup.classList.add('hidden');
      const tsInput = document.getElementById('tee-shot-input');
      if (tsInput) tsInput.value = '';
    } else {
      teeShotGroup.classList.remove('hidden');
    }
  }


  // ── Steppers ─────────────────────────────────────────────────────────────
  function initStepper(downId, upId, displayId, inputId, min, max) {
    const downBtn  = document.getElementById(downId);
    const upBtn    = document.getElementById(upId);
    const display  = document.getElementById(displayId);
    const input    = document.getElementById(inputId);

    if (!downBtn || !upBtn || !display || !input) return;

    function updateDisplay(val) {
      display.textContent = val;
      input.value = val;
    }

    downBtn.addEventListener('click', () => {
      let val = parseInt(input.value) || 0;
      if (val > min) updateDisplay(val - 1);
    });

    upBtn.addEventListener('click', () => {
      let val = parseInt(input.value) || 0;
      if (val < max) updateDisplay(val + 1);
    });
  }

  // Score: min 1, max 15
  initStepper('score-down', 'score-up', 'score-display', 'score-input', 1, 15);

  // Putts: min 0, max 10
  initStepper('putts-down', 'putts-up', 'putts-display', 'putts-input', 0, 10);

  // Penalties: min 0, max 10
  initStepper('penalties-down', 'penalties-up', 'penalties-display', 'penalties-input', 0, 10);


  // ── Sync score stepper with par changes ──────────────────────────────────
  // When par is changed, nudge the score display if it's still at the default
  const parInput = document.getElementById('par-input');
  if (parInput) {
    const observer = new MutationObserver(() => {
      // Score stepper already handles its own state; this is a hook for future use
    });
    observer.observe(parInput, { attributes: true, attributeFilter: ['value'] });
  }


  // ── On load: apply initial conditional state ──────────────────────────────
  const girInput = document.getElementById('gir-input');
  if (girInput) {
    handleGirChange(girInput.value === 'true');
  }

  const approachInput = document.getElementById('approach-miss-input');
  if (approachInput && approachInput.value) {
    handleApproachMissChange(approachInput.value);
  }

  const parVal = document.getElementById('par-input');
  if (parVal) {
    handleParChange(parseInt(parVal.value));
  }


  // ── Haptic feedback (mobile) ──────────────────────────────────────────────
  document.querySelectorAll('.tap-btn, .stepper-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (navigator.vibrate) navigator.vibrate(10);
    });
  });

});

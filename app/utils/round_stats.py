"""
Centralised round statistics computation — single source of truth.

Stats stored on the Round model (all derived from per-hole Hole records):
─────────────────────────────────────────────────────────────────────────
  total_score        : sum of hole scores
  total_putts        : sum of hole putts
  fairways_hit       : par-4/5 holes where tee_shot == 'fairway'
  fairways_available : count of par-4/5 holes
  gir_count          : count of holes where gir is True
  penalties          : sum of hole penalties
  sg_off_tee         : Strokes Gained: Off the Tee (requires yardage lookup)
  sg_approach        : Strokes Gained: Approach
  sg_atg             : Strokes Gained: Around the Green
  sg_putting         : Strokes Gained: Putting (total; band detail is always live)
  sg_total           : sum of all four SG categories
  algo_version       : computation version tag — set to CURRENT_ALGO_VERSION

Not stored — always derived live from hole rows:
─────────────────────────────────────────────────
  score_vs_par       : total_score minus sum of hole pars
  sg_putting bands   : per-distance-band putting breakdown (for charts)
  approach/tee-shot/scramble/first-putt breakdowns (analysis sections)

Rule: reports, dashboards, PB comparisons, and Claude narratives must read
the stored fields above.  They must NEVER recompute summary stats on the fly.
If stored values are absent (algo_version is NULL) the live fallback below
is used until the recompute script is next run.
"""

from app.utils.strokes_gained import (
    strokes_gained_putting,
    strokes_gained_off_tee,
    strokes_gained_approach,
    strokes_gained_around_green,
)

# Increment whenever computation logic changes.
# Rounds with algo_version < CURRENT_ALGO_VERSION (or NULL) are stale.
CURRENT_ALGO_VERSION = 4


def build_course_hole_map(round_):
    """
    Return {hole_number: CourseHole} for the round's tee set.

    Falls back to enumerate-by-id ordering when every stored hole_number
    is 0 — a known issue where the Golf Course API returns hole_number=0
    for all holes.  This fallback assumes rows were inserted in hole order
    (1–18), which matches API behaviour.
    """
    if not round_.tee_set_obj:
        return {}
    chs = round_.tee_set_obj.course_holes.all()
    if not chs:
        return {}
    if all(ch.hole_number == 0 for ch in chs):
        chs_sorted = sorted(chs, key=lambda ch: ch.id)
        return {i + 1: ch for i, ch in enumerate(chs_sorted)}
    return {ch.hole_number: ch for ch in chs}


def compute_all_stats(round_):
    """
    Compute and store every derived stat for a complete round in one pass.

    Covers basic totals (score, putts, GIR, fairways, penalties) and all
    four Strokes Gained categories.  Sets algo_version = CURRENT_ALGO_VERSION
    on success so staleness checks can identify outdated rounds.

    Returns True if stats were written, False if the round has no holes.
    """
    holes = round_.holes.order_by('hole_number').all()
    if not holes:
        return False

    # ── Basic totals ──────────────────────────────────────────────────────
    round_.total_score        = sum(h.score    for h in holes if h.score)
    round_.total_putts        = sum(h.putts     for h in holes if h.putts is not None)
    round_.gir_count          = sum(1           for h in holes if h.gir)
    round_.penalties          = sum(h.penalties for h in holes if h.penalties)
    fw_holes                  = [h for h in holes if h.par in (4, 5) and h.tee_shot is not None]
    round_.fairways_available = len(fw_holes)
    round_.fairways_hit       = sum(1 for h in fw_holes if h.tee_shot == 'fairway')

    # ── Strokes Gained ────────────────────────────────────────────────────
    course_hole_map  = build_course_hole_map(round_)
    sg_putting_data  = strokes_gained_putting(holes)
    sg_ott           = strokes_gained_off_tee(holes, course_hole_map)
    sg_app           = strokes_gained_approach(holes)
    sg_atg           = strokes_gained_around_green(holes)

    round_.sg_putting  = round(sg_putting_data['total'],        3)
    round_.sg_off_tee  = round(sg_ott,                          3)
    round_.sg_approach = round(sg_app,                          3)
    round_.sg_atg      = round(sg_atg,                          3)
    round_.sg_total    = round(sg_ott + sg_app + sg_atg
                               + sg_putting_data['total'],      3)

    round_.algo_version = CURRENT_ALGO_VERSION
    return True

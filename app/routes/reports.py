from flask import Blueprint, render_template, abort, make_response, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.utils.access import is_pro, subscription_required
from app.models.report import Report
from app.models.round import Round
from app.utils.strokes_gained import (
    strokes_gained_putting,
    strokes_gained_off_tee,
    strokes_gained_approach,
    strokes_gained_around_green,
    expected_putts,
    expected_approach,
    expected_ott,
    expected_scramble,
    _tee_shot_lie,
    _parse_yards,
)
import json as _json
from app.utils.round_stats import build_course_hole_map
from app.utils.personal_bests import check_recent_personal_best
from app.services.weather_service import get_round_weather
from app.services.calendar_service import get_calendar_context
from app.services.claude_service import generate_narrative, generate_context_summary

import logging
logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_label(diff) -> str:
    """Return 'E', '+3', '-1' etc. from score-vs-par integer."""
    if diff is None:
        return '—'
    if diff == 0:
        return 'E'
    return f'+{diff}' if diff > 0 else str(diff)


def _hole_score_class(diff: int) -> str:
    """CSS class for scorecard cell colouring."""
    if diff <= -2:
        return 'eagle'
    if diff == -1:
        return 'birdie'
    if diff == 0:
        return 'par'
    if diff == 1:
        return 'bogey'
    return 'double'   # double or worse


def _drive_dist_src(h):
    """Return which field was used for drive distance estimation, for logging."""
    if h.par not in (4, 5):
        return None
    if h.second_shot_distance:
        return 'second_shot'
    if h.approach_distance:
        return 'approach'
    return None


def _est_drive_distance(ch, h):
    """
    Estimate tee-shot distance as hole_yardage minus the distance from which
    the second shot was played.

    Priority:
      1. second_shot_distance — explicitly logged 2nd-shot distance to pin
         (always present on par 5s when recorded; absent on par 4s where the
         approach IS the 2nd shot, so approach_distance doubles as the source)
      2. approach_distance  — fallback when no second_shot_distance is logged

    Only computed for par 4s and 5s. Result must be positive; zero or negative
    means inconsistent data (e.g. shot distance > hole length) — excluded.
    """
    if not (ch and ch.yardage and h.par in (4, 5)):
        return None
    shot_dist = h.second_shot_distance or h.approach_distance
    if not shot_dist:
        return None
    est = ch.yardage - shot_dist
    return est if est > 0 else None


def _build_holes_data(holes, course_hole_map: dict) -> list:
    """
    Build the per-hole context list used by the scorecard and analysis sections.
    course_hole_map: {hole_number: CourseHole}
    """
    result = []
    for h in holes:
        ch = course_hole_map.get(h.hole_number)
        diff = h.score - h.par
        result.append({
            'hole_number':         h.hole_number,
            'par':                 h.par,
            'yardage':             ch.yardage if ch else None,
            'stroke_index':        ch.stroke_index if ch else None,
            'score':               h.score,
            'score_vs_par':        diff,
            'score_class':         _hole_score_class(diff),
            'score_label':         h.score_label,
            'tee_shot':            h.tee_shot,
            'gir':                 h.gir,
            'putts':               h.putts,
            'first_putt_distance': h.first_putt_distance,
            'approach_distance':   h.approach_distance,
            'approach_miss':       h.approach_miss,
            'scramble_distance':   h.scramble_distance,
            'second_shot_distance': h.second_shot_distance,
            'sand_save_attempt':   h.sand_save_attempt,
            'sand_save_made':      h.sand_save_made,
            'penalties':           h.penalties,
            'lie_type':            h.lie_type,
            'est_drive_distance':  _est_drive_distance(ch, h),
            'drive_dist_src':      _drive_dist_src(h),
        })
    return result


def _split_totals(holes_data: list) -> dict:
    """Compute front 9 / back 9 / total summary rows."""
    def _sum(subset):
        return {
            'score':   sum(h['score']        for h in subset),
            'par':     sum(h['par']          for h in subset),
            'putts':   sum(h['putts'] or 0   for h in subset),
            'gir':     sum(1 for h in subset if h['gir']),
            'yardage': sum(h['yardage'] or 0 for h in subset),
        }

    front = [h for h in holes_data if h['hole_number'] <= 9]
    back  = [h for h in holes_data if h['hole_number'] >= 10]

    def _enrich(s):
        s['score_vs_par'] = s['score'] - s['par']
        s['score_label']  = _score_label(s['score_vs_par'])
        return s

    return {
        'front': _enrich(_sum(front)) if front else None,
        'back':  _enrich(_sum(back))  if back  else None,
        'total': _enrich(_sum(holes_data)),
    }


def _tee_shot_gir_breakdown(holes_data: list, hole_sg_by_num: dict = None) -> dict:
    """GIR hit rate segmented by tee-shot outcome. Optionally includes SG per outcome."""
    cats = {'fairway': [0, 0], 'left': [0, 0], 'right': [0, 0],
            'penalty': [0, 0], 'other': [0, 0]}
    sg_by_cat: dict = {k: [] for k in cats}
    for h in holes_data:
        if h['par'] not in (4, 5):
            continue
        ts  = h['tee_shot'] or 'other'
        key = ts if ts in cats else 'other'
        cats[key][0] += 1
        if h['gir']:
            cats[key][1] += 1
        if hole_sg_by_num:
            sg_val = hole_sg_by_num.get(h['hole_number'], {}).get('sg_ott')
            if sg_val is not None:
                sg_by_cat[key].append(sg_val)
    result = {}
    for k, (attempts, girs) in cats.items():
        if attempts:
            sg_vals = sg_by_cat.get(k, [])
            result[k] = {
                'attempts': attempts,
                'girs':     girs,
                'gir_pct':  round(girs / attempts * 100),
                'sg':       round(sum(sg_vals), 2) if sg_vals else None,
            }
    return result


def _approach_distance_breakdown(holes_data: list, hole_sg_by_num: dict = None) -> list:
    """Shots grouped into distance bands with GIR rates. Optionally includes SG per band."""
    bands = [
        ('< 75 yds',    0,   75),
        ('75–100 yds',  75,  100),
        ('100–125 yds', 100, 125),
        ('125–150 yds', 125, 150),
        ('150–175 yds', 150, 175),
        ('175+ yds',    175, 9999),
    ]
    result = []
    for label, lo, hi in bands:
        subset = [
            h for h in holes_data
            if h['approach_distance'] is not None
            and lo <= h['approach_distance'] < hi
        ]
        if not subset:
            continue
        girs = sum(1 for h in subset if h['gir'])
        sg_total = None
        if hole_sg_by_num:
            sg_vals = [
                hole_sg_by_num[h['hole_number']]['sg_approach']
                for h in subset
                if hole_sg_by_num.get(h['hole_number'], {}).get('sg_approach') is not None
            ]
            if sg_vals:
                sg_total = round(sum(sg_vals), 2)
        result.append({
            'label':    label,
            'attempts': len(subset),
            'girs':     girs,
            'gir_pct':  round(girs / len(subset) * 100),
            'sg':       sg_total,
        })
    return result


def _miss_direction_counts(holes_data: list) -> dict:
    """Count approach miss directions (GIR misses only)."""
    counts = {}
    for h in holes_data:
        if not h['gir'] and h['approach_miss']:
            counts[h['approach_miss']] = counts.get(h['approach_miss'], 0) + 1
    return counts


def _scramble_stats(holes_data: list) -> dict:
    """Scramble (par-or-better save rate) from GIR misses."""
    misses = [h for h in holes_data if not h['gir']]
    if not misses:
        return {'attempts': 0, 'saves': 0, 'save_pct': None}
    saves = sum(1 for h in misses if h['score_vs_par'] <= 0)
    return {
        'attempts': len(misses),
        'saves':    saves,
        'save_pct': round(saves / len(misses) * 100),
    }


def _sand_save_stats(holes_data: list) -> dict:
    """
    Sand save stats from explicit sand_save fields OR bunker lie_type detection.
    Uses score_vs_par <= 0 as save proxy when sand_save_made is not recorded.
    """
    attempts = []
    for h in holes_data:
        is_bunker = h.get('sand_save_attempt') or (
            not h.get('gir')
            and h.get('lie_type')
            and 'bunker' in h['lie_type'].lower()
        )
        if is_bunker:
            attempts.append(h)
    if not attempts:
        return {'attempts': 0, 'saves': 0, 'save_pct': None}
    saves = 0
    for h in attempts:
        if h.get('sand_save_made') is not None:
            saves += 1 if h['sand_save_made'] else 0
        else:
            saves += 1 if h.get('score_vs_par', 1) <= 0 else 0
    return {
        'attempts': len(attempts),
        'saves':    saves,
        'save_pct': round(saves / len(attempts) * 100) if attempts else None,
    }


def _putting_distribution(holes_data: list) -> dict:
    """Count of holes by putts (1, 2, 3, 4+)."""
    dist = {1: 0, 2: 0, 3: 0, '4+': 0}
    for h in holes_data:
        p = h['putts']
        if p <= 1:
            dist[1] += 1
        elif p == 2:
            dist[2] += 1
        elif p == 3:
            dist[3] += 1
        else:
            dist['4+'] += 1
    return dist


def _first_putt_profile(holes_data: list) -> list:
    """Average putts and make-rate by first-putt distance band."""
    bands = [
        ('0–6 ft',   0,  6),
        ('6–10 ft',  6,  10),
        ('10–15 ft', 10, 15),
        ('15–30 ft', 15, 30),
        ('30+ ft',   30, 9999),
    ]
    result = []
    for label, lo, hi in bands:
        subset = [
            h for h in holes_data
            if h['first_putt_distance'] is not None
            and lo <= h['first_putt_distance'] < hi
        ]
        if not subset:
            continue
        makes     = sum(1 for h in subset if h['putts'] == 1)
        avg_putts = round(sum(h['putts'] for h in subset) / len(subset), 2)
        result.append({
            'label':     label,
            'attempts':  len(subset),
            'makes':     makes,
            'make_pct':  round(makes / len(subset) * 100),
            'avg_putts': avg_putts,
        })
    return result


def _par_type_gir_breakdown(holes_data: list) -> dict:
    """GIR count and rate segmented by par type."""
    result = {}
    for par in (3, 4, 5):
        subset = [h for h in holes_data if h['par'] == par]
        if not subset:
            continue
        girs = sum(1 for h in subset if h['gir'])
        result[par] = {
            'holes':   len(subset),
            'girs':    girs,
            'gir_pct': round(girs / len(subset) * 100),
        }
    return result


def _lie_type_breakdown(holes_data: list) -> dict:
    """Lie type frequency from GIR misses (comma-separated lie_type field)."""
    counts: dict = {}
    for h in holes_data:
        if not h['gir'] and h.get('lie_type'):
            for lt in h['lie_type'].split(','):
                lt = lt.strip()
                if lt:
                    counts[lt] = counts.get(lt, 0) + 1
    return counts


def _par5_analysis(holes_data: list) -> dict:
    """Par 5 per-hole detail and scoring average."""
    par5s = [h for h in holes_data if h['par'] == 5]
    if not par5s:
        return {'holes': [], 'avg_score_vs_par': None, 'count': 0}
    avg_svp = round(sum(h['score_vs_par'] for h in par5s) / len(par5s), 2)
    holes_detail = []
    for h in par5s:
        sd = h.get('approach_distance')   # treat approach_distance as 2nd-shot dist on par 5
        heuristic = None
        if sd is not None:
            heuristic = 'On/near green' if sd < 100 else 'Layup / long second'
        holes_detail.append({
            'hole_number':      h['hole_number'],
            'score':            h['score'],
            'score_vs_par':     h['score_vs_par'],
            'score_label':      h['score_label'],
            'gir':              h['gir'],
            'second_shot_dist': sd,
            'heuristic':        heuristic,
        })
    return {'holes': holes_detail, 'avg_score_vs_par': avg_svp, 'count': len(par5s)}


def _scoring_by_par_type(holes_data: list) -> dict:
    """Scoring distribution and average by par type."""
    result = {}
    for par in (3, 4, 5):
        subset = [h for h in holes_data if h['par'] == par]
        if not subset:
            continue
        avg_svp = round(sum(h['score_vs_par'] for h in subset) / len(subset), 2)
        result[par] = {
            'count':   len(subset),
            'avg_svp': avg_svp,
            'eagles':  sum(1 for h in subset if h['score_vs_par'] <= -2),
            'birdies': sum(1 for h in subset if h['score_vs_par'] == -1),
            'pars':    sum(1 for h in subset if h['score_vs_par'] == 0),
            'bogeys':  sum(1 for h in subset if h['score_vs_par'] == 1),
            'doubles': sum(1 for h in subset if h['score_vs_par'] >= 2),
        }
    return result


def _build_shot_circles(h, course_hole_map: dict) -> list:
    """
    Build a per-shot SG circle list from shots_json using the telescoping Broadie formula.

    Each circle dict:
      label     – display label (OTT / App / ATG / Putt / Gimme)
      sg        – float or None (None = gimme, shown as grey 0.00)
      is_gimme  – bool
      detail    – short descriptor string for the popover

    Falls back to [] if shots_json is missing or unparseable — the caller
    then falls through to the legacy aggregate dots.
    """
    STANDARD_GIMME_FT = 3

    try:
        shots = _json.loads(h.shots_json or '[]')
    except (ValueError, TypeError):
        return []
    if not shots:
        return []

    ch           = course_hole_map.get(h.hole_number)
    hole_yardage = ch.yardage if (ch and ch.yardage) else None
    circles      = []

    def _exp_end(i):
        """Expected strokes from the end position of shots[i] = start of shots[i+1]."""
        if i + 1 >= len(shots):
            return 0.0          # ball is in the hole
        nxt = shots[i + 1]
        t   = nxt.get('type')
        if t == 'gimme':
            d = nxt.get('gimme_distance') or STANDARD_GIMME_FT
            return expected_putts(float(d))
        if t == 'putt':
            d = nxt.get('putt_distance')
            return expected_putts(float(d)) if d else None
        if t == 'app':
            d = nxt.get('distance')
            if d:
                lie = _tee_shot_lie(h.tee_shot) if h.tee_shot else 'fairway'
                return expected_approach(float(d), lie)
            return None
        if t == 'atg':
            d   = nxt.get('distance')
            lie = nxt.get('lie') or 'rough'
            return expected_scramble(float(d), lie) if d else None
        return None

    for i, shot in enumerate(shots):
        t = shot.get('type')

        if t == 'gimme':
            gd = shot.get('gimme_distance')
            circles.append({
                'label':    'Gimme',
                'sg':       None,
                'is_gimme': True,
                'detail':   f"Conceded at {gd}ft" if gd else "Conceded (≤3ft)",
            })

        elif t == 'ott':
            if not hole_yardage:
                continue
            exp_end = _exp_end(i)
            if exp_end is None:
                continue
            sg = round(expected_ott(hole_yardage) - 1 - exp_end, 3)
            outcome = h.tee_shot or 'Tee shot'
            circles.append({'label': 'OTT', 'sg': sg, 'is_gimme': False,
                             'detail': outcome.replace(',', ' ').title()})

        elif t == 'app':
            d = shot.get('distance')
            if not d:
                continue
            # Lie: after a trees OTT (or any OTT with a stored lie on this shot),
            # prefer the shot's own recorded lie so the approach is evaluated on
            # where the ball actually ended up, not the tee-shot outcome.
            prev = shots[i - 1] if i > 0 else None
            if prev and prev.get('type') == 'ott':
                primary = (h.tee_shot or '').split(',')[0]
                if primary == 'trees':
                    lie = shot.get('lie') or 'fairway'
                else:
                    lie = _tee_shot_lie(h.tee_shot) if h.tee_shot else 'fairway'
            else:
                lie = shot.get('lie') or 'fairway'
            exp_end = _exp_end(i)
            if exp_end is None:
                continue
            sg = round(expected_approach(float(d), lie) - 1 - exp_end, 3)
            circles.append({'label': 'App', 'sg': sg, 'is_gimme': False,
                             'detail': f"{d}y"})

        elif t == 'atg':
            d   = shot.get('distance')
            lie = shot.get('lie') or 'rough'
            if not d:
                continue
            exp_end = _exp_end(i)
            if exp_end is None:
                continue
            sg = round(expected_scramble(float(d), lie) - 1 - exp_end, 3)
            circles.append({'label': 'ATG', 'sg': sg, 'is_gimme': False,
                             'detail': f"{d}y · {lie}"})

        elif t == 'putt':
            d = shot.get('putt_distance')
            if not d:
                continue    # no distance — can't compute individual SG
            exp_end = _exp_end(i)
            if exp_end is None:
                continue
            sg = round(expected_putts(float(d)) - 1 - exp_end, 3)
            circles.append({'label': 'Putt', 'sg': sg, 'is_gimme': False,
                             'detail': f"{d}ft"})

    return circles


def _per_hole_sg(holes, course_hole_map: dict) -> list:
    """Compute per-hole SG values for putting, approach, off-the-tee, and ATG.
    Returns list of dicts keyed by hole_number; values are None when not computable."""
    result = []
    for h in holes:
        ch = course_hole_map.get(h.hole_number)
        row: dict = {
            'hole_number':  h.hole_number,
            'par':          h.par,
            'sg_putt':      None,
            'sg_ott':       None,
            'sg_approach':  None,
            'sg_atg':       None,
            'shot_circles': [],
        }

        # Gimme helpers — first_putt_distance may be blank on legacy gimme holes
        is_gimme  = getattr(h, 'last_putt_gimme', False)
        gimme_d   = getattr(h, 'gimme_distance', None) or 3
        # Effective first-putt distance: stored value, or gimme distance fallback
        fpd = h.first_putt_distance or (gimme_d if is_gimme else None)

        # SG: Putting
        if fpd and h.putts:
            if is_gimme:
                actual = h.putts - 1
                if actual > 0:
                    row['sg_putt'] = round(
                        expected_putts(fpd) - actual - expected_putts(gimme_d), 3)
            else:
                row['sg_putt'] = round(expected_putts(fpd) - h.putts, 3)

        # SG: Off the Tee (par 4/5 only)
        if h.par in (4, 5) and h.tee_shot:
            lie       = _tee_shot_lie(h.tee_shot)
            remaining = (h.approach_distance if h.par == 4
                         else _parse_yards(h.second_shot_distance))
            yardage   = ch.yardage if (ch and ch.yardage) else None
            if yardage and remaining:
                row['sg_ott'] = round(
                    expected_ott(yardage) - 1 - expected_approach(remaining, lie), 3)

        # SG: Approach
        dist    = h.approach_distance
        _primary_ts = (h.tee_shot or '').split(',')[0]
        # Trees tee shots: approach is evaluated on where the ball lies after recovery,
        # not on the tee-shot outcome — use lie_type when available.
        if h.tee_shot and h.par in (4, 5):
            lie = (h.lie_type or 'fairway') if _primary_ts == 'trees' else _tee_shot_lie(h.tee_shot)
        else:
            lie = 'fairway'
        atg_lie = 'bunker' if h.approach_miss == 'bunker' else 'rough'
        sdist   = _parse_yards(h.scramble_distance)

        if h.par == 3 and dist:
            exp_start = expected_approach(dist, 'fairway')
            if h.gir and fpd:
                row['sg_approach'] = round(exp_start - 1 - expected_putts(fpd), 3)
            elif not h.gir and sdist:
                row['sg_approach'] = round(exp_start - 1 - expected_scramble(sdist, atg_lie), 3)
        elif h.par in (4, 5):
            if h.gir and dist and fpd:
                row['sg_approach'] = round(
                    expected_approach(dist, lie) - 1 - expected_putts(fpd), 3)
            elif not h.gir and dist and sdist:
                row['sg_approach'] = round(
                    expected_approach(dist, lie) - 1 - expected_scramble(sdist, atg_lie), 3)

        # SG: Around the Green (GIR misses only)
        if not h.gir and sdist and fpd:
            row['sg_atg'] = round(
                expected_scramble(sdist, atg_lie) - 1 - expected_putts(fpd), 3)

        # Per-shot circles from shots_json (used in template)
        row['shot_circles'] = _build_shot_circles(h, course_hole_map)

        result.append(row)
    return result


def _historical_hole_sg_at_course(round_, prev_rounds: list, course_hole_map: dict) -> dict:
    """
    For each hole number, compute average SG total across previous rounds at the
    same course (up to last 10). Reuses the current course_hole_map since the
    course layout is the same.

    Returns {hole_number: {'sg_avg': float, 'count': int}}.
    """
    if not round_.course_id:
        return {}
    same_course = [r for r in prev_rounds if r.course_id == round_.course_id][:10]
    if not same_course:
        return {}

    accumulator: dict = {}
    for prev_round in same_course:
        prev_holes = prev_round.holes.order_by('hole_number').all()
        if not prev_holes:
            continue
        for row in _per_hole_sg(prev_holes, course_hole_map):
            sg_vals = [row[k] for k in ('sg_putt', 'sg_ott', 'sg_approach', 'sg_atg')
                       if row.get(k) is not None]
            if sg_vals:
                accumulator.setdefault(row['hole_number'], []).append(round(sum(sg_vals), 2))

    return {
        hn: {'sg_avg': round(sum(vals) / len(vals), 2), 'count': len(vals)}
        for hn, vals in accumulator.items()
        if vals
    }


def _top_sg_moments(hole_sg: list, n: int = 3) -> list:
    """Return the top n SG shots across all categories, sorted best first."""
    _cat_labels = {
        'sg_putt':     'Putting',
        'sg_ott':      'Off the Tee',
        'sg_approach': 'Approach',
        'sg_atg':      'Around the Green',
    }
    moments = []
    for row in hole_sg:
        for cat, label in _cat_labels.items():
            val = row.get(cat)
            if val is not None:
                moments.append({
                    'hole_number': row['hole_number'],
                    'par':         row['par'],
                    'category':    label,
                    'sg':          val,
                })
    return sorted(moments, key=lambda x: x['sg'], reverse=True)[:n]


def _sg_bar_width(sg_value: float, scale: float = 8.0) -> int:
    """
    Map an SG value to a percentage bar width (0–100).
    scale = SG value that maps to 100% of one side of the centred bar.
    """
    clamped = max(-scale, min(scale, sg_value))
    return round(abs(clamped) / scale * 100)


def _weakest_sg_category(sg_data: dict):
    """Return the display name of the weakest SG category, or None if insufficient data."""
    categories = {
        'Off the Tee':      sg_data.get('sg_off_tee'),
        'Approach':         sg_data.get('sg_approach'),
        'Around the Green': sg_data.get('sg_atg'),
        'Putting':          sg_data.get('sg_putting', {}).get('total'),
    }
    valid = {name: val for name, val in categories.items() if val is not None}
    if not valid:
        return None
    return min(valid, key=valid.get)


def _build_historical_context(round_, prev_rounds: list) -> dict:
    """
    Assemble historical baseline data for the Claude narrative prompt.

    prev_rounds: all completed rounds for this user ordered most-recent first,
                 excluding the current round (already queried by the caller).

    Returns a dict consumed by claude_service._build_narrative_prompt.
    When round_count < 20 only the count is included — history is too thin
    for averages to be meaningful.
    """
    round_count = len(prev_rounds) + 1   # include the current round
    ctx = {'round_count': round_count}

    # Per-category SG averages and sparklines — computed regardless of round_count.
    # Averages shown only when >= 5 previous rounds have data for that category.
    # Sparkline shown only when total data points (prev + current) >= 5.
    _sg_cat_defs = [
        ('sg_off_tee',  round_.sg_off_tee),
        ('sg_approach', round_.sg_approach),
        ('sg_atg',      round_.sg_atg),
        ('sg_putting',  round_.sg_putting),
    ]
    for cat, curr_val in _sg_cat_defs:
        cat_vals = [getattr(r, cat) for r in prev_rounds if getattr(r, cat) is not None]
        count = len(cat_vals)
        ctx[f'avg_{cat}'] = round(sum(cat_vals) / count, 2) if count >= 5 else None
        ctx[f'{cat}_count'] = count
        # Sparkline: up to 4 most-recent previous rounds (reversed to oldest-first) + current
        prev_with_data = [round(v, 2) for v in cat_vals[:4]]
        spark = list(reversed(prev_with_data))
        if curr_val is not None:
            spark.append(round(curr_val, 2))
        ctx[f'sparkline_{cat}'] = spark if len(spark) >= 5 else []

    # Basic per-round averages — available from 3+ previous rounds
    _putts_vals = [r.total_putts for r in prev_rounds if r.total_putts is not None]
    if len(_putts_vals) >= 3:
        ctx['avg_total_putts'] = round(sum(_putts_vals) / len(_putts_vals), 1)
    _gir_vals = [
        r.gir_count / r.holes_played
        for r in prev_rounds
        if r.gir_count is not None and r.holes_played
    ]
    if len(_gir_vals) >= 3:
        ctx['avg_gir_pct'] = round(sum(_gir_vals) / len(_gir_vals) * 100, 1)

    if round_count < 20 or not prev_rounds:
        return ctx

    # Averages across all previous rounds that have complete data
    scored = [r for r in prev_rounds if r.total_score is not None]

    scores_vp = [v for v in (r.score_vs_par() for r in scored) if v is not None]
    sg_totals  = [r.sg_total   for r in scored if r.sg_total   is not None]
    putts_list = [r.total_putts for r in scored if r.total_putts is not None]
    gir_rates  = [
        r.gir_count / r.holes_played
        for r in scored
        if r.gir_count is not None and r.holes_played
    ]

    ctx['avg_score_vs_par'] = round(sum(scores_vp) / len(scores_vp), 1) if scores_vp else None
    ctx['avg_sg_total']     = round(sum(sg_totals)  / len(sg_totals),  2) if sg_totals  else None
    ctx['avg_putts']        = round(sum(putts_list) / len(putts_list), 1) if putts_list else None
    ctx['avg_gir_pct']      = round(sum(gir_rates)  / len(gir_rates) * 100, 1) if gir_rates else None

    # Recent form — last 5 rounds
    recent = prev_rounds[:5]
    ctx['recent_scores'] = [
        {
            'date':         r.date_played.strftime('%d %b %Y'),
            'course':       r.course.name if r.course else 'Unknown',
            'score_vs_par': r.score_vs_par(),
            'sg_total':     r.sg_total,
        }
        for r in recent if r.total_score is not None
    ]
    ctx['recent_differentials'] = [
        round(r.hc_differential, 1)
        for r in recent
        if r.hc_differential is not None
    ]

    return ctx


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@reports_bp.route('/<int:round_id>')
@login_required
def view_report(round_id):
    """
    Live round report — assembled from DB data, rendered via Jinja2.

    On first view: fetches weather (cached in report.weather_json) and
    generates Claude narrative (cached in report.narrative_text).
    Subsequent views are served entirely from cached DB values.
    """
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    # Ensure a Report record exists
    report = round_.report
    if not report:
        report = Report(round_id=round_.id, email_status='pending')
        db.session.add(report)
        db.session.flush()

    # ---- Hole data ----
    holes = round_.holes.order_by('hole_number').all()
    if not holes:
        abort(404)

    # CourseHole yardages — use enumerate fallback when hole_number=0 (Golf Course API issue)
    course_hole_map = build_course_hole_map(round_)

    holes_data = _build_holes_data(holes, course_hole_map)
    split      = _split_totals(holes_data)

    user_is_pro = is_pro(current_user)

    # ---- Strokes Gained ----
    # SG Off the Tee is available to all tiers.
    # SG Approach, ATG, Putting, and Total are Pro-only.
    # For free users, paid SG fields are set to None so they are never
    # included in the rendered HTML — the gate is server-side, not CSS-only.
    sg_putting_data = strokes_gained_putting(holes)

    if round_.sg_off_tee is not None:
        sg_off_tee  = round_.sg_off_tee
        sg_approach = round_.sg_approach if user_is_pro else None
        sg_atg      = round_.sg_atg      if user_is_pro else None
        sg_total    = round_.sg_total    if user_is_pro else None
        sg_putting  = ({'total': round_.sg_putting, 'bands': sg_putting_data['bands']}
                       if user_is_pro else {'total': None, 'bands': {}})
    else:
        # Live fallback for rounds without stored SG (algo_version is NULL)
        sg_off_tee  = strokes_gained_off_tee(holes, course_hole_map)
        if user_is_pro:
            sg_approach = strokes_gained_approach(holes)
            sg_atg      = strokes_gained_around_green(holes)
            sg_putting  = sg_putting_data
            sg_total    = round(sg_off_tee + sg_approach + sg_atg + sg_putting['total'], 2)
        else:
            sg_approach = None
            sg_atg      = None
            sg_putting  = {'total': None, 'bands': {}}
            sg_total    = None

    sg_data = {
        'sg_off_tee':  sg_off_tee,
        'sg_approach': sg_approach,
        'sg_atg':      sg_atg,
        'sg_putting':  sg_putting,
        'sg_total':    sg_total,
    }

    sg_bars = {
        'off_tee':  {'value': sg_off_tee,  'width': _sg_bar_width(sg_off_tee),  'positive': sg_off_tee  >= 0},
        'approach': {'value': sg_approach, 'width': _sg_bar_width(sg_approach or 0), 'positive': (sg_approach or 0) >= 0},
        'atg':      {'value': sg_atg,      'width': _sg_bar_width(sg_atg or 0),      'positive': (sg_atg or 0)      >= 0},
        'putting':  {'value': sg_putting['total'], 'width': _sg_bar_width(sg_putting['total'] or 0), 'positive': (sg_putting['total'] or 0) >= 0},
        'total':    {'value': sg_total,    'width': _sg_bar_width(sg_total or 0, scale=20),           'positive': (sg_total or 0) >= 0},
    }

    # ---- Per-hole SG (used for top moments, best-shot callouts, band SG) ----
    hole_sg         = _per_hole_sg(holes, course_hole_map)
    # Enrich each row with a hole-level SG total.
    # When shot_circles are present use their sum so the displayed circles and
    # the hole total are always consistent (multiple shots of the same category
    # would otherwise cause the category aggregate and circle values to diverge).
    for row in hole_sg:
        circles = row.get('shot_circles', [])
        if circles:
            circle_sum = sum(
                c['sg'] for c in circles
                if not c.get('is_gimme') and c.get('sg') is not None
            )
            row['sg_hole_total'] = round(circle_sum, 2)
        else:
            sg_vals = [row[k] for k in ('sg_putt', 'sg_ott', 'sg_approach', 'sg_atg')
                       if row.get(k) is not None]
            row['sg_hole_total'] = round(sum(sg_vals), 2) if sg_vals else None
    hole_sg_by_num  = {h['hole_number']: h for h in hole_sg}
    top_sg_moments  = _top_sg_moments(hole_sg, n=3)

    # Best shot per category (highest SG in each)
    best_sg_by_cat: dict = {}
    for cat in ('sg_putt', 'sg_ott', 'sg_approach', 'sg_atg'):
        candidates = [(h[cat], h['hole_number'], h['par'])
                      for h in hole_sg if h.get(cat) is not None]
        if candidates:
            best = max(candidates, key=lambda x: x[0])
            best_sg_by_cat[cat] = {'sg': best[0], 'hole_number': best[1], 'par': best[2]}

    # ---- Analysis sections ----
    # Approach distance breakdown and miss analysis are Pro-only.
    # Free users receive empty collections so no data leaks into the HTML.
    tee_gir      = _tee_shot_gir_breakdown(holes_data, hole_sg_by_num)
    approach_bds = _approach_distance_breakdown(holes_data, hole_sg_by_num) if user_is_pro else []
    miss_dirs    = _miss_direction_counts(holes_data) if user_is_pro else {}
    scramble     = _scramble_stats(holes_data)
    sand_stats   = _sand_save_stats(holes_data)
    # Average scramble distance (GIR-miss holes only), parsed via _parse_yards to handle band keys
    _sdist_vals  = [_parse_yards(h['scramble_distance']) for h in holes_data
                    if not h['gir'] and h['scramble_distance'] is not None]
    _sdist_vals  = [v for v in _sdist_vals if v is not None]
    avg_scramble_dist = round(sum(_sdist_vals) / len(_sdist_vals)) if _sdist_vals else None
    putt_dist    = _putting_distribution(holes_data)
    first_putt   = _first_putt_profile(holes_data) if user_is_pro else []
    weakest_sg   = _weakest_sg_category(sg_data)
    par_type_gir  = _par_type_gir_breakdown(holes_data)
    lie_types     = _lie_type_breakdown(holes_data)
    par5_stats    = _par5_analysis(holes_data) or {'count': 0, 'holes': [], 'avg_score_vs_par': None}
    scoring_by_par = _scoring_by_par_type(holes_data)

    # Estimated drive distances: hole_yardage − second_shot_distance (fallback: approach_distance)
    _drive_holes = [h for h in holes_data if h.get('est_drive_distance') is not None]
    avg_drive_dist = round(sum(h['est_drive_distance'] for h in _drive_holes) / len(_drive_holes)) if _drive_holes else None
    for _dh in _drive_holes:
        logger.info(
            'DRIVE EST hole=%s par=%s yardage=%s src=%s shot_dist=%s est=%s',
            _dh['hole_number'], _dh['par'], _dh['yardage'],
            _dh.get('drive_dist_src'),
            (_dh['yardage'] - _dh['est_drive_distance']) if _dh['yardage'] else '?',
            _dh['est_drive_distance'],
        )

    # Average approach distance left after tee shot (par 4s and 5s)
    _app_dists = [h['approach_distance'] for h in holes_data
                  if h['par'] in (4, 5) and h['approach_distance'] is not None]
    avg_approach_after_tee = round(sum(_app_dists) / len(_app_dists)) if _app_dists else None

    # ---- Weather (fetch once, cache in report.weather_json) ----
    weather = get_round_weather(round_)

    # ---- Calendar context ----
    calendar_ctx = get_calendar_context(round_.date_played)

    # ---- Previous rounds (needed for both historical context and personal best) ----
    prev_rounds = (
        Round.query
        .filter(Round.user_id == current_user.id,
                Round.status == 'complete',
                Round.id != round_.id)
        .order_by(Round.date_played.desc())
        .all()
    )
    historical_ctx = _build_historical_context(round_, prev_rounds)
    # Per-hole historical SG at this course (Pro only — requires hole queries for prev rounds)
    historical_hole_sg = (
        _historical_hole_sg_at_course(round_, prev_rounds, course_hole_map)
        if user_is_pro else {}
    )

    # ---- Claude-generated text (Pro-only; lazy-generate on first view, cached after) ----
    # Free users receive None for both fields — no API call is made, no cached
    # text is served. The template shows an upgrade prompt instead.
    #
    # NARRATIVE_VERSION: bump this integer whenever coaching prompt logic changes
    # significantly. Any stored narrative with a lower version is discarded and
    # regenerated on the next report view, then stamped so it only regenerates once.
    NARRATIVE_VERSION = 2

    summary_text = None
    narrative    = None
    if user_is_pro:
        if not report.summary_text:
            summary_text = generate_context_summary(round_, weather, calendar_ctx)
            report.summary_text = summary_text
        else:
            summary_text = report.summary_text

        # Clear stale narrative when version is behind current
        if (report.narrative_version or 0) < NARRATIVE_VERSION:
            report.narrative_text = None

        if not report.narrative_text:
            narrative = generate_narrative(round_, sg_data, historical_ctx)
            report.narrative_text     = narrative
            report.narrative_version  = NARRATIVE_VERSION
        else:
            narrative = report.narrative_text

    db.session.commit()

    # ---- Derived display values ----
    score_vs_par = round_.score_vs_par()
    # Par: sum actual hole pars (from CourseHole API data, stored on each Hole record).
    # This is correct for both 18-hole and 9-hole rounds and reflects the true course par.
    # Fall back to tee set / course level only when hole data is absent.
    if holes_data:
        par = sum(h['par'] for h in holes_data)
    elif round_.tee_set_obj:
        par = round_.tee_set_obj.total_par
    elif round_.course:
        par = round_.course.par
    else:
        par = 72
    course_name = round_.course.name if round_.course else 'Unknown Course'

    pb_banner = check_recent_personal_best(round_, prev_rounds)

    return render_template(
        'reports/report.html',

        # Access gate — controls both server-side data and template presentation.
        # Paid SG fields, narrative, and analysis data are already None for free
        # users above. This flag drives the upgrade-prompt UI in the template.
        user_is_pro = user_is_pro,

        # Round
        round             = round_,
        user              = current_user,
        course_name       = course_name,
        course_name_upper = course_name.upper()[:14],
        par               = par,
        score_vs_par      = score_vs_par,
        score_vs_par_label = _score_label(score_vs_par),

        # Holes
        holes_data = holes_data,
        split      = split,

        # Strokes gained
        sg_data    = sg_data,
        sg_bars    = sg_bars,
        weakest_sg = weakest_sg,

        # Analysis
        tee_gir      = tee_gir,
        approach_bds = approach_bds,
        miss_dirs    = miss_dirs,
        scramble     = scramble,
        putt_dist    = putt_dist,
        first_putt   = first_putt,
        par_type_gir          = par_type_gir,
        lie_types             = lie_types,
        par5_stats            = par5_stats,
        scoring_by_par        = scoring_by_par,
        avg_drive_dist        = avg_drive_dist,
        avg_approach_after_tee = avg_approach_after_tee,
        avg_scramble_dist     = avg_scramble_dist,
        sand_stats            = sand_stats,
        historical_hole_sg    = historical_hole_sg,

        # Context
        weather      = weather,
        calendar_ctx = calendar_ctx,
        summary_text = summary_text,
        narrative    = narrative,

        # Historical context (per-category SG averages + sparklines)
        historical_ctx = historical_ctx,

        # Personal best
        pb_banner    = pb_banner,

        # Per-hole SG (top moments + best-shot callouts + shot-by-shot breakdown)
        top_sg_moments  = top_sg_moments,
        best_sg_by_cat  = best_sg_by_cat,
        hole_sg_by_num  = hole_sg_by_num,
    )


@reports_bp.route('/<int:round_id>/html')
@login_required
def view_report_html(round_id):
    """
    Serve the legacy Claude-generated HTML blob (email preview / iframe).
    Redirects to the live report if no html_content exists.
    """
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    report = round_.report

    if not report or not report.html_content:
        return redirect(url_for('reports.view_report', round_id=round_id))

    response = make_response(report.html_content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

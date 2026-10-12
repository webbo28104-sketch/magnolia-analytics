"""
Per-shot Strokes Gained — the single source of truth for every SG figure.

Every logged shot gets its own SG value using Broadie's formula:

    SG(shot) = E(start) - 1 - penalty_strokes - E(start of next shot)

where E() is the PGA Tour expected strokes to hole out from that position
(baseline tables in app/utils/strokes_gained.py) and E = 0 once holed.

Because the formula telescopes, the SG values of a fully-measured hole sum to
E(tee) - score, and a round's category totals are simply the sum of its shot
values — so every breakdown (distance band, lie, club) adds up to the category
totals shown on the report.

Missing data
------------
Distances are optional in shot entry. When a shot's start distance is unknown
we cannot value it on its own, so it is merged into the previous shot's block:
the block is valued as a whole and credited to its first shot (e.g. a 22 ft
putt followed by an unmeasured tap-in becomes one 2-stroke block from 22 ft).
Blocks are only formed within one category; a block that would span two
categories is left unvalued (sg=None) rather than mis-attributed.

Holes without shots_json (logged before shot-by-shot entry) are rebuilt from
the legacy hole fields by reconstruct_shots().
"""

import json

from app.utils.strokes_gained import (
    expected_putts,
    expected_approach,
    expected_ott,
    expected_scramble,
    _parse_yards,
)

STANDARD_GIMME_FT = 3
ASSUMED_FIRST_PUTT_FT = 20   # used only to value the shot onto the green when no putt distance was logged
APP_LIES = ('fairway', 'rough', 'bunker', 'recovery')
CATEGORIES = ('ott', 'app', 'atg', 'putt')
CATEGORY_LABELS = {
    'ott':  'Off the tee',
    'app':  'Approach',
    'atg':  'Short game',
    'putt': 'Putting',
}


def expected_short_game(distance_yds, lie):
    """
    Tour expected strokes for a shot around the green, by lie:
    bunker → ATG bunker baseline; rough → rough baseline (chips from rough are
    harder than from tight lies); fringe/fairway → ATG fairway baseline.
    Beyond 50 yds the approach baselines take over (expected_scramble).
    """
    if lie == 'bunker':
        return expected_scramble(distance_yds, 'bunker')
    if lie == 'rough':
        return expected_approach(distance_yds, 'rough')
    return expected_scramble(distance_yds, 'fairway')


def _num(value):
    """Parse a positive number from shot JSON (int, float, numeric string); else None."""
    if value is None or value == '':
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# ---------------------------------------------------------------------------
# Shot list parsing
# ---------------------------------------------------------------------------

def reconstruct_shots(h) -> list:
    """Build a shots_json-style list from legacy hole fields."""
    shots = []
    if h.tee_shot and h.par in (4, 5):
        parts = (h.tee_shot or '').split(',')
        direction = mod = None
        if len(parts) == 1:
            if parts[0] == 'fairway':
                direction = 'fairway'
            elif parts[0] in ('left', 'right'):
                direction = parts[0]
            elif parts[0] in ('bunker', 'penalty', 'trees'):
                mod = parts[0]
        elif len(parts) == 2:
            mod, direction = parts[0], parts[1]
        shots.append({'type': 'ott', 'direction': direction, 'mod': mod})
    if h.second_shot_distance and h.approach_distance:
        s = {'type': 'app', 'distance': h.second_shot_distance}
        if h.tee_shot and h.tee_shot.split(',')[0] == 'trees':
            s['lie'] = 'recovery'
        shots.append(s)
    if h.approach_distance:
        s = {'type': 'app', 'distance': h.approach_distance}
        if h.approach_miss and h.approach_miss != 'layup':
            s['miss'] = h.approach_miss
        if h.lie_type and h.lie_type.split(',')[0] in APP_LIES and not h.second_shot_distance:
            s['lie'] = h.lie_type.split(',')[0]
        shots.append(s)
    atg_count = h.atg_strokes if h.atg_strokes is not None else (1 if h.scramble_distance else 0)
    if h.scramble_distance or (h.approach_miss and h.approach_miss != 'layup' and atg_count):
        sdist = _parse_yards(h.scramble_distance) if h.scramble_distance else None
        atg_lie = 'bunker' if ('bunker' in (h.lie_type or '') or h.sand_save_attempt) else 'rough'
        shots.append({'type': 'atg', 'distance': sdist, 'lie': atg_lie})
        for _ in range(max(0, (atg_count or 1) - 1)):
            shots.append({'type': 'atg', 'distance': None, 'lie': 'rough'})
    total_putts = h.putts if h.putts is not None else 2
    is_gimme = bool(getattr(h, 'last_putt_gimme', False))
    for i in range(total_putts):
        is_last = (i == total_putts - 1)
        if is_last and is_gimme:
            s = {'type': 'gimme'}
            if h.gimme_distance:
                s['gimme_distance'] = h.gimme_distance
            shots.append(s)
        else:
            s = {'type': 'putt'}
            if i == 0 and h.first_putt_distance:
                s['putt_distance'] = h.first_putt_distance
            shots.append(s)
    return shots


def parse_shots(h) -> list:
    """Return the hole's shot list: shots_json when present, else reconstructed."""
    if h.shots_json:
        try:
            shots = json.loads(h.shots_json)
            if isinstance(shots, list):
                return [s for s in shots if isinstance(s, dict) and s.get('type')]
        except (ValueError, TypeError):
            pass
    return reconstruct_shots(h)


def ott_result(shot) -> str:
    """Primary tee-shot outcome: fairway, left, right, bunker, trees, penalty, or unknown."""
    if shot.get('mod') in ('bunker', 'trees', 'penalty'):
        return shot['mod']
    return shot.get('direction') or 'unknown'


def _lie_after(prev) -> str:
    """Infer the lie at the start of a shot from the shot that preceded it."""
    t = prev.get('type')
    if t == 'ott':
        res = ott_result(prev)
        return {'fairway': 'fairway', 'bunker': 'bunker', 'trees': 'recovery',
                'left': 'rough', 'right': 'rough', 'penalty': 'rough'}.get(res, 'rough')
    if t == 'app':
        if prev.get('is_layup'):
            return 'fairway'
        return 'rough' if prev.get('miss') else 'fairway'
    if t == 'atg':
        return 'rough'
    return 'fairway'


# ---------------------------------------------------------------------------
# Hole and round computation
# ---------------------------------------------------------------------------

def compute_hole(h, yardage=None) -> dict:
    """
    Value every shot on a hole.

    Returns {
        'shots':     [shot record, ...],
        'complete':  True when every stroke is accounted for in a valued block,
        'start_exp': Tour expected strokes from the tee (None if unknown),
        'sg_total':  sum of valued shot SG,
    }
    """
    raw = parse_shots(h)
    par = h.par
    recs = []

    for i, s in enumerate(raw):
        t = s.get('type')
        prev = raw[i - 1] if i else None
        rec = {
            'hole_number': h.hole_number, 'par': par, 'idx': i, 'type': t,
            'cat': None, 'club': s.get('club') or None, 'lie': None,
            'dist': None, 'ft': None, 'exp': None, 'sg': None, 'n_strokes': 1,
            'penalty': 0, 'merged': False, 'result': None, 'miss': s.get('miss') or None,
            'is_layup': bool(s.get('is_layup')), 'is_gimme': False, 'holed': False,
            'recovery': False, 'hole_yardage': yardage,
        }
        if t == 'ott':
            rec['cat'] = 'ott'
            rec['lie'] = 'tee'
            rec['result'] = ott_result(s)
            rec['dist'] = yardage
            if yardage:
                rec['exp'] = (expected_approach(yardage, 'fairway') if par == 3
                              else expected_ott(yardage))
        elif t == 'app':
            rec['cat'] = 'app'
            d = _num(s.get('distance'))
            if d is None and i == 0 and yardage:
                d = float(yardage)          # par-3 tee shot logged without a distance
            lie = s.get('lie') if s.get('lie') in APP_LIES else (_lie_after(prev) if prev else 'fairway')
            rec['lie'] = lie
            rec['dist'] = d
            if d:
                rec['exp'] = expected_approach(d, lie)
            # A recovery punch-out after a tee shot into the trees is charged to
            # the tee shot, matching the shot-entry guidance.
            if prev and prev.get('type') == 'ott' and ott_result(prev) == 'trees' and par in (4, 5):
                rec['cat'] = 'ott'
                rec['recovery'] = True
        elif t == 'atg':
            rec['cat'] = 'atg'
            d = _num(s.get('distance'))
            lie = s.get('lie') or 'rough'
            rec['lie'] = lie
            rec['dist'] = d
            if d:
                rec['exp'] = expected_short_game(d, lie)
        elif t == 'putt':
            rec['cat'] = 'putt'
            rec['lie'] = 'green'
            ft = _num(s.get('putt_distance'))
            rec['ft'] = ft
            if ft:
                rec['exp'] = expected_putts(ft)
        elif t == 'gimme':
            rec['cat'] = 'putt'
            rec['lie'] = 'green'
            rec['is_gimme'] = True
            ft = _num(s.get('gimme_distance')) or STANDARD_GIMME_FT
            rec['ft'] = ft
            rec['exp'] = expected_putts(ft)
        recs.append(rec)

    if recs and recs[-1]['type'] == 'putt':
        recs[-1]['holed'] = True

    # ── Penalty strokes ──────────────────────────────────────────────────
    pen_total = int(h.penalties or 0)
    if pen_total and recs:
        flagged = [r for r, s in zip(recs, raw) if s.get('mod') == 'penalty' or s.get('penalty')]
        if flagged:
            for k in range(pen_total):
                flagged[min(k, len(flagged) - 1)]['penalty'] += 1
        else:
            target = next((r for r in recs if r['type'] == 'ott'), recs[0])
            target['penalty'] += pen_total

    # ── End-of-shot expectations ────────────────────────────────────────
    # end_exp[k] = expected strokes at the START of shot k, used as the END of
    # shot k-1. A first putt logged without a distance gets the assumed
    # 20 ft value here only, so the approach/chip onto the green can still be
    # valued; the putt itself stays unvalued.
    n = len(recs)
    starts = [r['exp'] for r in recs]
    end_exp = list(starts)
    for k in range(1, n):
        if (end_exp[k] is None and recs[k]['type'] == 'putt'
                and recs[k - 1]['cat'] != 'putt'):
            end_exp[k] = expected_putts(ASSUMED_FIRST_PUTT_FT)

    covered = 0
    i = 0
    while i < n:
        if starts[i] is None:
            i += 1
            continue
        j = i + 1
        while j < n and end_exp[j] is None:
            j += 1
        end = 0.0 if j == n else end_exp[j]
        block = recs[i:j]
        cats = {r['cat'] for r in block}
        if len(cats) == 1 and None not in cats:
            strokes = len(block) + sum(r['penalty'] for r in block)
            recs[i]['sg'] = round(starts[i] - strokes - end, 4)
            recs[i]['n_strokes'] = len(block)
            recs[i]['penalty'] = sum(r['penalty'] for r in block)
            for r in block[1:]:
                r['merged'] = True
                r['penalty'] = 0
            if recs[i]['type'] == 'putt' and j == n:
                recs[i]['holed'] = (len(block) == 1)
            covered += len(block)
        i = j

    complete = (n > 0 and covered == n and starts[0] is not None)
    return {
        'shots': recs,
        'complete': complete,
        'start_exp': starts[0] if starts else None,
        'sg_total': round(sum(r['sg'] for r in recs if r['sg'] is not None), 4),
    }


def compute_round(round_, course_hole_map=None) -> dict:
    """
    Value every shot in a round.

    Returns {
        'holes':       {hole_number: compute_hole() result + 'score', 'par'},
        'shots':       flat list of all shot records,
        'totals':      {cat: summed SG},
        'counts':      {cat: number of valued shots},
        'sg_total':    sum of all category totals,
        'measured':    {'holes', 'holes_total', 'expected', 'score'} for fully measured holes,
    }
    """
    if course_hole_map is None:
        from app.utils.round_stats import build_course_hole_map
        course_hole_map = build_course_hole_map(round_)

    holes = round_.holes.order_by('hole_number').all()
    out_holes, flat = {}, []
    totals = {c: 0.0 for c in CATEGORIES}
    counts = {c: 0 for c in CATEGORIES}
    m_holes = m_exp = m_score = 0

    for h in holes:
        ch = course_hole_map.get(h.hole_number)
        res = compute_hole(h, ch.yardage if (ch and ch.yardage) else None)
        res['score'] = h.score
        res['par'] = h.par
        out_holes[h.hole_number] = res
        for r in res['shots']:
            flat.append(r)
            if r['sg'] is not None and r['cat'] in totals:
                totals[r['cat']] += r['sg']
                counts[r['cat']] += 1
        if res['complete'] and h.score:
            m_holes += 1
            m_exp += res['start_exp']
            m_score += h.score

    totals = {c: round(v, 3) for c, v in totals.items()}
    return {
        'holes': out_holes,
        'shots': flat,
        'totals': totals,
        'counts': counts,
        'sg_total': round(sum(totals.values()), 3),
        'measured': {'holes': m_holes, 'holes_total': len(holes),
                     'expected': round(m_exp, 2), 'score': m_score},
    }

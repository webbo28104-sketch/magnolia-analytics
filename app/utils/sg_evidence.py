"""
How much to trust a strokes-gained number, and whether it is a pattern.

Two questions for every breakdown row (e.g. "approach 100–115 yds"):

1. Reliability — how many shots sit behind the per-shot average, and how wide
   is the uncertainty? A 95% range is mean ± 1.96·sd/√n, where sd is the
   golfer's own per-shot spread in that category (falling back to typical
   amateur values until there is enough history). If the whole range sits
   below zero the loss is beyond normal shot-to-shot noise.

2. Pattern — across the golfer's recent rounds, how often has this bucket
   lost strokes? Recurring losses are worth practising; a one-off bad day
   usually is not.
"""

import math

from app.utils import sg_breakdown as bd

# Typical per-shot SG spread for amateurs, used until the golfer has 30+ shots
DEFAULT_SD = {'ott': 0.55, 'app': 0.50, 'atg': 0.45, 'putt': 0.40}

DIM_CAT = {
    'app_dist': 'app', 'app_lie': 'app', 'app_club': 'app',
    'ott_club': 'ott', 'ott_result': 'ott', 'ott_len': 'ott',
    'atg_dist': 'atg', 'atg_lie': 'atg', 'atg_club': 'atg',
    'putt_dist': 'putt', 'club_all': None,
}

TIERS = [
    (30, 'solid', 'Solid sample'),
    (10, 'developing', 'Developing'),
    (3, 'early', 'Early signal'),
    (0, 'thin', 'Too few to judge'),
]


def category_sd(shots) -> dict:
    """Per-category SD of per-shot SG from the golfer's own shots (needs 30+)."""
    out = dict(DEFAULT_SD)
    for cat in DEFAULT_SD:
        vals = [s['sg'] for s in shots if s['cat'] == cat and s['sg'] is not None]
        if len(vals) >= 30:
            m = sum(vals) / len(vals)
            out[cat] = max(0.15, math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)))
    return out


def tier(n):
    for floor, key, label in TIERS:
        if n >= floor:
            return key, label
    return 'thin', 'Too few to judge'


def reliability(per, n, sd):
    """{'tier', 'tier_label', 'ci', 'lo', 'hi', 'clear'} for a per-shot mean."""
    key, label = tier(n)
    if not n or per is None:
        return {'tier': key, 'tier_label': label, 'ci': None, 'lo': None, 'hi': None, 'clear': None}
    ci = 1.96 * sd / math.sqrt(n)
    lo, hi = per - ci, per + ci
    clear = 'loss' if hi < 0 else ('gain' if lo > 0 else None)
    return {'tier': key, 'tier_label': label, 'ci': round(ci, 3), 'lo': round(lo, 3),
            'hi': round(hi, 3), 'clear': clear}


def per_round_values(round_datas, dim):
    """{bucket_key: [per-shot SG in each round where the bucket was played]} (newest first)."""
    out = {}
    for _, data in round_datas:
        agg = bd.aggregate(data['shots'], dim)
        for k, b in agg.items():
            out.setdefault(k, []).append(b['sg'] / b['n'])
    return out


def pattern(this_per, history_vals):
    """
    Classify a bucket across rounds.
    this_per: this round's per-shot value (None when used for a multi-round view)
    history_vals: per-round per-shot values from previous rounds (newest first)
    """
    played = len(history_vals)
    neg = sum(1 for v in history_vals if v < 0)
    avg = sum(history_vals) / played if played else None
    if played < 2:
        return {'kind': 'new', 'played': played, 'neg': neg, 'avg': avg,
                'text': 'Not enough earlier rounds from here to call it a pattern yet.'}
    share = neg / played
    if this_per is not None and this_per < 0 and share >= 0.6:
        kind, text = 'recurring', f'Recurring: also lost strokes here in {neg} of your previous {played} rounds.'
    elif this_per is not None and this_per < 0 and share <= 0.4:
        kind, text = 'one-off', (f'Unusual for you: you lost strokes here in only {neg} of your previous {played} rounds'
                                 + (f' (average {avg:+.2f}/shot).' if avg is not None else '.'))
    elif this_per is not None and this_per > 0 and share >= 0.6:
        kind, text = 'improving', f'Better than usual: you lost strokes here in {neg} of your previous {played} rounds.'
    elif this_per is None and share >= 0.6:
        kind, text = 'recurring', f'Lost strokes here in {neg} of {played} rounds.'
    else:
        kind, text = 'mixed', f'Mixed: lost strokes here in {neg} of your previous {played} rounds.'
    return {'kind': kind, 'played': played, 'neg': neg, 'avg': avg, 'text': text}


def annotate(rows, sd_by_cat, history_round_values=None):
    """Add reliability (+ pattern when per-round history is given) to breakdown rows in place."""
    for r in rows:
        cat = DIM_CAT.get(r['dim'])
        sd = sd_by_cat.get(cat, 0.5) if cat else 0.5
        r['rel'] = reliability(r['per'], r['n'], sd)
        if history_round_values is not None:
            hv = history_round_values.get(r['dim'], {}).get(r['key'], [])
            r['pattern'] = pattern(r['per'], hv)
    return rows


PATTERN_DIMS = ['app_dist', 'app_lie', 'app_club', 'ott_club', 'ott_result', 'atg_dist', 'atg_lie', 'putt_dist']


def recurring_patterns(round_datas, sd_by_cat, min_rounds=3, limit=3):
    """
    Buckets that keep gaining or losing strokes across rounds.

    round_datas: [(round, shots_for_round data)] newest first (include the current round).
    A weakness/strength needs at least `min_rounds` rounds played from that bucket and
    the same sign in 60%+ of them. Ranked by average strokes per round.
    """
    weak, strong = [], []
    all_shots = [s for _, d in round_datas for s in d['shots']]
    for dim in PATTERN_DIMS:
        per_round = {}
        for _, d in round_datas:
            for k, b in bd.aggregate(d['shots'], dim).items():
                per_round.setdefault(k, []).append((b['sg'], b['n']))
        overall = {r['key']: r for r in bd.rows(all_shots, dim)}
        for key, vals in per_round.items():
            played = len(vals)
            if played < min_rounds or key not in overall:
                continue
            row = overall[key]
            neg = sum(1 for sg, _ in vals if sg < 0)
            pos = played - neg
            cat = DIM_CAT.get(dim)
            rel = reliability(row['per'], row['n'], sd_by_cat.get(cat, 0.5))
            item = {
                'dim': dim, 'key': key, 'title': bd._title({**row, 'dim': dim}), 'label': row['label'],
                'played': played, 'neg': neg, 'pos': pos, 'n': row['n'], 'per': row['per'],
                'per_round': round(sum(sg for sg, _ in vals) / played, 2), 'rel': rel,
            }
            if neg / played >= 0.6 and row['per'] < 0:
                weak.append(item)
            elif pos / played >= 0.6 and row['per'] > 0:
                strong.append(item)
    weak.sort(key=lambda x: x['per_round'])
    strong.sort(key=lambda x: -x['per_round'])

    def dedupe(items):
        seen, out = set(), []
        for it in items:
            sig = (it['dim'].split('_')[0], it['played'], it['n'], round(it['per'], 2))
            if sig not in seen:
                seen.add(sig)
                out.append(it)
        return out
    return dedupe(weak)[:limit], dedupe(strong)[:limit]

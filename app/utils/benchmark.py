"""
Handicap benchmark: what strokes gained vs scratch a golfer of this handicap
typically records, so charts centre on "normal for you" instead of scratch (0).

Consistent with hcp_equiv ("plays like"): a golfer of index H loses H strokes to
scratch per 18 holes, a quarter in each part of the game:

    per 18, each part:   −H / 4
    per shot:            (−H / 4) / shots of that kind per 18 holes
    per hole:            −H / 18

Shots per 18 come from the golfer's own rounds, so the benchmark matches how
they actually play (e.g. ~13 approaches per 18 → a 10.4 expects −0.20 per approach).

The index is the official one at the time of the round: the Handicap Index
England Golf recorded with the most recent score on or before that date,
otherwise the current official index, otherwise the Magnolia index.
"""

import json
from datetime import date

CATS = ('ott', 'app', 'atg', 'putt')
TYPICAL_PER18 = {'ott': 14.0, 'app': 13.0, 'atg': 7.0, 'putt': 31.0}
MIN_HOLES_FOR_OWN_RATES = 36


def _num(v):
    try:
        return float(str(v).replace('+', '-') if str(v).startswith('+') else v)
    except (TypeError, ValueError):
        return None


def index_at(user, on_date=None):
    """(index, label) for the golfer's handicap at on_date, or (None, None)."""
    if user is None:
        return None, None
    if on_date is not None and user.eg_scores_json:
        try:
            scores = json.loads(user.eg_scores_json)
        except ValueError:
            scores = []
        dated = []
        for s in scores:
            raw = s.get('raw') or {}
            idx = _num(raw.get('HandicapIndex') if raw.get('HandicapIndex') is not None else s.get('index_at_time'))
            if s.get('date') and idx is not None and date.fromisoformat(s['date']) <= on_date:
                dated.append((s['date'], idx))
        if dated:
            d, idx = max(dated)
            d = date.fromisoformat(d)
            return idx, f"your England Golf index on {d.day} {d.strftime('%b %Y')}"
    if user.official_handicap_index is not None:
        return user.official_handicap_index, 'your official index'
    if user.handicap_index:
        return user.handicap_index, 'your Magnolia index'
    return None, None


def shots_per18(round_datas):
    """Average shots of each kind per 18 holes over [(round, shots_for_round data)]."""
    # Count only holes that have valued shots: holes logged without shot detail
    # would otherwise dilute the rates and inflate the per-shot benchmark.
    holes, counts = 0, {c: 0 for c in CATS}
    for _, d in round_datas:
        valued = [s for s in d['shots'] if s['sg'] is not None]
        holes += len({s['hole_number'] for s in valued})
        for s in valued:
            if s['cat'] in counts:
                counts[s['cat']] += 1
    if holes < MIN_HOLES_FOR_OWN_RATES:
        return dict(TYPICAL_PER18)
    return {c: max(counts[c] * 18 / holes, 1.0) for c in CATS}


def make(index, label, per18):
    """Benchmark dict used by templates; None when there is no handicap to compare with."""
    if index is None:
        return None
    cat18 = -index / 4
    shot = {c: cat18 / per18[c] for c in CATS}
    shot['all'] = -index / sum(per18[c] for c in CATS)
    return {'index': index, 'label': label, 'cat18': cat18, 'shot': shot, 'per18': per18,
            'hole': -index / 18, 'round18': -index,
            'index_txt': f'+{-index:.1f}' if index < 0 else f'{index:.1f}'}


def for_dim(bench, dim):
    """Per-shot benchmark for a breakdown dimension such as 'app_dist' or 'club_all'."""
    if not bench:
        return 0.0
    cat = (dim or '').split('_')[0]
    return bench['shot'].get(cat, bench['shot']['all'])

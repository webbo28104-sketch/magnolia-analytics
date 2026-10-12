"""
Strokes-gained breakdowns built from per-shot SG (app/utils/shot_sg.py).

Every row is centred on SG per shot: n valued shots, their summed SG and
the per-shot average, optionally alongside the player's average for the
same bucket over previous rounds.
"""

from app.utils.clubs import club_label, club_name, sort_clubs

APP_BANDS = [
    (0, 50, '< 50'), (50, 75, '50–75'), (75, 100, '75–100'), (100, 115, '100–115'),
    (115, 130, '115–130'), (130, 145, '130–145'), (145, 160, '145–160'),
    (160, 175, '160–175'), (175, 190, '175–190'), (190, 210, '190–210'), (210, 99999, '210+'),
]
OTT_LENGTHS = [
    (0, 350, '< 350'), (350, 400, '350–400'), (400, 450, '400–450'),
    (450, 500, '450–500'), (500, 99999, '500+'),
]
ATG_BANDS = [(0, 10, '0–10'), (10, 20, '10–20'), (20, 30, '20–30'), (30, 99999, '30+')]
PUTT_BANDS = [(0, 3, '< 3'), (3, 6, '3–6'), (6, 10, '6–10'), (10, 20, '10–20'),
              (20, 35, '20–35'), (35, 99999, '35+')]

OTT_RESULTS = [('fairway', 'Fairway'), ('left', 'Left rough'), ('right', 'Right rough'),
               ('bunker', 'Bunker'), ('trees', 'Trees'), ('penalty', 'Penalty')]
APP_LIE_LABELS = [('fairway', 'Fairway'), ('rough', 'Rough'), ('bunker', 'Bunker'), ('recovery', 'Recovery')]
ATG_LIE_LABELS = [('fringe', 'Fringe'), ('rough', 'Rough'), ('bunker', 'Bunker')]

# Tour make % by putt band (Broadie): used as a reference marker
TOUR_MAKE_PCT = {'< 3': 99, '3–6': 80, '6–10': 52, '10–20': 25, '20–35': 8, '35+': 3}


def _band(value, bands):
    if value is None:
        return None
    for lo, hi, label in bands:
        if lo <= value < hi:
            return label
    return None


def _valued(shots, cat):
    return [s for s in shots if s['cat'] == cat and s['sg'] is not None]


# Each dimension: (key, category, bucket function, ordered labels or None, title fn)
def _dims():
    return {
        'app_dist': ('app', lambda s: _band(s['dist'], APP_BANDS), [b[2] for b in APP_BANDS]),
        'app_lie':  ('app', lambda s: s['lie'], [k for k, _ in APP_LIE_LABELS]),
        'app_club': ('app', lambda s: s['club'], None),
        'ott_club': ('ott', lambda s: s['club'] if s['type'] == 'ott' else None, None),
        'ott_result': ('ott', lambda s: s['result'] if s['type'] == 'ott' else None, [k for k, _ in OTT_RESULTS]),
        'ott_len':  ('ott', lambda s: _band(s['hole_yardage'], OTT_LENGTHS) if s['type'] == 'ott' else None,
                     [b[2] for b in OTT_LENGTHS]),
        'atg_dist': ('atg', lambda s: _band(s['dist'], ATG_BANDS), [b[2] for b in ATG_BANDS]),
        'atg_lie':  ('atg', lambda s: s['lie'], [k for k, _ in ATG_LIE_LABELS]),
        'atg_club': ('atg', lambda s: s['club'], None),
        'putt_dist': ('putt', lambda s: _band(s['ft'], PUTT_BANDS), [b[2] for b in PUTT_BANDS]),
        'club_all': (None, lambda s: s['club'], None),
    }


def _label(dim, key):
    if dim in ('app_club', 'ott_club', 'atg_club', 'club_all'):
        return club_label(key)
    if dim == 'ott_result':
        return dict(OTT_RESULTS).get(key, key)
    if dim == 'app_lie':
        return dict(APP_LIE_LABELS).get(key, key)
    if dim == 'atg_lie':
        return dict(ATG_LIE_LABELS).get(key, key)
    return key


def aggregate(shots, dim) -> dict:
    """{bucket_key: {'n', 'sg', 'shots'}} for one dimension."""
    cat, fn, _ = _dims()[dim]
    pool = [s for s in shots if s['sg'] is not None and (cat is None or s['cat'] == cat)]
    if dim == 'club_all':
        pool = [s for s in pool if s['cat'] != 'putt' or s['club']]
    out = {}
    for s in pool:
        k = fn(s)
        if k is None:
            continue
        b = out.setdefault(k, {'n': 0, 'sg': 0.0, 'shots': []})
        b['n'] += 1
        b['sg'] += s['sg']
        b['shots'].append(s)
    return out


def rows(shots, dim, history_shots=None) -> list:
    """Ordered breakdown rows for one dimension, with optional history averages."""
    _, _, order = _dims()[dim]
    agg = aggregate(shots, dim)
    hist = aggregate(history_shots, dim) if history_shots else {}
    keys = list(agg.keys())
    if order:
        keys = [k for k in order if k in agg] + [k for k in keys if k not in order]
    elif dim in ('app_club', 'ott_club', 'atg_club', 'club_all'):
        keys = sort_clubs(keys)
    out = []
    for k in keys:
        b = agg[k]
        h = hist.get(k)
        out.append(_row(dim, k, b, h))
    return out


def _row(dim, key, b, h=None) -> dict:
    shots = b['shots']
    row = {
        'dim': dim, 'key': key, 'label': _label(dim, key),
        'n': b['n'], 'sg': round(b['sg'], 2), 'per': round(b['sg'] / b['n'], 3),
        'avg': round(h['sg'] / h['n'], 3) if h and h['n'] >= 3 else None,
        'avg_n': h['n'] if h else 0,
    }
    dists = [s['dist'] for s in shots if s['dist']]
    row['avg_dist'] = round(sum(dists) / len(dists)) if dists else None
    clubs = sort_clubs({s['club'] for s in shots if s['club']})
    row['clubs'] = [club_label(c) for c in clubs]
    if dim == 'putt_dist':
        row['holed'] = sum(1 for s in shots if s['holed'])
        row['tour_make'] = TOUR_MAKE_PCT.get(key)
    if dim in ('ott_club',):
        travel = [s.get('travel') for s in shots if s.get('travel')]
        row['avg_travel'] = round(sum(travel) / len(travel)) if travel else None
        row['fairways'] = sum(1 for s in shots if s['result'] == 'fairway')
    return row


def add_travel(round_data) -> None:
    """
    Annotate each shot with an estimated distance travelled (yards):
    start distance minus the distance left for the next shot, adding the
    remainder back when the shot was marked long. Used for club distances.
    """
    for hole in round_data['holes'].values():
        recs = hole['shots']
        for i, s in enumerate(recs):
            s['travel'] = None
            if s['cat'] == 'putt' or not s['dist']:
                continue
            if s['type'] == 'ott' and s['result'] == 'penalty':
                continue
            nxt = recs[i + 1] if i + 1 < len(recs) else None
            if nxt is None:
                left = 0.0
            elif nxt['type'] == 'ott':
                continue
            elif nxt['cat'] == 'putt':
                left = (nxt['ft'] or 0) / 3.0
            else:
                left = nxt['dist']
            if left is None:
                continue
            travel = s['dist'] + left if 'long' in (s['miss'] or '') else s['dist'] - left
            if travel > 0:
                s['travel'] = round(travel)


# ---------------------------------------------------------------------------
# Leaks and strengths
# ---------------------------------------------------------------------------

_LEAK_DIMS = ['app_dist', 'app_lie', 'app_club', 'ott_club', 'ott_result', 'atg_dist', 'atg_lie', 'putt_dist']


def _title(row):
    d, lbl = row['dim'], row['label']
    return {
        'app_dist': f'Approach {lbl} yds',
        'app_lie': f'Approach from {lbl.lower()}',
        'app_club': f'Approach with {club_name(row["key"]).lower()}',
        'ott_club': f'{club_name(row["key"])} off the tee',
        'ott_result': f'Tee shots: {lbl.lower()}',
        'atg_dist': f'Short game {lbl} yds',
        'atg_lie': f'Short game from {lbl.lower()}',
        'putt_dist': f'Putts {lbl} ft',
    }.get(d, lbl)


def _meta(row):
    d = row['dim']
    unit = 'putt' if d == 'putt_dist' else 'shot'
    parts = [f"{row['n']} {unit}{'s' if row['n'] != 1 else ''}"]
    if d == 'putt_dist':
        parts.append(f"{row.get('holed', 0)} holed")
    elif d in ('app_club', 'ott_club') and row.get('avg_dist'):
        parts.append(f"avg {row['avg_dist']} yds to flag" if d == 'app_club' else f"avg hole {row['avg_dist']} yds")
    elif row['clubs'] and d not in ('app_club', 'ott_club'):
        parts.append(', '.join(row['clubs'][:3]))
    return ' · '.join(parts)


def leaks_and_strengths(shots, history_shots=None, n_leaks=4, n_strengths=3):
    """Rank every breakdown bucket by total SG: biggest losses and clearest gains."""
    candidates = []
    for dim in _LEAK_DIMS:
        for row in rows(shots, dim, history_shots):
            row['title'] = _title(row)
            row['meta'] = _meta(row)
            candidates.append(row)
    leaks = sorted([r for r in candidates if r['sg'] < 0], key=lambda r: r['sg'])
    strengths = sorted([r for r in candidates if r['sg'] > 0], key=lambda r: -r['sg'])
    return _dedupe(leaks)[:n_leaks], _dedupe(strengths)[:n_strengths]


def _dedupe(rows_):
    """Drop a row that covers exactly the same shots as a higher-ranked row."""
    seen, out = [], []
    for r in rows_:
        sig = (r['dim'].split('_')[0], r['n'], round(r['sg'], 2))
        if sig in seen:
            continue
        seen.append(sig)
        out.append(r)
    return out

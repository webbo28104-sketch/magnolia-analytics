"""Per-club distance and strokes-gained profiles from logged shots."""


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = (len(sorted_vals) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def club_profiles(shots) -> dict:
    """
    {club: {'n', 'avg', 'lo', 'hi', 'sg_n', 'sg_per'}} from logged shots.
    Distance = estimated travel (start distance minus distance left);
    lay-ups and recovery shots are left out of distances.
    """
    out = {}
    for s in shots:
        club = s.get('club')
        if not club or club == 'P':
            continue
        p = out.setdefault(club, {'travel': [], 'sg': []})
        if s.get('travel') and not s['is_layup'] and not s['recovery']:
            p['travel'].append(s['travel'])
        if s['sg'] is not None:
            p['sg'].append(s['sg'])
    result = {}
    for club, p in out.items():
        t = sorted(p['travel'])
        result[club] = {
            'n': len(t),
            'avg': round(sum(t) / len(t)) if t else None,
            'lo': round(_quantile(t, 0.25)) if len(t) >= 3 else (t[0] if t else None),
            'hi': round(_quantile(t, 0.75)) if len(t) >= 3 else (t[-1] if t else None),
            'sg_n': len(p['sg']),
            'sg_per': round(sum(p['sg']) / len(p['sg']), 3) if p['sg'] else None,
        }
    return result

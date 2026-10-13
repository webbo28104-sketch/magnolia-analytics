"""
Handicap equivalents for strokes gained vs scratch — the "plays like a 16" numbers.

A scratch golfer loses nothing to scratch, so strokes lost per 18 holes reads
directly as handicap strokes. Each of the four parts of the game is weighted
equally (25%), so one part's equivalent is 4 × its strokes lost per 18:

    9 holes, −2 off the tee → −4 per 18 → 4 × 4 = plays like a 16 off the tee

The round as a whole is the average of the four: strokes lost per 18 in total.
A single shot (or group of shots) is scaled by how many such shots are played
per 18 holes: "if every approach were like this one you'd play to a 14".
"""

from app.utils.strokes_gained import normalize_to_18

PARTS = 4                 # equal weighting: tee, approach, short game, putting
MIN_HCP, MAX_HCP = -10.0, 54.0


def _clamp(v):
    return max(MIN_HCP, min(MAX_HCP, v))


def round_plays_like(sg_total, holes_played):
    """Whole round: strokes lost to scratch per 18."""
    per18 = normalize_to_18(sg_total, holes_played) if sg_total is not None else None
    return None if per18 is None else round(_clamp(-per18), 1)


def category_plays_like(sg_cat, holes_played):
    """One part of the game: 4 × strokes lost per 18 in that part."""
    per18 = normalize_to_18(sg_cat, holes_played) if sg_cat is not None else None
    return None if per18 is None else round(_clamp(-PARTS * per18), 1)


def per18_from_values(values):
    """Average of per-18 values, ignoring None."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def shots_plays_like(sg_per_shot, shots_per_18):
    """A group of shots: as if every shot of that type in 18 holes were like these."""
    if sg_per_shot is None or not shots_per_18:
        return None
    return round(_clamp(-PARTS * sg_per_shot * shots_per_18), 1)


def fmt(v):
    """16.4 → '16', −2.3 → '+2' (plus handicap)."""
    if v is None:
        return '—'
    r = round(v)
    return f'+{-r}' if r < 0 else str(r)


def verdict(v, index):
    """'better' / 'worse' / 'level' against the golfer's own index (±1.5 is level)."""
    if v is None or index is None:
        return None
    if v < index - 1.5:
        return 'better'
    if v > index + 1.5:
        return 'worse'
    return 'level'


def glance(parts, overall, index):
    """
    parts: [(key, label, plays_like)] ; overall: plays_like for the round/period.
    Returns tiles + a one-line plain-English takeaway.
    """
    tiles = [{'key': k, 'label': l, 'v': v, 'txt': fmt(v), 'verdict': verdict(v, index)} for k, l, v in parts]
    known = [t for t in tiles if t['v'] is not None]
    takeaway = None
    if len(known) >= 2:
        best = min(known, key=lambda t: t['v'])
        worst = max(known, key=lambda t: t['v'])
        if worst['v'] - best['v'] >= 2:
            takeaway = (f"{worst['label']} cost you most (plays like a {worst['txt']}); "
                        f"{best['label'].lower()} was your strength (plays like a {best['txt']}).")
        else:
            takeaway = 'Every part of your game played to a similar level.'
    return {'overall': overall, 'overall_txt': fmt(overall), 'overall_verdict': verdict(overall, index),
            'tiles': tiles, 'takeaway': takeaway, 'index': index}

"""
Strokes Gained calculations.
Based on PGA Tour baseline data for amateur golfers.
Extend with full SG tables as the dataset grows.
"""

# Baseline expected strokes to hole out from given distances (in feet)
# Source: approximated from Mark Broadie's SG research
PUTTING_BASELINES = {
    3: 1.03,
    6: 1.30,
    9: 1.50,
    12: 1.65,
    15: 1.75,
    20: 1.85,
    30: 1.95,
    40: 2.05,
    50: 2.15,
}

DISTANCE_BANDS = [
    (0, 6, '0–6 ft'),
    (6, 10, '6–10 ft'),
    (10, 15, '10–15 ft'),
    (15, 30, '15–30 ft'),
    (30, float('inf'), '30+ ft'),
]


def expected_putts(distance_ft: int) -> float:
    """Return expected putts from a given distance using baseline table."""
    keys = sorted(PUTTING_BASELINES.keys())
    if distance_ft <= keys[0]:
        return PUTTING_BASELINES[keys[0]]
    if distance_ft >= keys[-1]:
        return PUTTING_BASELINES[keys[-1]]
    # Linear interpolation
    for i in range(len(keys) - 1):
        if keys[i] <= distance_ft <= keys[i + 1]:
            t = (distance_ft - keys[i]) / (keys[i + 1] - keys[i])
            return PUTTING_BASELINES[keys[i]] + t * (
                PUTTING_BASELINES[keys[i + 1]] - PUTTING_BASELINES[keys[i]]
            )
    return 2.0


def strokes_gained_putting(holes) -> dict:
    """
    Calculate strokes gained putting for a list of Hole objects.
    Returns per-band breakdown and total SG putting.
    """
    band_data = {band[2]: {'attempts': 0, 'makes': 0, 'sg': 0.0} for band in DISTANCE_BANDS}
    total_sg = 0.0

    for hole in holes:
        if hole.first_putt_distance and hole.putts:
            dist = hole.first_putt_distance
            exp = expected_putts(dist)
            sg = exp - hole.putts
            total_sg += sg

            # Assign to distance band
            for lo, hi, label in DISTANCE_BANDS:
                if lo <= dist < hi:
                    band_data[label]['attempts'] += 1
                    band_data[label]['sg'] += sg
                    if hole.putts == 1:
                        band_data[label]['makes'] += 1
                    break

    # Compute make percentages
    for band in band_data.values():
        attempts = band['attempts']
        band['make_pct'] = (
            round(band['makes'] / attempts * 100, 1) if attempts else None
        )

    return {'total': round(total_sg, 2), 'bands': band_data}


def strokes_gained_off_tee(holes) -> float:
    """
    Simplified SG off tee: penalise for left/right/penalty misses.
    A full implementation requires course-specific yardage data.
    """
    sg = 0.0
    for hole in holes:
        if hole.par in (4, 5) and hole.tee_shot:
            if hole.tee_shot == 'fairway':
                sg += 0.2
            elif hole.tee_shot in ('left', 'right'):
                sg -= 0.2
            elif hole.tee_shot == 'penalty':
                sg -= 0.7
    return round(sg, 2)

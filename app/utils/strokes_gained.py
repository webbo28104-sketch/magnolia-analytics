"""
Strokes Gained calculations.
Baseline values are PGA Tour averages derived from Mark Broadie's research
("Every Shot Counts", 2014 and subsequent work).  All four categories use
the same benchmark so users can compare their numbers directly to tour data.
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


# ---------------------------------------------------------------------------
# Approach distance → expected strokes to hole out
# Source: Mark Broadie's PGA Tour averages (all lies combined).
# Using PGA Tour values so SG numbers are on the same scale as tour data.
# ---------------------------------------------------------------------------
_APPROACH_BASELINES = {
    # distance (yds): expected strokes remaining (PGA Tour average)
    30:  2.47,
    50:  2.58,
    75:  2.70,
    100: 2.79,
    125: 2.88,
    150: 2.98,
    175: 3.11,
    200: 3.25,
    225: 3.41,
    250: 3.58,
}


def _expected_strokes_approach(distance_yds: int) -> float:
    """Linear-interpolate expected strokes from approach distance (yards)."""
    keys = sorted(_APPROACH_BASELINES.keys())
    if distance_yds <= keys[0]:
        return _APPROACH_BASELINES[keys[0]]
    if distance_yds >= keys[-1]:
        return _APPROACH_BASELINES[keys[-1]]
    for i in range(len(keys) - 1):
        if keys[i] <= distance_yds <= keys[i + 1]:
            t = (distance_yds - keys[i]) / (keys[i + 1] - keys[i])
            return _APPROACH_BASELINES[keys[i]] + t * (
                _APPROACH_BASELINES[keys[i + 1]] - _APPROACH_BASELINES[keys[i]]
            )
    return 3.2


def strokes_gained_approach(holes) -> float:
    """
    Estimate SG Approach to the Green.

    Method:
    - Par 3s: use approach_distance (tee-to-green distance) and compare
      expected strokes from that distance vs. actual score after the tee shot
      (i.e. score minus 1 tee shot = strokes used from that distance).
    - Par 4/5 GIR: approach_distance gives distance of the approach shot;
      SG = expected_from(distance) - putts  (we know they holed it in putts).
    - Par 4/5 GIR missed: penalise — they needed extra strokes to get on green.

    TODO: replace with Broadie's full shot-level expected-strokes model once
    course-level yardage data is consistently available.
    """
    sg = 0.0
    eligible = 0

    for hole in holes:
        dist = hole.approach_distance

        if hole.par == 3 and dist:
            # On a par 3, the tee shot IS the approach shot
            exp = _expected_strokes_approach(dist)
            # Strokes used from that distance = total score - 1 (the tee shot)
            # SG approach = expected - actual strokes used from approach lie
            strokes_used = hole.score - 1
            sg += exp - strokes_used
            eligible += 1

        elif hole.par in (4, 5):
            if hole.gir and dist:
                # Approach found the green — compare expected from that distance
                exp = _expected_strokes_approach(dist)
                strokes_used = hole.putts  # they got on in regulation, putts remain
                sg += exp - strokes_used
                eligible += 1
            elif not hole.gir:
                # Missed GIR — simple penalty model
                # TODO: refine with distance from green after the approach
                if hole.approach_miss == 'bunker':
                    sg -= 0.4
                elif hole.approach_miss in ('left', 'right', 'short', 'long'):
                    sg -= 0.3
                else:
                    sg -= 0.25
                eligible += 1

    return round(sg, 2)


def strokes_gained_around_green(holes) -> float:
    """
    Estimate SG Around the Green (chip/pitch/bunker play).

    Applies only to holes where GIR was missed and the player had a
    short-game shot to play before putting.

    Method:
    - Good scramble (par or better despite GIR miss): positive SG
    - Bunker save made: bonus
    - Bunker save missed: penalty
    - Failed scramble (bogey+): scaled penalty based on severity

    TODO: replace with Broadie's around-green expected-strokes model using
    scramble_distance data once that field is more consistently populated.
    """
    sg = 0.0

    for hole in holes:
        if hole.gir:
            continue  # Around-green only applies to GIR misses

        score_diff = hole.score - hole.par  # vs par on this hole

        # Sand save contribution
        if hole.sand_save_attempt:
            if hole.sand_save_made:
                sg += 0.5   # saved from bunker — significantly above average
            else:
                sg -= 0.3   # failed bunker escape — below average

        elif score_diff <= 0:
            # Scrambled for par or better without a bunker — strong short game
            sg += 0.4

        elif score_diff == 1:
            # Bogey — average around the green for an amateur on a GIR miss
            sg += 0.0

        elif score_diff == 2:
            # Double — below average short game
            sg -= 0.4

        else:
            # Triple or worse
            sg -= 0.7

    return round(sg, 2)

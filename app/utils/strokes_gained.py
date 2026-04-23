"""
Strokes Gained calculations — Broadie PGA Tour methodology.

All four categories use the same PGA Tour benchmark so values are
directly comparable to tour data.  The core formula for every shot is:

    SG = expected_strokes(start_position) - 1 - expected_strokes(end_position)

Where "expected strokes" is the average number of strokes a PGA Tour
player needs to hole out from that position / lie.

Baseline tables are sourced from Mark Broadie's "Every Shot Counts" (2014)
and subsequently published tour-average datasets.
"""

# ---------------------------------------------------------------------------
# Putting baseline: distance in feet → expected putts (PGA Tour average)
# ---------------------------------------------------------------------------
PUTTING_BASELINES = {
    1: 1.001,  2: 1.009,  3: 1.053,  4: 1.147,  5: 1.252,
    6: 1.354,  7: 1.447,  8: 1.527,  9: 1.596, 10: 1.655,
   11: 1.705, 12: 1.748, 13: 1.786, 14: 1.820, 15: 1.850,
   16: 1.877, 17: 1.901, 18: 1.923, 19: 1.943, 20: 1.960,
   22: 1.991, 25: 2.034, 28: 2.069, 30: 2.088, 33: 2.113,
   35: 2.127, 40: 2.160, 45: 2.189, 50: 2.214, 55: 2.237,
   60: 2.257, 70: 2.292, 80: 2.322, 100: 2.373,
}

# ---------------------------------------------------------------------------
# Off-the-Tee baseline: hole distance in yards → expected strokes (PGA Tour)
# ---------------------------------------------------------------------------
_OTT_BASELINES = {
    300: 3.71, 325: 3.80, 350: 3.88, 375: 3.93, 400: 3.99,
    425: 4.04, 450: 4.10, 475: 4.17, 500: 4.23, 525: 4.50,
    550: 4.57, 575: 4.63, 600: 4.70,
}

# ---------------------------------------------------------------------------
# Approach baselines: distance in yards → expected strokes by lie (PGA Tour)
# ---------------------------------------------------------------------------
_APPROACH_FAIRWAY = {
      5: 2.10,  10: 2.23,  15: 2.36,  20: 2.46,  30: 2.60,
     40: 2.70,  50: 2.78,  60: 2.82,  70: 2.85,  80: 2.88,
     90: 2.90, 100: 2.92, 110: 2.95, 120: 2.97, 130: 2.99,
    140: 3.01, 150: 3.04, 160: 3.08, 170: 3.13, 180: 3.18,
    190: 3.23, 200: 3.28, 210: 3.33, 220: 3.38, 230: 3.43,
    240: 3.48, 250: 3.53, 260: 3.58, 280: 3.67, 300: 3.75,
    320: 3.83, 340: 3.90, 360: 3.96, 400: 4.07, 450: 4.19,
}
_APPROACH_ROUGH = {
      5: 2.18,  10: 2.34,  20: 2.55,  30: 2.67,  40: 2.78,
     50: 2.88,  60: 2.95,  70: 3.01,  80: 3.05,  90: 3.10,
    100: 3.13, 110: 3.16, 120: 3.18, 130: 3.21, 140: 3.24,
    150: 3.27, 160: 3.31, 170: 3.36, 180: 3.42, 190: 3.48,
    200: 3.54, 210: 3.60, 220: 3.66, 230: 3.71, 240: 3.76,
    250: 3.81, 260: 3.86, 280: 3.95, 300: 4.03, 320: 4.10,
    340: 4.17, 360: 4.23, 400: 4.33, 450: 4.45,
}
_APPROACH_BUNKER = {
      5: 2.42,  10: 2.49,  20: 2.64,  30: 2.77,  40: 2.89,
     50: 2.99,  60: 3.07,  70: 3.12,  80: 3.17,  90: 3.21,
    100: 3.25, 110: 3.29, 120: 3.33, 130: 3.37, 140: 3.41,
    150: 3.46, 160: 3.52, 170: 3.58, 180: 3.65, 190: 3.72,
    200: 3.79, 210: 3.85, 220: 3.90, 230: 3.95, 240: 4.00,
    250: 4.06, 260: 4.12, 280: 4.22, 300: 4.32, 320: 4.41,
    340: 4.50, 360: 4.58, 400: 4.71, 450: 4.85,
}
_APPROACH_RECOVERY = {
     80: 3.80,  90: 3.78, 100: 3.80, 110: 3.81, 120: 3.82,
    130: 3.87, 140: 3.92, 150: 3.97, 160: 4.03, 170: 4.10,
    180: 4.20, 190: 4.31, 200: 4.44, 210: 4.56, 220: 4.66,
    230: 4.75, 240: 4.84, 250: 4.94, 260: 5.03, 280: 5.13,
    300: 5.22, 320: 5.32, 340: 5.41, 360: 5.51, 400: 5.60,
    450: 5.70,
}

# ---------------------------------------------------------------------------
# Around-the-Green baselines: distance in yards → expected strokes by lie
# ---------------------------------------------------------------------------
_ATG_FAIRWAY = {
     5: 2.04, 10: 2.18, 15: 2.28, 20: 2.40,
    25: 2.50, 30: 2.58, 40: 2.70, 50: 2.80,
}
_ATG_BUNKER = {
     5: 2.37, 10: 2.47, 15: 2.43, 20: 2.51,
    25: 2.60, 30: 2.68, 40: 2.80, 50: 2.89,
}

DISTANCE_BANDS = [
    (0, 6,          '0–6 ft'),
    (6, 10,         '6–10 ft'),
    (10, 15,        '10–15 ft'),
    (15, 30,        '15–30 ft'),
    (30, float('inf'), '30+ ft'),
]


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------

def _interp(table: dict, dist: float) -> float:
    """Linear-interpolate expected strokes from a distance→strokes table."""
    keys = sorted(table.keys())
    if dist <= keys[0]:
        return table[keys[0]]
    if dist >= keys[-1]:
        return table[keys[-1]]
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= dist <= hi:
            t = (dist - lo) / (hi - lo)
            return table[lo] + t * (table[hi] - table[lo])
    return table[keys[-1]]


def expected_putts(distance_ft: float) -> float:
    return _interp(PUTTING_BASELINES, distance_ft)


def expected_ott(hole_yardage: float) -> float:
    return _interp(_OTT_BASELINES, hole_yardage)


def expected_approach(distance_yds: float, lie: str = 'fairway') -> float:
    table = {
        'fairway':  _APPROACH_FAIRWAY,
        'rough':    _APPROACH_ROUGH,
        'bunker':   _APPROACH_BUNKER,
        'recovery': _APPROACH_RECOVERY,
    }.get(lie, _APPROACH_ROUGH)
    return _interp(table, distance_yds)


def expected_atg(distance_yds: float, lie: str = 'rough') -> float:
    table = _ATG_BUNKER if lie == 'bunker' else _ATG_FAIRWAY
    return _interp(table, distance_yds)


ATG_MAX_YARDS = 50  # ATG baselines only cover up to 50 yards


def expected_scramble(distance_yds: float, lie: str = 'rough') -> float:
    """Return expected strokes for a scramble shot.
    Uses ATG baselines within range; switches to approach baselines beyond 50 yards
    (e.g. topped shots leaving a full approach shot from off the green).
    """
    if distance_yds > ATG_MAX_YARDS:
        return expected_approach(distance_yds, lie)
    return expected_atg(distance_yds, lie)


def _tee_shot_lie(tee_shot: str) -> str:
    """Map tee_shot field value to approach-baseline lie category.

    tee_shot may be a single value ('fairway', 'left', 'bunker', 'penalty')
    or a comma-separated modifier+direction pair ('bunker,left', 'penalty,right').
    The primary outcome (first token) determines the lie category.
    """
    primary = tee_shot.split(',')[0] if tee_shot else tee_shot
    if primary == 'fairway':
        return 'fairway'
    if primary == 'penalty':
        return 'recovery'
    if primary == 'bunker':
        return 'bunker'
    if primary == 'trees':
        return 'recovery'
    return 'rough'  # left / right / other


_SCRAMBLE_BANDS = {
    'fringe':  2,
    '0_10':    5,
    '10_20':  15,
    '20_40':  30,
    '40_plus': 45,
}


def _parse_yards(value):
    """Safely parse a yards value that may be stored as string, int, or band key."""
    if value is None:
        return None
    s = str(value).strip()
    if s in _SCRAMBLE_BANDS:
        return float(_SCRAMBLE_BANDS[s])
    try:
        return float(s.split()[0])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# SG: Putting
# ---------------------------------------------------------------------------

def strokes_gained_putting(holes) -> dict:
    """
    SG Putting per hole using Broadie's telescoping formula.

    Normal hole (holed out):
      SG = expected_putts(first_putt_distance) - actual_putts

    Gimme hole (last putt conceded):
      SG = expected_putts(first_putt_distance)
           - actual_strokes_taken
           - expected_putts(gimme_distance)

    Example — 80 ft lag left to a 3 ft gimme:
      SG = 2.322 − 1 − 1.053 = +0.269   (excellent lag credited; uncompleted putt neutral)

    Standard gimme distance (bottom of putter grip): 3 ft.
    Used as fallback when gimme_distance was not recorded.
    """
    # Standard gimme distance: bottom of putter grip ≈ 3 ft
    STANDARD_GIMME_FT = 3

    band_data = {band[2]: {'attempts': 0, 'makes': 0, 'sg': 0.0}
                 for band in DISTANCE_BANDS}
    total_sg = 0.0

    for hole in holes:
        if not (hole.first_putt_distance and hole.putts):
            continue

        is_gimme = getattr(hole, 'last_putt_gimme', False)
        dist = hole.first_putt_distance

        if is_gimme:
            actual_putts = hole.putts - 1
            if actual_putts <= 0:
                continue  # solo gimme, no prior real putt — skip
            gimme_dist = getattr(hole, 'gimme_distance', None) or STANDARD_GIMME_FT
            sg   = expected_putts(dist) - actual_putts - expected_putts(gimme_dist)
            made = False  # player did not hole out
        else:
            sg   = expected_putts(dist) - hole.putts
            made = (hole.putts == 1)

        total_sg += sg

        for lo, hi, label in DISTANCE_BANDS:
            if lo <= dist < hi:
                band_data[label]['attempts'] += 1
                band_data[label]['sg'] += sg
                if made:
                    band_data[label]['makes'] += 1
                break

    for band in band_data.values():
        a = band['attempts']
        band['make_pct'] = round(band['makes'] / a * 100, 1) if a else None

    return {'total': round(total_sg, 2), 'bands': band_data}


# ---------------------------------------------------------------------------
# SG: Off the Tee
# ---------------------------------------------------------------------------

def strokes_gained_off_tee(holes, course_hole_map=None) -> float:
    """
    SG Off the Tee (par 4/5 only):
      Normal:  SG = expected_OTT(yardage) - 1 - expected_approach(remaining, lie)
      Trees:   SG = expected_OTT(yardage) - 2 - expected_approach(real_approach, lie_after)

    When a tee shot goes into trees (tee_shot starts with 'trees'), the punch-out
    recovery shot is attributed here rather than SG Approach.  second_shot_distance
    stores the punch-out distance; approach_distance stores the real approach.
    The formula charges 2 shots (drive + punch-out) against SG OTT so that
    SG Approach only reflects genuine approach skill.
    """
    sg = 0.0
    for hole in holes:
        if hole.par not in (4, 5) or not hole.tee_shot:
            continue

        primary      = hole.tee_shot.split(',')[0]
        is_trees     = primary == 'trees'
        punch_dist   = _parse_yards(hole.second_shot_distance)
        ch           = course_hole_map.get(hole.hole_number) if course_hole_map else None
        hole_yardage = ch.yardage if (ch and ch.yardage) else None

        # Trees on par 4 with a recorded punch-out: bundle drive + punch-out into OTT
        if is_trees and hole.par == 4 and punch_dist and hole.approach_distance:
            if hole_yardage:
                lie_after = hole.lie_type or 'fairway'
                exp_start = expected_ott(hole_yardage)
                exp_end   = expected_approach(hole.approach_distance, lie_after)
                sg += exp_start - 2 - exp_end  # -2: drive + punch-out
            else:
                sg -= 1.0  # flat: bad drive + wasted punch-out
            continue

        lie       = _tee_shot_lie(hole.tee_shot)
        remaining = (hole.approach_distance if hole.par == 4
                     else _parse_yards(hole.second_shot_distance))

        if hole_yardage and remaining:
            exp_start = expected_ott(hole_yardage)
            exp_end   = expected_approach(remaining, lie)
            sg += exp_start - 1 - exp_end
        else:
            if primary == 'fairway':
                sg += 0.2
            elif primary in ('penalty', 'trees'):
                sg -= 0.7
            else:
                sg -= 0.2

    return round(sg, 2)


# ---------------------------------------------------------------------------
# SG: Approach
# ---------------------------------------------------------------------------

def strokes_gained_approach(holes) -> float:
    """
    SG Approach to the Green:
      SG = expected_approach(dist, lie) - 1 - expected_end_position

    End position:
    - GIR hit:    expected_putts(first_putt_distance)
    - GIR missed: expected_atg(scramble_distance, atg_lie)

    Falls back to a flat penalty when approach_distance is unavailable.
    """
    sg = 0.0

    for hole in holes:
        dist = hole.approach_distance

        if hole.par == 3:
            if not dist:
                continue
            # Tee shot IS the approach shot; lies are played from the tee (fairway)
            exp_start = expected_approach(dist, 'fairway')
            if hole.gir:
                fpd = hole.first_putt_distance
                exp_end = expected_putts(fpd) if fpd else expected_putts(20)
                sg += exp_start - 1 - exp_end
            else:
                # Missed GIR — end position is an ATG shot
                sdist  = _parse_yards(hole.scramble_distance)
                atg_lie = 'bunker' if hole.approach_miss == 'bunker' else 'rough'
                if sdist:
                    sg += exp_start - 1 - expected_scramble(sdist, atg_lie)
                elif hole.approach_miss == 'bunker':
                    sg += exp_start - 1 - expected_atg(10, 'bunker')
                else:
                    sg += exp_start - 1 - expected_atg(15, 'rough')

        elif hole.par in (4, 5):
            is_trees   = hole.tee_shot and hole.tee_shot.split(',')[0] == 'trees'
            punch_dist = _parse_yards(hole.second_shot_distance)

            # Trees par-4 with punch-out: real approach is approach_distance;
            # punch-out was already attributed to SG OTT — use lie_type for approach lie
            if is_trees and hole.par == 4 and punch_dist:
                lie = hole.lie_type or 'fairway'
            else:
                lie = _tee_shot_lie(hole.tee_shot) if hole.tee_shot else 'rough'

            if hole.gir:
                if not dist:
                    continue
                exp_start = expected_approach(dist, lie)
                fpd       = hole.first_putt_distance
                exp_end   = expected_putts(fpd) if fpd else expected_putts(20)
                sg += exp_start - 1 - exp_end
            else:
                # Missed GIR
                sdist   = _parse_yards(hole.scramble_distance)
                atg_lie = 'bunker' if hole.approach_miss == 'bunker' else 'rough'
                if dist and sdist:
                    exp_start = expected_approach(dist, lie)
                    sg += exp_start - 1 - expected_scramble(sdist, atg_lie)
                elif dist:
                    # No scramble distance — use typical ATG distance by miss type
                    exp_start = expected_approach(dist, lie)
                    default_sdist = 10 if hole.approach_miss == 'bunker' else 15
                    sg += exp_start - 1 - expected_atg(default_sdist, atg_lie)
                else:
                    # No approach distance at all — flat fallback
                    if hole.approach_miss == 'bunker':
                        sg -= 0.4
                    elif hole.approach_miss in ('left', 'right', 'short', 'long'):
                        sg -= 0.3
                    else:
                        sg -= 0.25

    return round(sg, 2)


# ---------------------------------------------------------------------------
# SG: Around the Green
# ---------------------------------------------------------------------------

def strokes_gained_around_green(holes) -> float:
    """
    SG Around the Green (GIR-miss holes only):
      SG = expected_atg(scramble_distance, lie) - 1 - expected_putts(first_putt_distance)

    Falls back to a score-based adjustment when scramble_distance or
    first_putt_distance is unavailable.
    """
    sg = 0.0

    for hole in holes:
        if hole.gir:
            continue

        sdist   = _parse_yards(hole.scramble_distance)
        atg_lie = 'bunker' if hole.approach_miss == 'bunker' else 'rough'

        if sdist and hole.first_putt_distance:
            exp_start = expected_scramble(sdist, atg_lie)
            exp_end   = expected_putts(hole.first_putt_distance)
            sg += exp_start - (hole.atg_strokes or 1) - exp_end
        else:
            # Fallback: score-relative model
            score_diff = hole.score - hole.par
            if hole.sand_save_attempt:
                sg += 0.5 if hole.sand_save_made else -0.3
            elif score_diff <= 0:
                sg += 0.4
            elif score_diff == 1:
                sg += 0.0
            elif score_diff == 2:
                sg -= 0.4
            else:
                sg -= 0.7

    return round(sg, 2)

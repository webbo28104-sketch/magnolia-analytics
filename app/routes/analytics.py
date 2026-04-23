"""
Game-section analysis pages — Off the Tee, Approach, Around the Green, Putting.
Each page aggregates rolling stats across the last 25 complete rounds and passes
structured data to Chart.js-powered templates.

All routes are Pro-only; free users are redirected to the upgrade page.
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models.round import Round
from app.utils.access import is_pro
from app.utils.strokes_gained import _parse_yards

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

_ROUND_LIMIT = 25   # rolling window for all analysis pages


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pro_gate():
    if not is_pro(current_user):
        flash('Game analysis is a Magnolia Pro feature.', 'info')
        return redirect(url_for('main.upgrade'))
    return None


def _get_rounds():
    return (Round.query
            .filter_by(user_id=current_user.id, status='complete')
            .order_by(Round.date_played.desc())
            .limit(_ROUND_LIMIT)
            .all())


def _norm(r, attr):
    """Normalise a stored SG value to 18-hole equivalent."""
    v = getattr(r, attr, None)
    if v is not None and r.holes_played:
        return round(v / r.holes_played * 18, 2)
    return None


def _safe_avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _safe_pct(num, denom):
    return round(num / denom * 100, 1) if denom else None


def _hcp_equiv(sg_18h):
    """Convert an 18-hole SG value into an approximate handicap equivalent."""
    if sg_18h is None:
        return None
    if sg_18h >= 0:
        return 'Tour'
    hcp = round(-sg_18h)
    return f'+{abs(hcp)}' if hcp < 0 else str(hcp)


def _sg_color(val):
    """CSS colour token for an SG value."""
    if val is None:
        return 'mid'
    if val > 0.04:
        return 'best'
    if val < -0.04:
        return 'worst'
    return 'mid'


# ---------------------------------------------------------------------------
# Off the Tee
# ---------------------------------------------------------------------------

@analytics_bp.route('/off-the-tee')
@login_required
def off_the_tee():
    gate = _pro_gate()
    if gate:
        return gate

    rounds = _get_rounds()
    # Cache all holes upfront — one query per round (avoids repeated lazy-load hits)
    round_holes = {r.id: list(r.holes.all()) for r in rounds}
    all_holes   = [h for hs in round_holes.values() for h in hs]
    ott_holes   = [h for h in all_holes if h.par in (4, 5) and h.tee_shot]

    # ── Hero: SG OTT average ─────────────────────────────────────────────────
    sg_vals   = [_norm(r, 'sg_off_tee') for r in rounds]
    sg_ott_avg = _safe_avg(sg_vals)
    sg_color   = _sg_color(sg_ott_avg)

    # ── FIR% ─────────────────────────────────────────────────────────────────
    fir_holes     = [h for h in ott_holes if h.tee_shot is not None]
    fairways_hit  = sum(1 for h in fir_holes if h.tee_shot.split(',')[0] == 'fairway')
    fir_pct       = _safe_pct(fairways_hit, len(fir_holes))

    # ── Avg approach distance after tee (quality-of-position proxy) ──────────
    app_dists = [h.approach_distance for h in ott_holes if h.approach_distance]
    avg_approach  = round(sum(app_dists) / len(app_dists)) if app_dists else None

    # ── Miss direction distribution ───────────────────────────────────────────
    _miss_labels = {
        'fairway': 'Fairway', 'left': 'Miss Left', 'right': 'Miss Right',
        'bunker': 'Bunker', 'penalty': 'Penalty', 'trees': 'Trees/Recovery',
    }
    miss_counts = {}
    for h in fir_holes:
        key = h.tee_shot.split(',')[0]
        miss_counts[key] = miss_counts.get(key, 0) + 1
    total_tee = len(fir_holes)
    miss_data = sorted(
        [
            {
                'key': k,
                'label': _miss_labels.get(k, k.title()),
                'count': c,
                'pct':   round(c / total_tee * 100) if total_tee else 0,
            }
            for k, c in miss_counts.items()
        ],
        key=lambda x: x['count'], reverse=True,
    )

    # ── GIR rate by tee outcome ───────────────────────────────────────────────
    _outcome_acc = {}
    for h in fir_holes:
        key = h.tee_shot.split(',')[0]
        _outcome_acc.setdefault(key, [0, 0])
        _outcome_acc[key][0] += 1
        if h.gir:
            _outcome_acc[key][1] += 1
    gir_by_outcome = [
        {
            'label':   _miss_labels.get(k, k.title()),
            'total':   v[0],
            'gir':     v[1],
            'gir_pct': round(v[1] / v[0] * 100) if v[0] else 0,
        }
        for k, v in sorted(_outcome_acc.items(), key=lambda x: -x[1][0])
    ]

    # ── SG OTT trend (oldest → newest) ───────────────────────────────────────
    sg_trend = [
        {'date': r.date_played.strftime('%d %b'), 'value': _norm(r, 'sg_off_tee')}
        for r in reversed(rounds)
        if _norm(r, 'sg_off_tee') is not None
    ]

    # ── FIR% trend per round ──────────────────────────────────────────────────
    fir_trend = []
    for r in reversed(rounds):
        hs = [h for h in round_holes[r.id] if h.par in (4, 5) and h.tee_shot]
        if hs:
            pct = _safe_pct(
                sum(1 for h in hs if h.tee_shot.split(',')[0] == 'fairway'), len(hs)
            )
            if pct is not None:
                fir_trend.append({'date': r.date_played.strftime('%d %b'), 'value': pct})

    # ── Par 4 vs Par 5 GIR rates ─────────────────────────────────────────────
    for par in (4, 5):
        hs = [h for h in all_holes if h.par == par]
        # stored but not returned separately — included in gir_by_par below
    gir_by_par = {}
    for par in (4, 5):
        hs = [h for h in all_holes if h.par == par]
        if hs:
            gir_by_par[par] = {'total': len(hs), 'gir': sum(1 for h in hs if h.gir),
                                'gir_pct': _safe_pct(sum(1 for h in hs if h.gir), len(hs))}

    return render_template(
        'analytics/off_the_tee.html',
        sg_ott_avg=sg_ott_avg,
        sg_color=sg_color,
        hcp_equiv=_hcp_equiv(sg_ott_avg),
        fir_pct=fir_pct,
        fairways_hit=fairways_hit,
        total_fairways=len(fir_holes),
        avg_approach=avg_approach,
        miss_data=miss_data,
        gir_by_outcome=gir_by_outcome,
        gir_by_par=gir_by_par,
        sg_trend=sg_trend,
        fir_trend=fir_trend,
        rounds_count=len(rounds),
        total_tee=total_tee,
    )


# ---------------------------------------------------------------------------
# Approach
# ---------------------------------------------------------------------------

@analytics_bp.route('/approach')
@login_required
def approach():
    gate = _pro_gate()
    if gate:
        return gate

    rounds = _get_rounds()
    round_holes = {r.id: list(r.holes.all()) for r in rounds}
    all_holes   = [h for hs in round_holes.values() for h in hs]

    # ── Hero ──────────────────────────────────────────────────────────────────
    sg_vals       = [_norm(r, 'sg_approach') for r in rounds]
    sg_app_avg    = _safe_avg(sg_vals)
    sg_color      = _sg_color(sg_app_avg)

    # ── GIR% overall ─────────────────────────────────────────────────────────
    gir_holes = [h for h in all_holes if h.approach_distance is not None]
    gir_hit   = sum(1 for h in gir_holes if h.gir)
    gir_pct   = _safe_pct(gir_hit, len(gir_holes))

    # ── Avg approach distance ─────────────────────────────────────────────────
    app_dists    = [h.approach_distance for h in all_holes if h.approach_distance]
    avg_app_dist = round(sum(app_dists) / len(app_dists)) if app_dists else None

    # ── GIR% by lie type (fairway vs rough) ──────────────────────────────────
    _lie_map = {'fairway': [0, 0], 'rough': [0, 0], 'bunker': [0, 0]}
    for h in all_holes:
        if h.approach_distance is None:
            continue
        if h.par == 3:
            key = 'fairway'   # par 3: tee is always fairway lie
        elif h.tee_shot:
            primary = h.tee_shot.split(',')[0]
            key = 'bunker' if primary == 'bunker' else ('fairway' if primary == 'fairway' else 'rough')
        else:
            key = 'rough'
        _lie_map[key][0] += 1
        if h.gir:
            _lie_map[key][1] += 1
    gir_by_lie = [
        {'label': k.title(), 'total': v[0], 'gir': v[1],
         'gir_pct': round(v[1] / v[0] * 100) if v[0] else 0}
        for k, v in _lie_map.items() if v[0] > 0
    ]

    # ── GIR% by distance band ─────────────────────────────────────────────────
    _bands = [
        ('< 75 yds',    0,   75),
        ('75–100 yds',  75,  100),
        ('100–125 yds', 100, 125),
        ('125–150 yds', 125, 150),
        ('150–175 yds', 150, 175),
        ('175+ yds',    175, 9999),
    ]
    gir_by_distance = []
    for label, lo, hi in _bands:
        subset = [h for h in all_holes if h.approach_distance is not None
                  and lo <= h.approach_distance < hi]
        if subset:
            g = sum(1 for h in subset if h.gir)
            gir_by_distance.append({
                'label':    label,
                'attempts': len(subset),
                'gir':      g,
                'gir_pct':  round(g / len(subset) * 100) if subset else 0,
            })

    # ── Miss direction distribution ───────────────────────────────────────────
    _miss_labels = {
        'left': 'Miss Left', 'right': 'Miss Right',
        'long': 'Long', 'short': 'Short', 'bunker': 'Bunker',
    }
    miss_counts = {}
    for h in all_holes:
        if not h.gir and h.approach_miss:
            for part in h.approach_miss.split(','):
                part = part.strip()
                if part:
                    miss_counts[part] = miss_counts.get(part, 0) + 1
    total_miss = sum(miss_counts.values())
    miss_data = sorted(
        [
            {'key': k, 'label': _miss_labels.get(k, k.title()),
             'count': c, 'pct': round(c / total_miss * 100) if total_miss else 0}
            for k, c in miss_counts.items()
        ],
        key=lambda x: x['count'], reverse=True,
    )

    # ── SG Approach trend ─────────────────────────────────────────────────────
    sg_trend = [
        {'date': r.date_played.strftime('%d %b'), 'value': _norm(r, 'sg_approach')}
        for r in reversed(rounds)
        if _norm(r, 'sg_approach') is not None
    ]

    # ── GIR% trend per round ──────────────────────────────────────────────────
    gir_trend = []
    for r in reversed(rounds):
        hs = [h for h in round_holes[r.id] if h.approach_distance is not None]
        if hs:
            pct = _safe_pct(sum(1 for h in hs if h.gir), len(hs))
            if pct is not None:
                gir_trend.append({'date': r.date_played.strftime('%d %b'), 'value': pct})

    return render_template(
        'analytics/approach.html',
        sg_app_avg=sg_app_avg,
        sg_color=sg_color,
        hcp_equiv=_hcp_equiv(sg_app_avg),
        gir_pct=gir_pct,
        gir_hit=gir_hit,
        total_gir_holes=len(gir_holes),
        avg_app_dist=avg_app_dist,
        gir_by_lie=gir_by_lie,
        gir_by_distance=gir_by_distance,
        miss_data=miss_data,
        sg_trend=sg_trend,
        gir_trend=gir_trend,
        rounds_count=len(rounds),
    )


# ---------------------------------------------------------------------------
# Around the Green
# ---------------------------------------------------------------------------

@analytics_bp.route('/around-the-green')
@login_required
def around_green():
    gate = _pro_gate()
    if gate:
        return gate

    rounds = _get_rounds()
    round_holes = {r.id: list(r.holes.all()) for r in rounds}
    all_holes   = [h for hs in round_holes.values() for h in hs]
    atg_holes   = [h for h in all_holes if not h.gir]   # GIR-miss holes only

    # ── Hero ──────────────────────────────────────────────────────────────────
    sg_vals    = [_norm(r, 'sg_atg') for r in rounds]
    sg_atg_avg = _safe_avg(sg_vals)
    sg_color   = _sg_color(sg_atg_avg)

    # ── Scramble% ─────────────────────────────────────────────────────────────
    scramble_saves = sum(1 for h in atg_holes if h.score is not None and h.par is not None and h.score <= h.par)
    scramble_pct   = _safe_pct(scramble_saves, len(atg_holes))

    # ── Sand save% ───────────────────────────────────────────────────────────
    sand_attempts = [h for h in atg_holes if h.sand_save_attempt
                     or (h.lie_type and 'bunker' in h.lie_type.lower())]
    sand_saves    = sum(
        1 for h in sand_attempts
        if (h.sand_save_made is not None and h.sand_save_made)
        or (h.sand_save_made is None and h.score is not None and h.par is not None and h.score <= h.par)
    )
    sand_save_pct = _safe_pct(sand_saves, len(sand_attempts))

    # ── Avg scramble distance ─────────────────────────────────────────────────
    sdists = [_parse_yards(h.scramble_distance) for h in atg_holes
              if h.scramble_distance is not None]
    sdists = [v for v in sdists if v is not None]
    avg_scramble_dist = round(sum(sdists) / len(sdists)) if sdists else None

    # ── Save% by scramble distance band ──────────────────────────────────────
    _atg_bands = [
        ('Fringe',  'fringe',  2),
        ('0–10 yds',  '0_10',  5),
        ('10–20 yds', '10_20', 15),
        ('20–40 yds', '20_40', 30),
        ('40+ yds', '40_plus', 45),
    ]
    _band_keys = {'fringe': 2, '0_10': 5, '10_20': 15, '20_40': 30, '40_plus': 45}
    save_by_distance = []
    for label, bkey, mid_dist in _atg_bands:
        # Match holes whose scramble_distance is this key OR within the yardage range
        subset = []
        for h in atg_holes:
            sd = h.scramble_distance
            if sd is None:
                continue
            s = str(sd).strip()
            if s == bkey:
                subset.append(h)
            else:
                v = _parse_yards(s)
                if v is not None:
                    lo = _band_keys.get(bkey, mid_dist) - 0.5
                    # map band to yardage range
                    ranges = {'fringe': (0, 3), '0_10': (0, 10),
                              '10_20': (10, 20), '20_40': (20, 40), '40_plus': (40, 999)}
                    rng = ranges.get(bkey, (0, 999))
                    if rng[0] <= v < rng[1]:
                        subset.append(h)
        if not subset:
            continue
        saves = sum(1 for h in subset
                    if h.score is not None and h.par is not None and h.score <= h.par)
        save_by_distance.append({
            'label':    label,
            'attempts': len(subset),
            'saves':    saves,
            'save_pct': round(saves / len(subset) * 100) if subset else 0,
        })

    # ── Lie type distribution ─────────────────────────────────────────────────
    lie_counts = {}
    for h in atg_holes:
        if h.lie_type:
            for lt in h.lie_type.split(','):
                lt = lt.strip().lower()
                if lt:
                    lie_counts[lt] = lie_counts.get(lt, 0) + 1
        elif h.approach_miss == 'bunker':
            lie_counts['bunker'] = lie_counts.get('bunker', 0) + 1
    total_lies = sum(lie_counts.values())
    lie_data = sorted(
        [{'label': k.title(), 'count': v,
          'pct': round(v / total_lies * 100) if total_lies else 0}
         for k, v in lie_counts.items()],
        key=lambda x: x['count'], reverse=True,
    )

    # ── SG ATG trend ──────────────────────────────────────────────────────────
    sg_trend = [
        {'date': r.date_played.strftime('%d %b'), 'value': _norm(r, 'sg_atg')}
        for r in reversed(rounds)
        if _norm(r, 'sg_atg') is not None
    ]

    # ── Scramble% trend ───────────────────────────────────────────────────────
    scramble_trend = []
    for r in reversed(rounds):
        misses = [h for h in round_holes[r.id] if not h.gir]
        if misses:
            saves = sum(1 for h in misses if h.score is not None and h.par is not None and h.score <= h.par)
            pct   = _safe_pct(saves, len(misses))
            if pct is not None:
                scramble_trend.append({'date': r.date_played.strftime('%d %b'), 'value': pct})

    return render_template(
        'analytics/around_green.html',
        sg_atg_avg=sg_atg_avg,
        sg_color=sg_color,
        hcp_equiv=_hcp_equiv(sg_atg_avg),
        scramble_pct=scramble_pct,
        scramble_saves=scramble_saves,
        total_atg=len(atg_holes),
        sand_save_pct=sand_save_pct,
        sand_attempts=len(sand_attempts),
        avg_scramble_dist=avg_scramble_dist,
        save_by_distance=save_by_distance,
        lie_data=lie_data,
        sg_trend=sg_trend,
        scramble_trend=scramble_trend,
        rounds_count=len(rounds),
    )


# ---------------------------------------------------------------------------
# Putting
# ---------------------------------------------------------------------------

@analytics_bp.route('/putting')
@login_required
def putting():
    gate = _pro_gate()
    if gate:
        return gate

    rounds = _get_rounds()
    round_holes = {r.id: list(r.holes.all()) for r in rounds}
    all_holes   = [h for hs in round_holes.values() for h in hs]
    putt_holes  = [h for h in all_holes if h.putts is not None]

    # ── Hero ──────────────────────────────────────────────────────────────────
    sg_vals       = [_norm(r, 'sg_putting') for r in rounds]
    sg_putt_avg   = _safe_avg(sg_vals)
    sg_color      = _sg_color(sg_putt_avg)

    # ── Putts per hole ────────────────────────────────────────────────────────
    putts_per_hole = round(sum(h.putts for h in putt_holes) / len(putt_holes), 2) if putt_holes else None

    # ── Distance bands: make% and SG ─────────────────────────────────────────
    _bands = [
        ('0–6 ft',   0,  6),
        ('6–10 ft',  6,  10),
        ('10–15 ft', 10, 15),
        ('15–30 ft', 15, 30),
        ('30+ ft',   30, 9999),
    ]
    from app.utils.strokes_gained import expected_putts as _ep
    band_data = []
    for label, lo, hi in _bands:
        subset = [h for h in putt_holes
                  if h.first_putt_distance is not None and lo <= h.first_putt_distance < hi]
        if not subset:
            continue
        makes     = sum(1 for h in subset if h.putts == 1)
        avg_putts = round(sum(h.putts for h in subset) / len(subset), 2)
        sg_total  = round(sum(_ep(h.first_putt_distance) - h.putts for h in subset), 2)
        band_data.append({
            'label':     label,
            'attempts':  len(subset),
            'makes':     makes,
            'make_pct':  round(makes / len(subset) * 100) if subset else 0,
            'avg_putts': avg_putts,
            'sg':        sg_total,
        })

    # ── Make% inside 6 ft ────────────────────────────────────────────────────
    inside6 = [b for b in band_data if b['label'] == '0–6 ft']
    make_pct_6ft = inside6[0]['make_pct'] if inside6 else None
    makes_6ft    = inside6[0]['makes']    if inside6 else None
    total_6ft    = inside6[0]['attempts'] if inside6 else None

    # ── 3-putt rate ───────────────────────────────────────────────────────────
    three_putt_holes = sum(1 for h in putt_holes if h.putts >= 3)
    three_putt_pct   = _safe_pct(three_putt_holes, len(putt_holes))

    # ── 1-putt rate ───────────────────────────────────────────────────────────
    one_putt_holes = sum(1 for h in putt_holes if h.putts == 1)
    one_putt_pct   = _safe_pct(one_putt_holes, len(putt_holes))

    # ── Putting distribution (1 / 2 / 3 / 4+) ────────────────────────────────
    putt_dist = {1: 0, 2: 0, 3: 0, '4+': 0}
    for h in putt_holes:
        if h.putts <= 1:   putt_dist[1]  += 1
        elif h.putts == 2: putt_dist[2]  += 1
        elif h.putts == 3: putt_dist[3]  += 1
        else:              putt_dist['4+'] += 1

    # ── SG Putting trend ──────────────────────────────────────────────────────
    sg_trend = [
        {'date': r.date_played.strftime('%d %b'), 'value': _norm(r, 'sg_putting')}
        for r in reversed(rounds)
        if _norm(r, 'sg_putting') is not None
    ]

    # ── Putts per round trend ─────────────────────────────────────────────────
    putts_trend = []
    for r in reversed(rounds):
        hs = [h for h in round_holes[r.id] if h.putts is not None]
        if hs and r.holes_played:
            # normalise to 18-hole equivalent
            pph = round(sum(h.putts for h in hs) / r.holes_played * 18, 1)
            putts_trend.append({'date': r.date_played.strftime('%d %b'), 'value': pph})

    # ── Avg first putt distance ───────────────────────────────────────────────
    fpd_vals   = [h.first_putt_distance for h in putt_holes if h.first_putt_distance]
    avg_fpd    = round(sum(fpd_vals) / len(fpd_vals), 1) if fpd_vals else None

    return render_template(
        'analytics/putting.html',
        sg_putt_avg=sg_putt_avg,
        sg_color=sg_color,
        hcp_equiv=_hcp_equiv(sg_putt_avg),
        putts_per_hole=putts_per_hole,
        make_pct_6ft=make_pct_6ft,
        makes_6ft=makes_6ft,
        total_6ft=total_6ft,
        three_putt_pct=three_putt_pct,
        three_putt_holes=three_putt_holes,
        one_putt_pct=one_putt_pct,
        one_putt_holes=one_putt_holes,
        band_data=band_data,
        putt_dist=putt_dist,
        avg_fpd=avg_fpd,
        sg_trend=sg_trend,
        putts_trend=putts_trend,
        rounds_count=len(rounds),
        total_putt_holes=len(putt_holes),
    )

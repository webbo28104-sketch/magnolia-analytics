"""Shared personal-best utilities used by the dashboard, profile, and reports."""


def _pb(value, round_):
    return {'value': value, 'date_set': round_.date_played, 'round_id': round_.id}


def _sg_ok(holes):
    """
    Return a dict of which SG categories meet minimum data thresholds.
    Uses an already-loaded list of Hole objects to avoid extra DB queries.

    Thresholds:
      sg_off_tee  — >= 3 par-4/5 holes with tee_shot AND approach_distance
      sg_approach — >= 3 holes with approach_distance
      sg_atg      — >= 2 GIR misses with scramble_distance
      sg_putting  — >= 3 holes with first_putt_distance
    """
    par45 = [h for h in holes if h.par in (4, 5)]
    return {
        'sg_off_tee':  sum(1 for h in par45 if h.tee_shot and h.approach_distance) >= 3,
        'sg_approach': sum(1 for h in holes if h.approach_distance) >= 3,
        'sg_atg':      sum(1 for h in holes if not h.gir and h.scramble_distance) >= 2,
        'sg_putting':  sum(1 for h in holes if h.first_putt_distance) >= 3,
    }


def compute_all_personal_bests(rounds, holes_played=None):
    """
    Compute all-time personal bests across a list of complete Round objects.
    Uses stored Round fields only (no live recomputation).

    If holes_played is 9 or 18, only rounds matching that format are considered.
    SG categories are only included when the round meets minimum data thresholds
    (to exclude 0.0 values caused by insufficient data, not genuine performance).

    Returns a dict keyed by PB name. Each value is
    {'value': ..., 'date_set': date, 'round_id': int} or None.
    """
    if holes_played is not None:
        rounds = [r for r in rounds if r.holes_played == holes_played]

    pbs = {
        'lowest_score_vs_par': None,
        'best_gir_pct':        None,
        'best_fir_pct':        None,
        'best_sg_total':       None,
        'best_sg_off_tee':     None,
        'best_sg_approach':    None,
        'best_sg_atg':         None,
        'best_sg_putting':     None,
        'most_birdies':        None,
        'lowest_putts':        None,
    }

    for r in rounds:
        # Load holes once — reused for birdies and SG threshold checks
        holes = r.holes.all()
        sg_thresholds = _sg_ok(holes)

        # Lowest score vs par (lower is better)
        svp = r.score_vs_par()
        if svp is not None:
            if pbs['lowest_score_vs_par'] is None or svp < pbs['lowest_score_vs_par']['value']:
                pbs['lowest_score_vs_par'] = _pb(svp, r)

        # Best GIR% (higher is better)
        if r.gir_count is not None and r.holes_played:
            gir_pct = r.gir_count / r.holes_played * 100
            if pbs['best_gir_pct'] is None or gir_pct > pbs['best_gir_pct']['value']:
                pbs['best_gir_pct'] = _pb(round(gir_pct, 1), r)

        # Best FIR% (higher is better)
        if r.fairways_hit is not None and r.fairways_available:
            fir_pct = r.fairways_hit / r.fairways_available * 100
            if pbs['best_fir_pct'] is None or fir_pct > pbs['best_fir_pct']['value']:
                pbs['best_fir_pct'] = _pb(round(fir_pct, 1), r)

        # SG total — only if at least 2 categories met their threshold
        valid_cats = sum(sg_thresholds.values())
        if r.sg_total is not None and valid_cats >= 2:
            if pbs['best_sg_total'] is None or r.sg_total > pbs['best_sg_total']['value']:
                pbs['best_sg_total'] = _pb(round(r.sg_total, 2), r)

        # Individual SG categories — only if that category met its threshold
        for key, attr in [
            ('best_sg_off_tee',  'sg_off_tee'),
            ('best_sg_approach', 'sg_approach'),
            ('best_sg_atg',      'sg_atg'),
            ('best_sg_putting',  'sg_putting'),
        ]:
            if not sg_thresholds[attr]:
                continue
            val = getattr(r, attr, None)
            if val is not None:
                if pbs[key] is None or val > pbs[key]['value']:
                    pbs[key] = _pb(round(val, 2), r)

        # Most birdies in a single round (holes already loaded above)
        birdies = sum(
            1 for h in holes
            if h.score is not None and h.par is not None and (h.score - h.par) == -1
        )
        if birdies > 0:
            if pbs['most_birdies'] is None or birdies > pbs['most_birdies']['value']:
                pbs['most_birdies'] = _pb(birdies, r)

        # Lowest total putts (lower is better)
        if r.total_putts is not None:
            if pbs['lowest_putts'] is None or r.total_putts < pbs['lowest_putts']['value']:
                pbs['lowest_putts'] = _pb(r.total_putts, r)

    return pbs


def check_recent_personal_best(recent, prev_rounds):
    """
    Check if `recent` sets any personal best vs `prev_rounds`.

    Only compares against rounds of the same format (holes_played) as `recent`.
    SG categories are only checked when the recent round meets the minimum data
    threshold for that category, to exclude 0.0 values from insufficient data.
    Uses stored Round fields only (no live recomputation).

    Returns the most impressive PB dict {'label': str, 'priority': int} or None.
    """
    # Filter to same format — critical correctness guard
    same_fmt = [r for r in prev_rounds if r.holes_played == recent.holes_played]
    if not same_fmt:
        return None

    # Compute SG data thresholds for the recent round
    recent_holes = recent.holes.all()
    sg_thresholds = _sg_ok(recent_holes)

    pbs = []

    # 1. Lowest score vs par (lower is better)
    svp = recent.score_vs_par()
    if svp is not None:
        prev_svps = [r.score_vs_par() for r in same_fmt if r.score_vs_par() is not None]
        if prev_svps and svp < min(prev_svps):
            label = 'E' if svp == 0 else (f'+{svp}' if svp > 0 else str(svp))
            pbs.append({'label': f"Best score vs par you've ever recorded ({label})", 'priority': 1})

    # 2. Best GIR% (higher is better)
    if recent.gir_count is not None and recent.holes_played:
        gir_pct   = recent.gir_count / recent.holes_played * 100
        prev_girs = [r.gir_count / r.holes_played * 100
                     for r in same_fmt if r.gir_count is not None and r.holes_played]
        if prev_girs and gir_pct > max(prev_girs):
            pbs.append({'label': f"Best GIR rate you've ever recorded ({round(gir_pct)}%)", 'priority': 2})

    # 3. Best SG total — only if at least 2 categories have sufficient data
    valid_cats = sum(sg_thresholds.values())
    if recent.sg_total is not None and valid_cats >= 2:
        prev_totals = [r.sg_total for r in same_fmt if r.sg_total is not None]
        if prev_totals and recent.sg_total > max(prev_totals):
            sign = '+' if recent.sg_total > 0 else ''
            pbs.append({'label': f"Best Strokes Gained total you've ever recorded ({sign}{round(recent.sg_total, 1)})", 'priority': 3})

    # 4. Best SG individual categories — only if that category has sufficient data
    sg_cat_checks = [
        ('Putting',          'sg_putting'),
        ('Off the Tee',      'sg_off_tee'),
        ('Approach',         'sg_approach'),
        ('Around the Green', 'sg_atg'),
    ]
    for cat_name, attr in sg_cat_checks:
        if not sg_thresholds[attr]:
            continue
        cat_val = getattr(recent, attr, None)
        if cat_val is None:
            continue
        prev_vals = [getattr(r, attr) for r in same_fmt if getattr(r, attr) is not None]
        if prev_vals and cat_val > max(prev_vals):
            sign = '+' if cat_val > 0 else ''
            pbs.append({'label': f"Best SG: {cat_name} you've ever recorded ({sign}{round(cat_val, 1)})", 'priority': 4})

    return min(pbs, key=lambda x: x['priority']) if pbs else None

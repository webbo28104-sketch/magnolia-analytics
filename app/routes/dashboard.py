from flask import Blueprint, render_template, url_for
from flask_login import login_required, current_user
from datetime import date, timedelta
from app.models.round import Round
from app.models.hole import Hole

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    # Single query for all complete rounds — used for stats, glance, and recent list
    all_complete = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .order_by(Round.date_played.desc())
        .all()
    )

    recent_rounds = all_complete[:10]
    stats  = _compute_stats(all_complete[:20]) if all_complete else None
    glance = _compute_glance(all_complete) if all_complete else None

    # In-progress rounds â find the next unplayed hole for each
    in_progress = (
        Round.query
        .filter_by(user_id=current_user.id, status='in_progress')
        .order_by(Round.created_at.desc())
        .all()
    )
    in_progress_rounds = []
    for r in in_progress:
        saved_holes = {h.hole_number for h in r.holes}
        if r.holes_played == 9 and r.nine_hole_selection == 'back':
            hole_range = range(10, 19)
        elif r.holes_played == 9:
            hole_range = range(1, 10)
        else:
            hole_range = range(1, 19)
        next_seq = None
        for i, actual in enumerate(hole_range, start=1):
            if actual not in saved_holes:
                next_seq = i
                break
        if next_seq is None:
            next_seq = r.holes_played
        in_progress_rounds.append({
            'round': r,
            'next_hole_url': url_for('rounds.enter_hole', round_id=r.id, hole_number=next_seq),
            'holes_done': len(saved_holes),
        })

    return render_template('dashboard/index.html',
        recent_rounds=recent_rounds,
        stats=stats,
        glance=glance,
        in_progress_rounds=in_progress_rounds)


def _compute_stats(rounds):
    if not rounds:
        return None

    # Per-hole average score â normalises across 9 and 18-hole rounds
    scored = [r for r in rounds if r.total_score and r.holes_played]
    avg_score_per_hole = (
        round(sum(r.total_score / r.holes_played for r in scored) / len(scored), 2)
        if scored else None
    )

    # Aggregate all holes for per-hole metrics
    all_holes = [h for r in rounds for h in r.holes.all()]

    # GIR %
    gir_pct = (
        round(sum(1 for h in all_holes if h.gir) / len(all_holes) * 100, 1)
        if all_holes else None
    )

    # FIR % â only counted on par 4s and par 5s
    fir_holes = [h for h in all_holes if h.par in (4, 5) and h.tee_shot is not None]
    fir_pct = (
        round(sum(1 for h in fir_holes if h.tee_shot == 'fairway') / len(fir_holes) * 100, 1)
        if fir_holes else None
    )

    # Scramble %
    missed_gir = [h for h in all_holes if not h.gir]
    scramble_pct = (
        round(sum(1 for h in missed_gir if h.score is not None and h.par is not None and h.score <= h.par) / len(missed_gir) * 100, 1)
        if missed_gir else None
    )

    # Putts per hole
    putts_data = [h.putts for h in all_holes if h.putts is not None]
    putts_per_hole = (
        round(sum(putts_data) / len(putts_data), 2)
        if putts_data else None
    )

    # Average score by par type
    def avg_by_par(par_num):
        hs = [h for h in all_holes if h.par == par_num and h.score is not None]
        return round(sum(h.score for h in hs) / len(hs), 2) if hs else None

    return {
        'rounds_played': len(rounds),
        'avg_score_per_hole': avg_score_per_hole,
        'avg_par3': avg_by_par(3),
        'avg_par4': avg_by_par(4),
        'avg_par5': avg_by_par(5),
        'gir_pct': gir_pct,
        'fir_pct': fir_pct,
        'scramble_pct': scramble_pct,
        'putts_per_hole': putts_per_hole,
    }


def _compute_glance(all_rounds):
    """Compute 'Your Game at a Glance' engagement metrics from all complete rounds."""
    if not all_rounds:
        return None

    today = date.today()
    glance = {}

    # 1. Streak — consecutive weeks (ISO) going back from most recent round's week
    weeks_with_rounds = set()
    for r in all_rounds:
        iso = r.date_played.isocalendar()
        weeks_with_rounds.add((iso[0], iso[1]))

    streak = 0
    check = all_rounds[0].date_played          # start from most recent round
    while True:
        iso = check.isocalendar()
        if (iso[0], iso[1]) in weeks_with_rounds:
            streak += 1
            check -= timedelta(weeks=1)
        else:
            break
    glance['streak'] = streak                  # always >= 1

    # 2. Rounds this month vs last month
    glance['this_month'] = sum(
        1 for r in all_rounds
        if r.date_played.year == today.year and r.date_played.month == today.month
    )
    last_month_year = today.year if today.month > 1 else today.year - 1
    last_month_num  = today.month - 1 if today.month > 1 else 12
    glance['prev_month'] = sum(
        1 for r in all_rounds
        if r.date_played.year == last_month_year and r.date_played.month == last_month_num
    )

    # 3. Best SG category across last 5 rounds with trend (need >= 2 rounds with SG data)
    sg_cats = {
        'Putting':          'sg_putting',
        'Off the Tee':      'sg_off_tee',
        'Approach':         'sg_approach',
        'Around the Green': 'sg_atg',
    }
    last5_sg = [r for r in all_rounds[:5] if any(getattr(r, a) is not None for a in sg_cats.values())]

    if len(last5_sg) >= 2:
        avgs = {}
        for cat_name, attr in sg_cats.items():
            vals = [getattr(r, attr) for r in last5_sg if getattr(r, attr) is not None]
            if vals:
                avgs[cat_name] = sum(vals) / len(vals)

        if avgs:
            best_cat = max(avgs, key=avgs.get)
            attr     = sg_cats[best_cat]
            newest   = getattr(last5_sg[0], attr)
            oldest   = getattr(last5_sg[-1], attr)
            trend    = ('up' if newest > oldest else 'down') if (newest is not None and oldest is not None) else None
            glance['best_sg_cat']    = best_cat
            glance['best_sg_trend']  = trend
            glance['sg_rounds_count'] = len(last5_sg)
        else:
            glance['best_sg_cat'] = None
    else:
        glance['best_sg_cat'] = None

    # 4. Personal best from the most recent round vs all previous
    glance['recent_pb'] = (
        _check_personal_best(all_rounds[0], all_rounds[1:])
        if len(all_rounds) >= 2 else None
    )

    return glance


def _check_personal_best(recent, prev_rounds):
    """Return the most impressive personal best set by recent vs prev_rounds, or None."""
    if not prev_rounds:
        return None

    pbs = []

    # Score vs par — lower is better
    recent_svp = recent.score_vs_par()
    if recent_svp is not None:
        prev_svps = [r.score_vs_par() for r in prev_rounds if r.score_vs_par() is not None]
        if prev_svps and recent_svp < min(prev_svps):
            label = 'E' if recent_svp == 0 else (f'+{recent_svp}' if recent_svp > 0 else str(recent_svp))
            pbs.append({'label': f'Best score vs par ({label})', 'priority': 1})

    # GIR% — higher is better
    if recent.gir_count is not None and recent.holes_played:
        recent_gir = recent.gir_count / recent.holes_played * 100
        prev_girs  = [r.gir_count / r.holes_played * 100
                      for r in prev_rounds if r.gir_count is not None and r.holes_played]
        if prev_girs and recent_gir > max(prev_girs):
            pbs.append({'label': f'Best GIR% ({round(recent_gir)}%)', 'priority': 2})

    # SG total — higher is better (more positive / least negative = more strokes gained)
    if recent.sg_total is not None:
        prev_sg = [r.sg_total for r in prev_rounds if r.sg_total is not None]
        if prev_sg and recent.sg_total > max(prev_sg):
            sign = '+' if recent.sg_total > 0 else ''
            pbs.append({'label': f'Best SG Total ({sign}{round(recent.sg_total, 1)})', 'priority': 3})

    # Individual SG categories — higher is better (same direction as SG total)
    sg_cat_checks = [
        ('Putting',          recent.sg_putting,  'sg_putting'),
        ('Off the Tee',      recent.sg_off_tee,  'sg_off_tee'),
        ('Approach',         recent.sg_approach, 'sg_approach'),
        ('Around the Green', recent.sg_atg,      'sg_atg'),
    ]
    for cat_name, cat_val, attr in sg_cat_checks:
        if cat_val is None:
            continue
        prev_vals = [getattr(r, attr) for r in prev_rounds if getattr(r, attr) is not None]
        if prev_vals and cat_val > max(prev_vals):
            sign = '+' if cat_val > 0 else ''
            pbs.append({'label': f'Best SG: {cat_name} ({sign}{round(cat_val, 1)})', 'priority': 4})

    return min(pbs, key=lambda x: x['priority']) if pbs else None

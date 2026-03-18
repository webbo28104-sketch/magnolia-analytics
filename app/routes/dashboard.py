from flask import Blueprint, render_template, url_for
from flask_login import login_required, current_user
from app.models.round import Round
from app.models.hole import Hole

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    recent_rounds = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .order_by(Round.date_played.desc())
        .limit(10)
        .all()
    )

    # Season stats — split by holes played so 9-hole rounds don't skew 18-hole averages
    all_complete = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .all()
    )
    rounds_18 = [r for r in all_complete if r.holes_played == 18]
    rounds_9  = [r for r in all_complete if r.holes_played == 9]

    stats   = _compute_season_stats(rounds_18) if rounds_18 else None
    stats_9 = _compute_season_stats(rounds_9)  if rounds_9  else None

    # In-progress rounds — find the next unplayed hole for each
    in_progress = (
        Round.query
        .filter_by(user_id=current_user.id, status='in_progress')
        .order_by(Round.created_at.desc())
        .all()
    )
    in_progress_rounds = []
    for r in in_progress:
        saved_holes = {h.hole_number for h in r.holes}
        if r.holes_played == 18 and r.back_nine_start:
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
                           stats_9=stats_9,
                           in_progress_rounds=in_progress_rounds)


def _compute_season_stats(rounds):
    if not rounds:
        return None

    scores  = [r.total_score for r in rounds if r.total_score]
    putts   = [r.total_putts for r in rounds if r.total_putts]
    vs_pars = [v for v in (r.score_vs_par() for r in rounds) if v is not None]

    # GIR% — per-round percentage then averaged
    gir_pcts = [
        r.gir_count / r.holes_played * 100
        for r in rounds
        if r.gir_count is not None and r.holes_played
    ]

    # Scramble% — missed GIR holes where par or better was still made
    all_holes = [h for r in rounds for h in r.holes.all()]
    missed_gir = [h for h in all_holes if not h.gir]
    scrambled  = [h for h in missed_gir if h.score <= h.par]

    return {
        'rounds_played':     len(rounds),
        'avg_score':         round(sum(scores)   / len(scores),   1) if scores   else None,
        'best_vs_par':       min(vs_pars)                            if vs_pars  else None,
        'avg_putts':         round(sum(putts)    / len(putts),    1) if putts    else None,
        'avg_gir_pct':       round(sum(gir_pcts) / len(gir_pcts), 1) if gir_pcts else None,
        'avg_scramble_pct':  round(100 * len(scrambled) / len(missed_gir), 1) if missed_gir else None,
    }

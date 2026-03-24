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

    last_20 = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .order_by(Round.date_played.desc())
        .limit(20)
        .all()
    )
    stats = _compute_stats(last_20) if last_20 else None

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
        in_progress_rounds=in_progress_rounds)


def _compute_stats(rounds):
    if not rounds:
        return None

    # Per-hole average score — normalises across 9 and 18-hole rounds
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

    # FIR % — only counted on par 4s and par 5s
    fir_holes = [h for h in all_holes if h.par in (4, 5)]
    fir_pct = (
        round(sum(1 for h in fir_holes if h.fir) / len(fir_holes) * 100, 1)
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

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

    # Season stats summary
    season_rounds = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .all()
    )

    stats = _compute_season_stats(season_rounds)

    # In-progress rounds — find the next unplayed hole for each (Task 11)
    in_progress = (
        Round.query
        .filter_by(user_id=current_user.id, status='in_progress')
        .order_by(Round.created_at.desc())
        .all()
    )
    in_progress_rounds = []
    for r in in_progress:
        saved_holes = {h.hole_number for h in r.holes.all()}
        # Determine the range of actual course holes for this round
        if r.nine_hole_selection == 'back' and r.holes_played == 9:
            hole_range = range(10, 19)
        elif r.holes_played == 9:
            hole_range = range(1, 10)
        else:
            hole_range = range(1, 19)
        # Find first unsaved hole; map back to sequential URL number
        next_seq = None
        for i, actual in enumerate(hole_range, start=1):
            if actual not in saved_holes:
                next_seq = i
                break
        # All holes done but not submitted → send to review
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


def _compute_season_stats(rounds):
    if not rounds:
        return {}

    scores = [r.total_score for r in rounds if r.total_score]
    putts = [r.total_putts for r in rounds if r.total_putts]
    girs = [r.gir_count for r in rounds if r.gir_count is not None]

    return {
        'rounds_played': len(rounds),
        'avg_score': round(sum(scores) / len(scores), 1) if scores else None,
        'best_score': min(scores) if scores else None,
        'avg_putts': round(sum(putts) / len(putts), 1) if putts else None,
        'avg_gir': round(sum(girs) / len(girs), 1) if girs else None,
    }

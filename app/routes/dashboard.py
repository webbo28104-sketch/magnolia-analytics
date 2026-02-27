from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models.round import Round

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

    return render_template('dashboard/index.html',
                           recent_rounds=recent_rounds,
                           stats=stats)


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

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models.round import Round

profile_bp = Blueprint('profile', __name__)


def _round_stats(rounds):
    """Compute per-hole stats for a list of completed rounds."""
    if not rounds:
        return None
    all_holes = []
    for r in rounds:
        all_holes.extend(r.holes.all())
    if not all_holes:
        return None

    scored = [r for r in rounds if r.total_score]
    avg_score = (sum(r.total_score for r in scored) / len(scored)) if scored else None

    gir_pct = round(sum(1 for h in all_holes if h.gir) / len(all_holes) * 100)

    missed = [h for h in all_holes if not h.gir]
    scramble_pct = (round(sum(1 for h in missed if h.score <= h.par) / len(missed) * 100)
                    if missed else None)

    putts_data = [h.putts for h in all_holes if h.putts is not None]
    putts_per_hole = (round(sum(putts_data) / len(putts_data), 1) if putts_data else None)

    return {
        'count':          len(rounds),
        'avg_score':      round(avg_score, 1) if avg_score else None,
        'gir_pct':        gir_pct,
        'scramble_pct':   scramble_pct,
        'putts_per_hole': putts_per_hole,
    }


@profile_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        first_name   = request.form.get('first_name', '').strip()
        last_name    = request.form.get('last_name', '').strip()
        home_course  = request.form.get('home_course', '').strip()
        home_country = request.form.get('home_country', '').strip()

        if not first_name or not last_name:
            flash('First and last name are required.', 'error')
            return redirect(url_for('profile.index'))

        current_user.first_name   = first_name
        current_user.last_name    = last_name
        current_user.home_course  = home_course
        current_user.home_country = home_country
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile.index'))

    completed = Round.query.filter_by(
        user_id=current_user.id, status='complete'
    ).all()

    stats_9  = _round_stats([r for r in completed if r.holes_played == 9])
    stats_18 = _round_stats([r for r in completed if r.holes_played == 18])

    # Lifetime stats — computed per hole across all completed rounds
    all_holes = []
    for r in completed:
        all_holes.extend(r.holes.all())

    lifetime = {
        'holes_in_one':    sum(1 for h in all_holes if h.score == 1),
        'total_birdies':   sum(1 for h in all_holes if (h.score - h.par) == -1),
        'courses_played':  len({r.course_id for r in completed if r.course_id}),
    }

    return render_template(
        'profile/index.html',
        stats_9=stats_9,
        stats_18=stats_18,
        lifetime=lifetime,
    )

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models.round import Round
from app.utils.personal_bests import compute_all_personal_bests

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        first_name  = request.form.get('first_name',  '').strip()
        last_name   = request.form.get('last_name',   '').strip()
        home_course  = request.form.get('home_course',  '').strip()
        home_country = request.form.get('home_country', '').strip()

        if not first_name or not last_name:
            flash('First and last name are required.', 'error')
            return redirect(url_for('profile.index'))

        current_user.first_name  = first_name
        current_user.last_name   = last_name
        current_user.home_course  = home_course
        current_user.home_country = home_country
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile.index'))

    completed = Round.query.filter_by(
        user_id=current_user.id, status='complete'
    ).all()

    all_holes = []
    for r in completed:
        all_holes.extend(r.holes.all())

    lifetime = {
        'total_rounds':   len(completed),
        'total_holes':    len(all_holes),
        'courses_played': len({r.course_id for r in completed if r.course_id}),
        'holes_in_one':   sum(1 for h in all_holes if h.score == 1),
        'total_eagles':   sum(
            1 for h in all_holes
            if h.score is not None and h.par is not None and (h.score - h.par) <= -2
        ),
        'total_birdies':  sum(
            1 for h in all_holes
            if h.score is not None and h.par is not None and (h.score - h.par) == -1
        ),
        'total_pars':     sum(
            1 for h in all_holes
            if h.score is not None and h.par is not None and (h.score - h.par) == 0
        ),
    }

    personal_bests = compute_all_personal_bests(completed)

    return render_template(
        'profile/index.html',
        lifetime=lifetime,
        personal_bests=personal_bests,
    )

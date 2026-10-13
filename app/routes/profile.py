import json
import re

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

    pb_18 = compute_all_personal_bests(completed, holes_played=18)
    pb_9  = compute_all_personal_bests(completed, holes_played=9)
    has_18 = any(r.holes_played == 18 for r in completed)
    has_9  = any(r.holes_played == 9  for r in completed)

    try:
        eg_scores = json.loads(current_user.eg_scores_json or '[]')
    except ValueError:
        eg_scores = []

    return render_template(
        'profile/index.html',
        eg_scores=eg_scores,
        lifetime=lifetime,
        pb_18=pb_18,
        pb_9=pb_9,
        has_18=has_18,
        has_9=has_9,
    )


# ── England Golf link ────────────────────────────────────────────────────────

@profile_bp.route('/england-golf', methods=['POST'])
@login_required
def england_golf_connect():
    from app.utils import england_golf as eg
    from app.utils.eg_sync import sync_user

    member_no = re.sub(r'\D', '', request.form.get('eg_member_no', ''))
    password = request.form.get('eg_password', '')
    if not member_no or not password:
        flash('Enter your England Golf membership number and password.', 'error')
        return redirect(url_for('profile.index') + '#england-golf')
    if request.form.get('eg_consent') != 'yes':
        flash('Tick the box to allow Magnolia to log in to England Golf for you.', 'error')
        return redirect(url_for('profile.index') + '#england-golf')
    try:
        current_user.eg_member_no = member_no
        current_user.eg_password_enc = eg.encrypt(password)
    except eg.EGError as e:
        flash(str(e), 'error')
        return redirect(url_for('profile.index') + '#england-golf')
    db.session.commit()
    if sync_user(current_user):
        hi = current_user.eg_handicap_index
        flash('Connected to England Golf.' + (f' Handicap Index {hi:.1f}.' if hi is not None else ''), 'success')
    else:
        flash(current_user.eg_error or 'Could not connect to England Golf.', 'error')
    return redirect(url_for('profile.index') + '#england-golf')


@profile_bp.route('/england-golf/sync', methods=['POST'])
@login_required
def england_golf_sync():
    from app.utils.eg_sync import sync_user
    if sync_user(current_user):
        flash('England Golf synced.', 'success')
    else:
        flash(current_user.eg_error or 'Sync failed.', 'error')
    return redirect(url_for('profile.index') + '#england-golf')


@profile_bp.route('/england-golf/disconnect', methods=['POST'])
@login_required
def england_golf_disconnect():
    for col in ('eg_member_no', 'eg_password_enc', 'eg_status', 'eg_error', 'eg_last_sync',
                'eg_handicap_index', 'eg_scores_json', 'eg_pages_text'):
        setattr(current_user, col, None)
    db.session.commit()
    flash('England Golf disconnected and your saved password deleted.', 'success')
    return redirect(url_for('profile.index') + '#england-golf')

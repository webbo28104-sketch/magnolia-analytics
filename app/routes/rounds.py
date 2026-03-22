from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.round import Round
from app.models.hole import Hole
from app.models.course import Course
from app.models.tee_set import TeeSet
from app.models.course_hole import CourseHole
from app.services.claude_service import generate_report
from app.services.sendgrid_service import send_report_email
from datetime import datetime, date

rounds_bp = Blueprint('rounds', __name__)


def _recalculate_handicap(user):
    """Recalculate user.handicap_index using proper WHS rules."""
    rounds = (
        Round.query
        .filter_by(user_id=user.id, status='complete')
        .filter(Round.hc_differential.isnot(None))
        .order_by(Round.date_played.desc())
        .limit(20)
        .all()
    )

    count = len(rounds)
    if count < 3:
        return

    diffs = sorted(r.hc_differential for r in rounds)

    # --- WHS RULES ---
    if count == 3:
        new_index = diffs[0] - 2.0

    elif count == 4:
        new_index = diffs[0] - 1.0

    elif count == 5:
        new_index = diffs[0]

    else:
        n_map = {
            6: 2, 7: 2, 8: 2,
            9: 3, 10: 3, 11: 3,
            12: 4, 13: 4, 14: 4,
            15: 5, 16: 5,
            17: 6, 18: 6,
            19: 7,
        }
        n = n_map.get(count, 8)

        best = diffs[:n]
        avg = sum(best) / n

        if 6 <= count <= 8:
            avg -= 1.0
        elif 9 <= count <= 11:
            avg -= 0.5
        elif 15 <= count <= 16:
            avg += 0.5
        elif 17 <= count <= 18:
            avg += 1.0
        elif count == 19:
            avg += 1.5
        elif count >= 20:
            avg *= 0.96

        new_index = avg

    user.handicap_index = round(new_index, 1)
    db.session.commit()

    current_app.logger.info(
        f"[handicap] {user.email} -> {user.handicap_index} "
        f"(from {count} rounds, diffs={diffs})"
    )


@rounds_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_round():
    if request.method == 'POST':
        course_id   = request.form.get('course_id')
        tee_set_id  = request.form.get('tee_set_id')
        date_played = request.form.get('date_played', date.today().isoformat())
        holes_played = int(request.form.get('holes_played', 18))
        nine_hole_selection = request.form.get('nine_hole_selection') or None

        if holes_played != 9:
            nine_hole_selection = None

        if not course_id or not tee_set_id:
            flash('Please select a course and tee.', 'error')
            return redirect(url_for('rounds.new_round'))

        tee = db.session.get(TeeSet, int(tee_set_id))
        if not tee:
            flash('Selected tee not found.', 'error')
            return redirect(url_for('rounds.new_round'))

        round_ = Round(
            user_id=current_user.id,
            course_id=tee.course_id,
            tee_set_id=int(tee_set_id),
            date_played=datetime.strptime(date_played, '%Y-%m-%d').date(),
            tee_set=tee.name,
            holes_played=holes_played,
            nine_hole_selection=nine_hole_selection,
            status='in_progress'
        )
        db.session.add(round_)
        db.session.commit()

        return redirect(url_for('rounds.enter_hole', round_id=round_.id, hole_number=1))

    return render_template('rounds/new.html', today=date.today().isoformat())


@rounds_bp.route('/<int:round_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        round_.status = 'complete'
        round_.completed_at = datetime.utcnow()

        try:
            round_.compute_totals()
            round_.compute_differential()
        except Exception as e:
            current_app.logger.exception(f"Compute failed: {e}")

        db.session.commit()

        try:
            _recalculate_handicap(current_user)
        except Exception as e:
            current_app.logger.exception(f"Handicap failed: {e}")

        try:
            generate_report(round_)
            send_report_email(round_)
        except Exception:
            pass

        return redirect(url_for('dashboard.index'))

    return render_template('rounds/submit.html', round=round_)

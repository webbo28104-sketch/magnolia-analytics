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


# ---------------------------------------------------------------------------
# USGA World Handicap System â differentials-to-use lookup table
# ---------------------------------------------------------------------------
_WHS_TABLE = {
    3: 1,  4: 1,  5: 1,
    6: 2,  7: 2,  8: 2,
    9: 3,  10: 3, 11: 3,
    12: 4, 13: 4, 14: 4,
    15: 5, 16: 5,
    17: 6, 18: 6,
    19: 7,
}


def _recalculate_handicap(user):
    """Recalculate user.handicap_index using WHS (best N of last 20 diffs Ã 0.96)."""
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
        return  # Need at least 3 rounds
    n_to_use = _WHS_TABLE.get(count, 8)   # 20+ rounds -> use best 8
    diffs = sorted(r.hc_differential for r in rounds)
    best  = diffs[:n_to_use]
    new_index = round(sum(best) / n_to_use * 0.96, 1)
    user.handicap_index = new_index
    db.session.commit()
    current_app.logger.info(
        f"[handicap] {user.email} -> {new_index} "
        f"(best {n_to_use} of {count} diffs)"
    )


@rounds_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_round():
    """Start a new round â USGA-style course + tee selector."""
    if request.method == 'POST':
        course_id   = request.form.get('course_id')
        tee_set_id  = request.form.get('tee_set_id')
        date_played = request.form.get('date_played', date.today().isoformat())
        holes_played = int(request.form.get('holes_played', 18))
        nine_hole_selection = request.form.get('nine_hole_selection') or None
        # Only valid when actually playing 9 holes
        if holes_played != 9:
            nine_hole_selection = None

        if not course_id or not tee_set_id:
            flash('Please select a course and tee.', 'error')
            return redirect(url_for('rounds.new_round'))

        tee = db.session.get(TeeSet, int(tee_set_id))
        if not tee:
            flash('Selected tee not found. Please try again.', 'error')
            return redirect(url_for('rounds.new_round'))

        # Always use the course_id from the tee (avoids stale hidCourseId)
        course_id = tee.course_id
        tee_label = tee.name

        round_ = Round(
            user_id=current_user.id,
            course_id=course_id,
            tee_set_id=int(tee_set_id),
            date_played=datetime.strptime(date_played, '%Y-%m-%d').date(),
            tee_set=tee_label,
            holes_played=holes_played,
            nine_hole_selection=nine_hole_selection,
            status='in_progress'
        )
        db.session.add(round_)
        db.session.commit()

        return redirect(url_for('rounds.enter_hole', round_id=round_.id, hole_number=1))

    return render_template('rounds/new.html', today=date.today().isoformat())


@rounds_bp.route('/<int:round_id>/hole/<int:hole_number>', methods=['GET', 'POST'])
@login_required
def enter_hole(round_id, hole_number):
    """Enter stats for a single hole."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    if hole_number < 1 or hole_number > round_.holes_played:
        return redirect(url_for('rounds.enter_hole', round_id=round_.id, hole_number=1))

    # For back-9 rounds, sequential entry 1-9 maps to course holes 10-18
    if round_.nine_hole_selection == 'back' and round_.holes_played == 9:
        actual_hole_number = hole_number + 9
    else:
        actual_hole_number = hole_number

    # Get existing data if re-visiting a hole (keyed on actual course hole)
    existing = Hole.query.filter_by(round_id=round_id, hole_number=actual_hole_number).first()

    # Determine par and yardage from the specific tee set's hole data (real API data)
    course_par = None
    course_yardage = None
    if round_.tee_set_id:
        ch = CourseHole.query.filter_by(
            tee_set_id=round_.tee_set_id,
            hole_number=actual_hole_number
        ).first()
        if ch:
            course_par = ch.par
            course_yardage = ch.yardage
    # Fallback: use course-level par distribution (index by actual hole)
    if course_par is None and round_.course and round_.course.par_list:
        course_par = round_.course.par_list[actual_hole_number - 1]

    if request.method == 'POST':
        data = request.form

        # Upsert hole (stored under the actual course hole number)
        if not existing:
            hole = Hole(round_id=round_id, hole_number=actual_hole_number)
            db.session.add(hole)
        else:
            hole = existing

        hole.par = int(data.get('par', course_par or 4))
        hole.score = int(data.get('score', hole.par))
        hole.tee_shot = data.get('tee_shot') or None

        # Approach / miss (GIR is auto-calculated)
        hole.approach_distance = int(data['approach_distance']) if data.get('approach_distance') else None
        hole.approach_miss = data.get('approach_miss') or None
        hole.scramble_distance = data.get('scramble_distance') or None
        # GIR = made the green in regulation â true when no miss recorded
        hole.gir = not bool(hole.approach_miss or hole.scramble_distance)

        # Par 5 second shot
        hole.second_shot_distance = int(data['second_shot_distance']) if data.get('second_shot_distance') else None

        hole.putts = int(data.get('putts', 2))
        hole.first_putt_distance = int(data['first_putt_distance']) if data.get('first_putt_distance') else None
        hole.sand_save_attempt = bool(data.get('sand_save_attempt') == 'true') if data.get('sand_save_attempt') else None
        hole.sand_save_made = data.get('sand_save_made') == 'true' if data.get('sand_save_made') else None
        hole.penalties = int(data.get('penalties', 0))

        db.session.commit()

        # Navigate to next hole or submit
        if hole_number < round_.holes_played:
            return redirect(url_for('rounds.enter_hole', round_id=round_id, hole_number=hole_number + 1))
        else:
            return redirect(url_for('rounds.submit_round', round_id=round_id))

    # Previous hole score for progress indicator
    prev_actual = (actual_hole_number - 1) if actual_hole_number > 1 else None
    prev_hole = Hole.query.filter_by(round_id=round_id, hole_number=prev_actual).first() if prev_actual else None

    is_edit = round_.holes.count() >= round_.holes_played
    return render_template('rounds/hole.html',
                           round=round_,
                           hole_number=hole_number,
                           display_hole_number=actual_hole_number,
                           existing=existing,
                           course_par=course_par,
                           course_yardage=course_yardage,
                           total_holes=round_.holes_played,
                           prev_hole=prev_hole,
                           is_edit=is_edit)


@rounds_bp.route('/<int:round_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_round(round_id):
    """Review and finalise the round, trigger report generation."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        current_app.logger.info(f"[submit_round] POST received for round_id={round_id}")

        # Mark the round complete first â this must commit regardless of what follows
        round_.status = 'complete'
        round_.completed_at = datetime.utcnow()

        # Compute totals / differential â errors here are non-fatal; round still saves
        try:
            round_.compute_totals()
            round_.compute_differential()   # USGA handicap differential
        except Exception as e:
            current_app.logger.exception(f"[submit_round] compute_totals/differential failed for round {round_id}: {e}")

        db.session.commit()
        current_app.logger.info(f"[submit_round] Round {round_id} committed as complete")

        # Recalculate handicap index from latest round history (non-fatal)
        try:
            _recalculate_handicap(current_user)
        except Exception as e:
            current_app.logger.exception(f"[submit_round] Handicap recalc failed: {e}")

        # Trigger report generation â failure must never roll back the round save
        try:
            generate_report(round_)
            send_report_email(round_)
            flash('Your round has been saved and your report is on its way!', 'success')
        except Exception as e:
            current_app.logger.exception(f"[submit_round] Report generation failed for round {round_id}: {e}")
            flash('Round saved! Report generation is in the queue.', 'info')

        return redirect(url_for('dashboard.index'))

    holes = round_.holes.all()
    return render_template('rounds/submit.html', round=round_, holes=holes)


@rounds_bp.route('/<int:round_id>/reopen', methods=['POST'])
@login_required
def reopen_round(round_id):
    """Re-open a completed round for editing hole-by-hole data."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    round_.status = 'in_progress'
    db.session.commit()
    return redirect(url_for('rounds.edit_round_meta', round_id=round_id))


@rounds_bp.route('/<int:round_id>/edit-meta', methods=['GET', 'POST'])
@login_required
def edit_round_meta(round_id):
    """Edit date and tee label before stepping through holes."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        date_str = request.form.get('date_played', '').strip()
        tee_label = request.form.get('tee_set', '').strip()
        tee_set_id_str = request.form.get('tee_set_id', '').strip()
        if date_str:
            round_.date_played = datetime.strptime(date_str, '%Y-%m-%d').date()
        if tee_label:
            round_.tee_set = tee_label
        if tee_set_id_str:
            try:
                round_.tee_set_id = int(tee_set_id_str)
            except ValueError:
                pass
        db.session.commit()
        return redirect(url_for('rounds.enter_hole', round_id=round_id, hole_number=1))
    course_external_id = round_.course.external_id if round_.course else None
    return render_template('rounds/edit_meta.html',
                           round=round_,
                           course_external_id=course_external_id,
                           current_tee_id=round_.tee_set_id)


@rounds_bp.route('/<int:round_id>/delete', methods=['POST'])
@login_required
def delete_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    db.session.delete(round_)
    db.session.commit()
    flash('Round deleted.', 'info')
    return redirect(url_for('dashboard.index'))

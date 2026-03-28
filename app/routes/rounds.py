from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.round import Round
from app.models.hole import Hole
from app.models.course import Course
from app.models.tee_set import TeeSet
from app.models.course_hole import CourseHole
from app.services.claude_service import generate_report
from app.services.sendgrid_service import send_report_email, send_personal_best
from app.utils.round_stats import compute_all_stats
from app.utils.personal_bests import check_recent_personal_best
from datetime import datetime, date

rounds_bp = Blueprint('rounds', __name__)

# ---------------------------------------------------------------------------
# USGA World Handicap System — differentials-to-use lookup table
# ---------------------------------------------------------------------------
_WHS_TABLE = {
    3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3,
    12: 4, 13: 4, 14: 4, 15: 5, 16: 5, 17: 6, 18: 6, 19: 7,
}


def _compute_whs_index(rounds):
    """Compute a WHS handicap index from a list of Round objects.

    Returns the computed index (float) or None if fewer than 3 qualifying
    differentials are available.
    """
    # holes_played < 18 covers declared 9-hole rounds AND partial submissions
    nine_hole_diffs = [r.hc_differential for r in rounds if r.holes_played < 18]
    eighteen_diffs  = [r.hc_differential for r in rounds if r.holes_played == 18]

    # Pair 9-hole diffs (most recent first) into 18-hole equivalents; drop odd one out
    paired = [
        nine_hole_diffs[i] + nine_hole_diffs[i + 1]
        for i in range(0, len(nine_hole_diffs) - 1, 2)
    ]

    all_diffs = eighteen_diffs + paired
    count = len(all_diffs)
    if count < 3:
        return None

    n_to_use = _WHS_TABLE.get(count, 8)
    best = sorted(all_diffs)[:n_to_use]
    avg = sum(best) / n_to_use

    if count == 3:
        return round(avg - 2.0, 1)
    elif count == 4:
        return round(avg - 1.0, 1)
    elif count >= 20:
        return round(avg * 0.96, 1)
    else:
        return round(avg, 1)


def _recalculate_handicap(user):
    """Recalculate both handicap indexes for user and commit.

    Computes:
      - user.handicap_index          — all complete rounds (All Rounds HCP)
      - user.official_handicap_index — rounds with counts_for_official_hc=True only

    Uses the same WHS differential logic for both. Requires at least 3
    qualifying 18-hole differentials (9-hole pairs count as one 18-hole diff).
    """
    all_rounds = (
        Round.query
        .filter_by(user_id=user.id, status='complete')
        .filter(Round.hc_differential.isnot(None))
        .order_by(Round.date_played.desc())
        .limit(20)
        .all()
    )

    # All Rounds handicap
    new_all = _compute_whs_index(all_rounds)
    if new_all is not None:
        user.handicap_index = new_all

    # Official handicap — rounds explicitly marked as counting (None treated as True)
    official_rounds = [r for r in all_rounds if r.counts_for_official_hc is not False]
    user.official_handicap_index = _compute_whs_index(official_rounds)

    db.session.commit()
    current_app.logger.info(
        f"[handicap] {user.email} -> all={new_all} "
        f"official={user.official_handicap_index}"
    )


@rounds_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_round():
    """Start a new round — USGA-style course + tee selector."""
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
            flash('Selected tee not found. Please try again.', 'error')
            return redirect(url_for('rounds.new_round'))

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

    if round_.nine_hole_selection == 'back' and round_.holes_played == 9:
        actual_hole_number = hole_number + 9
    else:
        actual_hole_number = hole_number

    existing = Hole.query.filter_by(round_id=round_id, hole_number=actual_hole_number).first()

    course_par     = None
    course_yardage = None
    if round_.tee_set_id:
        ch = CourseHole.query.filter_by(
            tee_set_id=round_.tee_set_id,
            hole_number=actual_hole_number
        ).first()
        if ch:
            course_par     = ch.par
            course_yardage = ch.yardage

    if course_par is None and round_.course and round_.course.par_list:
        course_par = round_.course.par_list[actual_hole_number - 1]

    # Prompt to add hole data for manual courses that have none (shown on hole 1 only)
    show_hole_prompt = False
    course_edit_url  = None
    if hole_number == 1 and round_.course:
        ext_id = round_.course.external_id or ''
        if ext_id.startswith('manual_') and round_.tee_set_id:
            has_data = CourseHole.query.filter_by(tee_set_id=round_.tee_set_id).count() > 0
            if not has_data:
                show_hole_prompt = True
                course_edit_url  = url_for('courses.edit_course',
                                           course_id=round_.course.id)

    if request.method == 'POST':
        data = request.form
        if not existing:
            hole = Hole(round_id=round_id, hole_number=actual_hole_number)
            db.session.add(hole)
        else:
            hole = existing

        hole.par               = int(data.get('par', course_par or 4))
        hole.score             = int(data.get('score', hole.par))
        hole.tee_shot          = data.get('tee_shot') or None
        hole.approach_distance = int(data['approach_distance']) if data.get('approach_distance') else None
        hole.approach_miss     = data.get('approach_miss') or None
        hole.scramble_distance = data.get('scramble_distance') or None
        hole.gir               = not bool(hole.approach_miss or hole.scramble_distance)
        hole.second_shot_distance = int(data['second_shot_distance']) if data.get('second_shot_distance') else None
        hole.putts             = int(data.get('putts', 2))
        hole.first_putt_distance = int(data['first_putt_distance']) if data.get('first_putt_distance') else None
        hole.sand_save_attempt = bool(data.get('sand_save_attempt') == 'true') if data.get('sand_save_attempt') else None
        hole.sand_save_made    = data.get('sand_save_made') == 'true' if data.get('sand_save_made') else None
        hole.penalties         = int(data.get('penalties', 0))
        db.session.commit()

        if hole_number < round_.holes_played:
            return redirect(url_for('rounds.enter_hole', round_id=round_id, hole_number=hole_number + 1))
        else:
            return redirect(url_for('rounds.submit_round', round_id=round_id))

    is_edit     = round_.holes.count() >= round_.holes_played

    # Running totals for all completed holes before this one
    completed_before = Hole.query.filter(
        Hole.round_id == round_id,
        Hole.hole_number < actual_hole_number,
        Hole.score.isnot(None)
    ).all()
    running_gross   = sum(h.score for h in completed_before)
    running_vs_par  = sum((h.score - h.par) for h in completed_before if h.par)
    holes_completed = len(completed_before)

    completed_hole_numbers = {h.hole_number for h in round_.holes.all()}

    return render_template(
        'rounds/hole.html',
        round=round_,
        hole_number=hole_number,
        display_hole_number=actual_hole_number,
        existing=existing,
        course_par=course_par,
        course_yardage=course_yardage,
        total_holes=round_.holes_played,
        running_gross=running_gross,
        running_vs_par=running_vs_par,
        holes_completed=holes_completed,
        is_edit=is_edit,
        completed_hole_numbers=completed_hole_numbers,
        show_hole_prompt=show_hole_prompt,
        course_edit_url=course_edit_url,
    )


@rounds_bp.route('/<int:round_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        current_app.logger.info(f"[submit_round] POST received for round_id={round_id}")
        round_.status       = 'complete'
        round_.completed_at = datetime.utcnow()
        # Stamp actual holes completed so handicap pairing and stats use the real count
        round_.holes_played = round_.holes.count()
        try:
            compute_all_stats(round_)     # totals + SG + algo_version in one pass
            round_.compute_differential()
        except Exception as e:
            current_app.logger.exception(f"[submit_round] compute failed: {e}")
        db.session.commit()
        try:
            _recalculate_handicap(current_user)
        except Exception as e:
            current_app.logger.exception(f"[submit_round] Handicap recalc failed: {e}")
        try:
            generate_report(round_)
            send_report_email(round_)
            flash('Your round has been saved and your report is on its way!', 'success')
        except Exception:
            flash('Round saved! Report generation is in the queue.', 'info')

        # Personal best check — runs after the report email so it lands separately
        try:
            prev_rounds = (
                Round.query
                .filter(Round.user_id == current_user.id,
                        Round.status == 'complete',
                        Round.id != round_.id)
                .order_by(Round.date_played.desc())
                .all()
            )
            pb_banner = check_recent_personal_best(round_, prev_rounds)
            if pb_banner:
                send_personal_best(round_, pb_banner)
        except Exception:
            current_app.logger.warning('[submit_round] PB email failed for round %s', round_.id)

        return redirect(url_for('dashboard.index'))

    holes = round_.holes.all()
    return render_template('rounds/submit.html', round=round_, holes=holes)


@rounds_bp.route('/<int:round_id>/reopen', methods=['POST'])
@login_required
def reopen_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    round_.status = 'in_progress'
    db.session.commit()
    return redirect(url_for('rounds.edit_round_meta', round_id=round_id))


@rounds_bp.route('/<int:round_id>/edit-meta', methods=['GET', 'POST'])
@login_required
def edit_round_meta(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        date_str       = request.form.get('date_played', '').strip()
        tee_label      = request.form.get('tee_set', '').strip()
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
    return render_template(
        'rounds/edit_meta.html',
        round=round_,
        course_external_id=course_external_id,
        current_tee_id=round_.tee_set_id
    )


@rounds_bp.route('/<int:round_id>/toggle-official-hc', methods=['POST'])
@login_required
def toggle_official_hc(round_id):
    """Toggle whether a round counts towards the Official Handicap."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    # Treat None (pre-migration rows) as True before toggling
    current_state = round_.counts_for_official_hc
    if current_state is None:
        current_state = True
    round_.counts_for_official_hc = not current_state
    db.session.commit()
    _recalculate_handicap(current_user)
    return jsonify({
        'counts': round_.counts_for_official_hc,
        'official_hcp': current_user.official_handicap_index,
        'all_hcp': current_user.handicap_index,
    })


@rounds_bp.route('/<int:round_id>/delete', methods=['POST'])
@login_required
def delete_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    db.session.delete(round_)
    db.session.commit()
    flash('Round deleted.', 'info')
    return redirect(url_for('dashboard.index'))

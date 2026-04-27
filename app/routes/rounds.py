from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.utils.access import is_pro, subscription_required
from app import db
from app.models.round import Round
from app.models.hole import Hole
from app.models.course import Course
from app.models.tee_set import TeeSet
from app.models.course_hole import CourseHole
from app.services.claude_service import generate_report
from app.utils.round_stats import build_course_hole_map
from app.services.sendgrid_service import send_report_email, send_personal_best
from app.utils.round_stats import compute_all_stats
from app.utils.personal_bests import check_recent_personal_best
from app.utils.access import is_pro
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
        starting_hole = int(request.form.get('starting_hole', 1) or 1)
        starting_hole = max(1, min(18, starting_hole))
        is_partial    = (starting_hole != 1)
        holes_played  = 9 if starting_hole >= 10 else 18

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
            starting_hole=starting_hole,
            is_partial=is_partial,
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

    # Map sequential entry counter (1..holes_played) to actual course hole (1..18).
    # Wraps after 18: e.g. starting_hole=15, hole_number=5 → actual=(14+4)%18+1=1
    starting = round_.starting_hole or 1
    actual_hole_number = ((starting - 1 + hole_number - 1) % 18) + 1

    existing = Hole.query.filter_by(round_id=round_id, hole_number=actual_hole_number).first()

    course_par     = None
    course_yardage = None
    course_hole_map = build_course_hole_map(round_)
    ch = course_hole_map.get(actual_hole_number)
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
        approach_miss = data.get('approach_miss') or None
        if approach_miss:
            # Server-side enforcement: Left/Right and Long/Short are mutually exclusive.
            vals = [v.strip() for v in approach_miss.split(',') if v.strip()]
            if 'left' in vals and 'right' in vals:
                vals = [v for v in vals if v != 'right']
            if 'long' in vals and 'short' in vals:
                vals = [v for v in vals if v != 'short']
            approach_miss = ','.join(vals) or None
        hole.approach_miss     = approach_miss
        hole.lie_type          = data.get('lie_type') or None
        hole.scramble_distance = data.get('scramble_distance') or None
        hole.gir               = not bool(hole.approach_miss or hole.scramble_distance)
        hole.second_shot_distance = int(data['second_shot_distance']) if data.get('second_shot_distance') else None
        hole.putts             = int(data.get('putts', 2))
        hole.first_putt_distance = int(data['first_putt_distance']) if data.get('first_putt_distance') else None
        hole.last_putt_gimme   = data.get('last_putt_gimme') == 'true'
        hole.gimme_distance    = int(data['gimme_distance']) if data.get('gimme_distance') else None
        hole.sand_save_attempt = bool(data.get('sand_save_attempt') == 'true') if data.get('sand_save_attempt') else None
        hole.sand_save_made    = data.get('sand_save_made') == 'true' if data.get('sand_save_made') else None
        hole.penalties         = int(data.get('penalties', 0))
        hole.shots_json = data.get('shots_json') or None
        if data.get('atg_strokes'):
            hole.atg_strokes = int(data.get('atg_strokes', 1))
        db.session.commit()

        if hole_number < round_.holes_played:
            return redirect(url_for('rounds.enter_hole', round_id=round_id, hole_number=hole_number + 1))
        else:
            return redirect(url_for('rounds.submit_round', round_id=round_id))

    is_edit     = round_.holes.count() >= round_.holes_played

    # Running totals for all completed holes (excluding current).
    # Using != rather than < so wrap-around rounds count previously played holes correctly.
    completed_before = Hole.query.filter(
        Hole.round_id == round_id,
        Hole.hole_number != actual_hole_number,
        Hole.score.isnot(None)
    ).all()
    running_gross   = sum(h.score for h in completed_before)
    running_vs_par  = sum((h.score - h.par) for h in completed_before if h.par)
    holes_completed = len(completed_before)

    completed_hole_numbers = {h.hole_number for h in round_.holes.all()}

    import json as _json

    def _reconstruct_shots(h):
        """Build a shots_json-style list from legacy hole fields."""
        shots = []
        if h.tee_shot and h.par in (4, 5):
            parts = (h.tee_shot or '').split(',')
            direction = mod = None
            if len(parts) == 1:
                if parts[0] == 'fairway': direction = 'fairway'
                elif parts[0] in ('left', 'right'): direction = parts[0]
                elif parts[0] in ('bunker', 'penalty'): mod = parts[0]
            elif len(parts) == 2:
                mod, direction = parts[0], parts[1]
            shots.append({'type': 'ott', 'direction': direction, 'mod': mod})
        if h.approach_distance:
            s = {'type': 'app', 'distance': h.approach_distance}
            if h.approach_miss: s['miss'] = h.approach_miss
            if h.lie_type: s['lie'] = h.lie_type.split(',')[0]
            shots.append(s)
        if h.approach_miss:  # missed green → had ATG
            from app.utils.strokes_gained import _parse_yards
            sdist = _parse_yards(h.scramble_distance) if h.scramble_distance else None
            atg_lie = 'bunker' if 'bunker' in (h.lie_type or '') else 'rough'
            shots.append({'type': 'atg', 'distance': sdist, 'lie': atg_lie})
        total_putts = h.putts or 2
        is_gimme = getattr(h, 'last_putt_gimme', False)
        for i in range(total_putts):
            is_last = (i == total_putts - 1)
            if is_last and is_gimme:
                s = {'type': 'gimme'}
                if h.gimme_distance: s['gimme_distance'] = h.gimme_distance
                shots.append(s)
            else:
                s = {'type': 'putt'}
                if i == 0 and h.first_putt_distance: s['putt_distance'] = h.first_putt_distance
                shots.append(s)
        return shots

    if existing:
        if existing.shots_json:
            existing_shots_json = existing.shots_json
        else:
            existing_shots_json = _json.dumps(_reconstruct_shots(existing))
    else:
        existing_shots_json = '[]'

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
        existing_shots_json=existing_shots_json,
    )


@rounds_bp.route('/<int:round_id>/hole/<int:hole_number>/autosave', methods=['POST'])
@login_required
def autosave_hole(round_id, hole_number):
    """AJAX save for hole data — identical logic to enter_hole POST but returns JSON."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    starting = round_.starting_hole or 1
    actual_hole_number = ((starting - 1 + hole_number - 1) % 18) + 1

    existing = Hole.query.filter_by(round_id=round_id, hole_number=actual_hole_number).first()
    data = request.form

    if not existing:
        shots_raw = data.get('shots_json') or ''
        has_shots = shots_raw not in ('', '[]', 'null')
        par_val = int(data.get('par', 4))
        score_raw = data.get('score')
        score_differs = score_raw and int(score_raw) != par_val and int(score_raw) != 0
        has_field = any(data.get(f) for f in (
            'tee_shot', 'approach_distance', 'scramble_distance', 'putts'
        ))
        if not (has_shots or score_differs or has_field):
            return jsonify({'ok': True, 'skipped': True})
        hole = Hole(round_id=round_id, hole_number=actual_hole_number)
        db.session.add(hole)
    else:
        hole = existing

    hole.par               = int(data.get('par', 4))
    hole.score             = int(data.get('score', hole.par))
    hole.tee_shot          = data.get('tee_shot') or None
    hole.approach_distance = int(data['approach_distance']) if data.get('approach_distance') else None
    approach_miss = data.get('approach_miss') or None
    if approach_miss:
        vals = [v.strip() for v in approach_miss.split(',') if v.strip()]
        if 'left' in vals and 'right' in vals:
            vals = [v for v in vals if v != 'right']
        if 'long' in vals and 'short' in vals:
            vals = [v for v in vals if v != 'short']
        approach_miss = ','.join(vals) or None
    hole.approach_miss     = approach_miss
    hole.lie_type          = data.get('lie_type') or None
    hole.scramble_distance = data.get('scramble_distance') or None
    hole.gir               = not bool(hole.approach_miss or hole.scramble_distance)
    hole.second_shot_distance = int(data['second_shot_distance']) if data.get('second_shot_distance') else None
    hole.putts             = int(data.get('putts', 2))
    hole.first_putt_distance = int(data['first_putt_distance']) if data.get('first_putt_distance') else None
    hole.last_putt_gimme   = data.get('last_putt_gimme') == 'true'
    hole.gimme_distance    = int(data['gimme_distance']) if data.get('gimme_distance') else None
    hole.sand_save_attempt = bool(data.get('sand_save_attempt') == 'true') if data.get('sand_save_attempt') else None
    hole.sand_save_made    = data.get('sand_save_made') == 'true' if data.get('sand_save_made') else None
    hole.penalties         = int(data.get('penalties', 0))
    hole.shots_json = data.get('shots_json') or None
    if data.get('atg_strokes'):
        hole.atg_strokes = int(data.get('atg_strokes', 1))
    db.session.commit()

    return jsonify({'ok': True})


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
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.exception(f"[submit_round] DB commit failed: {e}")
            db.session.rollback()
            flash('There was a problem saving your round. Please try again.', 'error')
            return redirect(url_for('dashboard.index'))
        try:
            _recalculate_handicap(current_user)
        except Exception as e:
            current_app.logger.exception(f"[submit_round] Handicap recalc failed: {e}")
        try:
            report = generate_report(round_)
            # All users receive an email — pro users get the full report, free
            # users get a trimmed version that teases paid features.
            # Don't re-send if this round was already emailed (re-edit path).
            if not (report and report.emailed_at):
                send_report_email(round_)
            flash('Your round has been saved and your report is on its way!', 'success')
        except Exception as e:
            current_app.logger.exception(f"[submit_round] Report/email failed: {e}")
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
            if pb_banner and is_pro(current_user):
                send_personal_best(round_, pb_banner)
        except Exception:
            current_app.logger.warning('[submit_round] PB email failed for round %s', round_.id)

        return redirect(url_for('reports.view_report', round_id=round_.id))

    holes = round_.holes.all()
    return render_template('rounds/submit.html', round=round_, holes=holes)


def _recompute_round(round_):
    """Recompute aggregate stats and invalidate the cached report for a complete round.

    Called after any mid-review edit (hole removal, manual score override) so the
    report reflects the updated hole data on next view rather than serving stale text.
    Only acts when the round is already complete — in-progress rounds have no cached
    report to invalidate and will recompute naturally at submission.
    """
    if round_.status != 'complete':
        return
    try:
        compute_all_stats(round_)
        round_.compute_differential()
    except Exception as e:
        current_app.logger.exception(f"[_recompute_round] stats failed for round {round_.id}: {e}")
    report = round_.report
    if report:
        report.narrative_text    = None
        report.summary_text      = None
        report.narrative_version = None
    db.session.commit()
    try:
        _recalculate_handicap(current_user)
    except Exception as e:
        current_app.logger.exception(f"[_recompute_round] handicap recalc failed: {e}")


@rounds_bp.route('/<int:round_id>/hole/<int:hole_number>/remove', methods=['POST'])
@login_required
def remove_hole(round_id, hole_number):
    """Delete a single hole from a round (called from the review page)."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    hole = Hole.query.filter_by(round_id=round_id, hole_number=hole_number).first_or_404()
    db.session.delete(hole)
    db.session.commit()
    _recompute_round(round_)
    return jsonify({'ok': True})


@rounds_bp.route('/<int:round_id>/hole/<int:hole_number>/set-score', methods=['POST'])
@login_required
def set_hole_score(round_id, hole_number):
    """Manually set the gross score for a hole from the review page."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    hole = Hole.query.filter_by(round_id=round_id, hole_number=hole_number).first_or_404()
    try:
        score = int(request.form.get('score', 0))
        if score < 1 or score > 20:
            return jsonify({'ok': False, 'error': 'Invalid score'}), 400
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid score'}), 400
    hole.score = score
    db.session.commit()
    _recompute_round(round_)
    return jsonify({'ok': True, 'score': hole.score})


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
    try:
        _recalculate_handicap(current_user)
    except Exception as e:
        current_app.logger.exception(f"[delete_round] Handicap recalc failed: {e}")
    flash('Round deleted.', 'info')
    return redirect(url_for('dashboard.index'))

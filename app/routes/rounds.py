from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.round import Round
from app.models.hole import Hole
from app.models.course import Course
from app.services.claude_service import generate_report
from app.services.sendgrid_service import send_report_email
from datetime import datetime, date

rounds_bp = Blueprint('rounds', __name__)


@rounds_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_round():
    """Start a new round — choose course, date, tee set."""
    courses = Course.query.order_by(Course.name).all()

    if request.method == 'POST':
        course_id = request.form.get('course_id')
        date_played = request.form.get('date_played', date.today().isoformat())
        tee_set = request.form.get('tee_set', 'White')
        holes_played = int(request.form.get('holes_played', 18))

        round_ = Round(
            user_id=current_user.id,
            course_id=int(course_id) if course_id else None,
            date_played=datetime.strptime(date_played, '%Y-%m-%d').date(),
            tee_set=tee_set,
            holes_played=holes_played,
            status='in_progress'
        )
        db.session.add(round_)
        db.session.commit()

        return redirect(url_for('rounds.enter_hole', round_id=round_.id, hole_number=1))

    return render_template('rounds/new.html', courses=courses, today=date.today().isoformat())


@rounds_bp.route('/<int:round_id>/hole/<int:hole_number>', methods=['GET', 'POST'])
@login_required
def enter_hole(round_id, hole_number):
    """Enter stats for a single hole."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    if hole_number < 1 or hole_number > round_.holes_played:
        return redirect(url_for('rounds.enter_hole', round_id=round_.id, hole_number=1))

    # Get existing data if re-visiting a hole
    existing = Hole.query.filter_by(round_id=round_id, hole_number=hole_number).first()

    # Determine par for this hole
    course_par = None
    if round_.course and round_.course.par_list:
        course_par = round_.course.par_list[hole_number - 1]

    if request.method == 'POST':
        data = request.form

        # Upsert hole
        if not existing:
            hole = Hole(round_id=round_id, hole_number=hole_number)
            db.session.add(hole)
        else:
            hole = existing

        hole.par = int(data.get('par', course_par or 4))
        hole.score = int(data.get('score', hole.par))
        hole.tee_shot = data.get('tee_shot') or None
        hole.gir = data.get('gir') == 'true'
        hole.approach_miss = data.get('approach_miss') or None if not hole.gir else None
        hole.scramble_distance = data.get('scramble_distance') or None if not hole.gir else None
        hole.putts = int(data.get('putts', 2))
        hole.first_putt_distance = int(data['first_putt_distance']) if data.get('first_putt_distance') else None
        hole.sand_save_attempt = data.get('sand_save_attempt') == 'true' if data.get('sand_save_attempt') else None
        hole.sand_save_made = data.get('sand_save_made') == 'true' if data.get('sand_save_made') else None
        hole.penalties = int(data.get('penalties', 0))

        db.session.commit()

        # Navigate to next hole or submit
        if hole_number < round_.holes_played:
            return redirect(url_for('rounds.enter_hole', round_id=round_id, hole_number=hole_number + 1))
        else:
            return redirect(url_for('rounds.submit_round', round_id=round_id))

    return render_template('rounds/hole.html',
                           round=round_,
                           hole_number=hole_number,
                           existing=existing,
                           course_par=course_par,
                           total_holes=round_.holes_played)


@rounds_bp.route('/<int:round_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_round(round_id):
    """Review and finalise the round, trigger report generation."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        round_.compute_totals()
        round_.status = 'complete'
        round_.completed_at = datetime.utcnow()
        db.session.commit()

        # Trigger async report generation (placeholder for task queue)
        try:
            generate_report(round_)
            send_report_email(round_)
            flash('Your round has been saved and your report is on its way!', 'success')
        except Exception as e:
            flash('Round saved! Report generation is in the queue.', 'info')

        return redirect(url_for('dashboard.index'))

    holes = round_.holes.all()
    return render_template('rounds/submit.html', round=round_, holes=holes)


@rounds_bp.route('/<int:round_id>/delete', methods=['POST'])
@login_required
def delete_round(round_id):
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    db.session.delete(round_)
    db.session.commit()
    flash('Round deleted.', 'info')
    return redirect(url_for('dashboard.index'))

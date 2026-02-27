from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from app.models.report import Report
from app.models.round import Round

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/<int:round_id>')
@login_required
def view_report(round_id):
    """View the generated report for a round."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    report = round_.report

    if not report or not report.html_content:
        abort(404)

    return render_template('reports/view.html', round=round_, report=report)

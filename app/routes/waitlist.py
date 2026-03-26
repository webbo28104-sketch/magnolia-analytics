import random
import string

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.waitlist import WaitingList
from app.models.access_code import AccessCode

waitlist_bp = Blueprint('waitlist', __name__)


def _generate_invite_code() -> str:
    """Generate a single-use GOLF-XXXX-XXXX code."""
    part = lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    while True:
        code = f'GOLF-{part()}-{part()}'
        if not AccessCode.query.filter_by(code=code).first():
            return code


# ---------------------------------------------------------------------------
# Public waiting list
# ---------------------------------------------------------------------------

@waitlist_bp.route('/waitlist', methods=['GET', 'POST'])
def index():
    success = False

    if request.method == 'POST':
        name             = request.form.get('name', '').strip()
        email            = request.form.get('email', '').strip().lower()
        handicap_raw     = request.form.get('handicap', '').strip()
        rounds_raw       = request.form.get('rounds_per_month', '').strip()

        if not name or not email:
            flash('Name and email are required.', 'error')
        elif WaitingList.query.filter_by(email=email).first():
            flash("You're already on the list — we'll be in touch!", 'info')
            success = True
        else:
            handicap = None
            try:
                handicap = float(handicap_raw) if handicap_raw else None
            except ValueError:
                pass

            rounds_per_month = None
            try:
                rounds_per_month = int(rounds_raw) if rounds_raw else None
            except ValueError:
                pass

            entry = WaitingList(
                name             = name,
                email            = email,
                handicap         = handicap,
                rounds_per_month = rounds_per_month,
            )
            db.session.add(entry)
            db.session.commit()
            success = True

    # ── Stats ──────────────────────────────────────────────────────────────
    real_count  = WaitingList.query.count()
    shown_count = real_count * 7 + 312

    # Average handicap — real from DB, skip nulls
    hc_rows = db.session.query(WaitingList.handicap).filter(
        WaitingList.handicap.isnot(None)
    ).all()
    avg_handicap = None
    if hc_rows:
        avg_handicap = round(sum(r[0] for r in hc_rows) / len(hc_rows), 1)

    return render_template(
        'waitlist/index.html',
        success      = success,
        shown_count  = shown_count,
        avg_handicap = avg_handicap,
    )


# ---------------------------------------------------------------------------
# Admin: generate invite code
# ---------------------------------------------------------------------------

@waitlist_bp.route('/admin/generate-invite')
@login_required
def generate_invite():
    code_str = _generate_invite_code()
    code     = AccessCode(code=code_str, is_admin=False)
    db.session.add(code)
    db.session.commit()
    return jsonify({'code': code_str})

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db

profile_bp = Blueprint('profile', __name__)


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

    return render_template('profile/index.html')

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.access_code import AccessCode
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        first_name       = request.form.get('first_name', '').strip()
        last_name        = request.form.get('last_name', '').strip()
        email            = request.form.get('email', '').strip().lower()
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Basic validation
        if not all([first_name, last_name, email, password]):
            flash('All fields are required.', 'error')
            return render_template('auth/register.html')
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/register.html')
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('auth/register.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
            return render_template('auth/register.html')

        # Retrieve the access code stored in session (set by /auth/validate-code)
        code_in_session = session.get('access_code')
        access_code_obj = None
        if code_in_session:
            access_code_obj = AccessCode.query.filter_by(code=code_in_session).first()

        # Create user
        user = User(first_name=first_name, last_name=last_name, email=email)
        user.set_password(password)
        if code_in_session:
            user.invite_code = code_in_session
        db.session.add(user)

        # Mark code as used
        if access_code_obj:
            access_code_obj.mark_used(email)

        db.session.commit()

        # Clear the access session flags
        session.pop('access_granted', None)
        session.pop('access_code', None)

        login_user(user)
        flash(f'Welcome to Magnolia Analytics, {first_name}!', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/register.html')


@auth_bp.route('/validate-code', methods=['POST'])
def validate_code():
    code = request.get_json(force=True).get('code', '').strip().upper()
    if not code:
        return jsonify(ok=False, error='Please enter an invite code.')

    access_code_obj = AccessCode.query.filter_by(code=code).first()
    if not access_code_obj or not access_code_obj.is_available:
        return jsonify(ok=False, error='That code is invalid or has already been used.')

    session['access_granted'] = True
    session['access_code'] = code
    return jsonify(ok=True)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember_me') == 'on'
        user     = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Invalid email or password.', 'error')
    return render_template('auth/login.html')


@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password():
    return render_template('auth/forgot_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

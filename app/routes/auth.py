import secrets

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.access_code import AccessCode
from app.services.sendgrid_service import send_welcome, send_password_reset, send_password_changed
from datetime import datetime, timedelta

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

        # Prefer the code entered in the form; fall back to the session (modal flow)
        form_code    = request.form.get('invite_code', '').strip().upper()
        session_code = (session.get('access_code') or '').strip().upper()
        code_str     = form_code or session_code

        def _form(**kw):
            return render_template('auth/register.html', code_prefill=code_str, **kw)

        # --- Invite code: must be present and still available at submission time ---
        if not code_str:
            flash(
                'Access to Magnolia is currently by invite only. '
                'Join the waitlist at magnoliaanalytics.golf',
                'error',
            )
            return _form()

        access_code_obj = AccessCode.query.filter_by(code=code_str).first()
        if not access_code_obj or not access_code_obj.is_available:
            flash(
                'Access to Magnolia is currently by invite only. '
                'Join the waitlist at magnoliaanalytics.golf',
                'error',
            )
            return _form()

        # --- Basic field validation ---
        if not all([first_name, last_name, email, password]):
            flash('All fields are required.', 'error')
            return _form()
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return _form()
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return _form()
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
            return _form()

        # --- Create user ---
        user = User(first_name=first_name, last_name=last_name, email=email)
        user.set_password(password)
        user.invite_code = code_str

        if current_app.config.get('BETA_MODE'):
            from decimal import Decimal
            user.is_founding_member = True
            user.founding_member_since = datetime.utcnow()
            user.subscription_tier = 'founding_member'
            user.pricing_locked_at = Decimal('9.99')
        else:
            user.subscription_tier = 'free'

        db.session.add(user)

        # Consume the code
        access_code_obj.mark_used(email)

        # Mark the matching waitlist entry as converted
        from app.models.waitlist import WaitingList
        wl_entry = WaitingList.query.filter_by(access_code=code_str).first()
        if wl_entry:
            wl_entry.status = 'converted'

        db.session.commit()

        # Clear session access flags
        session.pop('access_granted', None)
        session.pop('access_code', None)

        login_user(user)

        try:
            send_welcome(user)
        except Exception as exc:
            current_app.logger.error('[register] Welcome email failed for %s: %s', email, exc, exc_info=True)

        flash(f'Welcome to Magnolia Analytics, {first_name}!', 'success')
        return redirect(url_for('dashboard.index'))

    # GET — pre-fill from URL param, fall back to session (modal flow)
    code_prefill = request.args.get('code', '').strip().upper() or (session.get('access_code') or '')
    return render_template('auth/register.html', code_prefill=code_prefill)


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


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()
        if user:
            token  = secrets.token_urlsafe(32)
            user.password_reset_token   = token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            try:
                send_password_reset(user, reset_url)
            except Exception as exc:
                current_app.logger.error('[forgot_password] Reset email failed for %s: %s', email, exc, exc_info=True)
        # Always show the same message — don't reveal whether email exists
        flash("If that email is registered, a reset link is on its way. Check your inbox.", 'success')
        return redirect(url_for('auth.forgot_password'))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(password_reset_token=token).first()
    now  = datetime.utcnow()

    if not user or not user.password_reset_expires or user.password_reset_expires < now:
        flash('That reset link has expired or is invalid. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        else:
            user.set_password(password)
            user.password_reset_token   = None
            user.password_reset_expires = None
            db.session.commit()
            try:
                send_password_changed(user)
            except Exception as exc:
                current_app.logger.error('[reset_password] Confirmation email failed for %s: %s', user.email, exc, exc_info=True)
            flash('Your password has been reset. Please sign in.', 'success')
            return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

import secrets

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.services.sendgrid_service import (
    send_welcome, send_password_reset, send_password_changed,
    send_email_confirmation, send_admin_new_user_notification,
)
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

        def _form(**kw):
            return render_template('auth/register.html', **kw)

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

        if current_app.config.get('BETA_MODE'):
            from decimal import Decimal
            user.is_founding_member = True
            user.founding_member_since = datetime.utcnow()
            user.subscription_tier = 'founding_member'
            user.pricing_locked_at = Decimal('9.99')
        else:
            user.subscription_tier = 'free'

        # Generate email confirmation token
        user.email_confirmed     = False
        user.email_confirm_token = secrets.token_urlsafe(32)

        db.session.add(user)
        db.session.commit()

        confirm_url = url_for('auth.confirm_email', token=user.email_confirm_token, _external=True)
        try:
            send_email_confirmation(user, confirm_url)
        except Exception as exc:
            current_app.logger.error('[register] Confirmation email failed for %s: %s', email, exc, exc_info=True)

        flash(
            f"We've sent a confirmation link to {email}. "
            "Click the link in the email to activate your account.",
            'success',
        )
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/confirm-email/<token>')
def confirm_email(token):
    user = User.query.filter_by(email_confirm_token=token).first()
    if not user:
        flash('That confirmation link is invalid or has already been used.', 'error')
        return redirect(url_for('auth.login'))

    user.email_confirmed     = True
    user.email_confirm_token = None
    db.session.commit()

    login_user(user)

    try:
        send_welcome(user)
    except Exception as exc:
        current_app.logger.error('[confirm_email] Welcome email failed for %s: %s', user.email, exc, exc_info=True)

    try:
        send_admin_new_user_notification(user)
    except Exception as exc:
        current_app.logger.error('[confirm_email] Admin notification failed for %s: %s', user.email, exc, exc_info=True)

    flash(f'Email confirmed! Welcome to Magnolia Analytics, {user.first_name}.', 'success')
    return redirect(url_for('dashboard.index'))


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
            if not user.email_confirmed:
                flash(
                    'Please confirm your email address before signing in. '
                    'Check your inbox for the confirmation link.',
                    'warning',
                )
                return render_template('auth/login.html')
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

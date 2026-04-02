"""
Admin dashboard blueprint.
All routes require is_staff=True on the current user.

Diagnostic routes (/test-email, /db-users) are preserved at the bottom
and can be removed once email flows are fully confirmed.
"""
import os
import traceback
from functools import wraps
from types import SimpleNamespace
from datetime import datetime

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, jsonify, request, current_app,
)
from flask_login import current_user, login_required

from app import db

admin_bp = Blueprint('admin', __name__)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_staff:
            flash('Access denied.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Dashboard views
# ---------------------------------------------------------------------------
@admin_bp.route('/')
@staff_required
def index():
    return redirect(url_for('admin.waitlist'))


@admin_bp.route('/waitlist')
@staff_required
def waitlist():
    return render_template('admin/waitlist.html', active_tab='waitlist')


@admin_bp.route('/users')
@staff_required
def users():
    return render_template('admin/users.html', active_tab='users')


@admin_bp.route('/rounds')
@staff_required
def rounds():
    return render_template('admin/rounds.html', active_tab='rounds')


@admin_bp.route('/founding-members')
@staff_required
def founding_members():
    return render_template('admin/founding_members.html', active_tab='founding_members')


@admin_bp.route('/kpis')
@staff_required
def kpis():
    return render_template('admin/kpis.html', active_tab='kpis')


# ---------------------------------------------------------------------------
# Diagnostic: SendGrid + template checks  (remove once email confirmed)
# ---------------------------------------------------------------------------
def _try_render(template, **ctx):
    try:
        render_template(template, **ctx)
        return 'ok'
    except Exception as exc:
        return str(exc)


@admin_bp.route('/test-email')
@staff_required
def test_email():
    api_key    = os.environ.get('SENDGRID_API_KEY', '').strip()
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', '').strip() or 'team@magnoliaanalytics.golf'
    to_email   = request.args.get('to', 'team@magnoliaanalytics.golf').strip()
    trigger_reset = request.args.get('reset', '0') == '1'

    result = {
        'env': {
            'api_key_present':  bool(api_key),
            'api_key_prefix':   (api_key[:8] + '…') if len(api_key) > 8 else '(empty)',
            'from_email':       from_email,
        },
        'direct_sendgrid': {
            'to': to_email,
            'called': False,
            'status_code': None,
            'success': False,
            'error': None,
        },
        'template_renders': {},
        'db_user_lookup': {
            'email': to_email,
            'found': False,
            'note': None,
        },
        'reset_email_send': None,
    }

    if not api_key:
        result['direct_sendgrid']['error'] = (
            'SENDGRID_API_KEY is not set or empty — check Railway → Variables.'
        )
    else:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            message = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject='[TEST] Magnolia Analytics — SendGrid diagnostic',
                html_content=(
                    '<p>Direct SendGrid test from <code>/admin/test-email</code>.</p>'
                    '<p>If you received this, the API key and sender domain are working.</p>'
                ),
            )
            result['direct_sendgrid']['called'] = True
            response = SendGridAPIClient(api_key).send(message)
            result['direct_sendgrid']['status_code'] = response.status_code
            result['direct_sendgrid']['success']     = response.status_code in (200, 202)
        except Exception as exc:
            result['direct_sendgrid']['error']     = str(exc)
            result['direct_sendgrid']['traceback'] = traceback.format_exc()

    mock_user  = SimpleNamespace(first_name='Test', last_name='User', email=to_email)
    mock_round = SimpleNamespace(
        id=1,
        golfer=mock_user,
        course=SimpleNamespace(name='Test Course'),
        date_played=datetime.utcnow(),
        counts_for_official_hc=True,
        total_score=72,
        fairways_available=14,
        fairways_hit=8,
        holes_played=18,
        gir_count=9,
        total_putts=32,
        sg_off_tee=0.5,
        sg_approach=0.2,
        sg_atg=-0.1,
        sg_putting=0.3,
        sg_total=0.9,
        report=None,
        score_vs_par=lambda: -2,
        holes=SimpleNamespace(all=lambda: []),
    )

    result['template_renders'] = {
        'password_reset': _try_render(
            'email/password_reset.html',
            first_name='Test',
            reset_url='https://example.com/auth/reset-password/testtoken',
        ),
        'welcome': _try_render(
            'email/welcome.html',
            first_name='Test',
            new_round_url='https://example.com/rounds/new',
        ),
        'waitlist_confirm': _try_render(
            'email/waitlist_confirm.html',
            name='Test',
            position=42,
        ),
        'invite_code': _try_render(
            'email/invite_code.html',
            first_name='Test',
            code='GOLF-TEST-1234',
            register_url='https://example.com/',
        ),
        'password_changed': _try_render(
            'email/password_changed.html',
            first_name='Test',
            changed_at=datetime.utcnow().strftime('%d %B %Y at %H:%M UTC'),
        ),
        'admin_waitlist': _try_render(
            'email/admin_waitlist.html',
            entry=SimpleNamespace(
                name='Test User',
                email=to_email,
                handicap=12.4,
                rounds_per_month=4,
            ),
            position=319,
            real_count=1,
        ),
    }

    try:
        from app.models.user import User
        user = User.query.filter_by(email=to_email.lower()).first()
        if user:
            result['db_user_lookup']['found'] = True
            result['db_user_lookup']['note']  = (
                f'User found: first_name={user.first_name!r}. '
                'forgot-password WILL attempt to send for this email.'
            )
        else:
            result['db_user_lookup']['found'] = False
            count = User.query.count()
            result['db_user_lookup']['total_users_in_db'] = count
            result['db_user_lookup']['note'] = (
                'No user with this email in the database. '
                f'Total users in DB: {count}.'
            )
            if count > 0:
                users = User.query.limit(5).all()
                result['db_user_lookup']['sample_emails'] = [
                    u.email[:3] + '***@' + u.email.split('@')[-1]
                    for u in users
                ]
    except Exception as exc:
        result['db_user_lookup']['error'] = str(exc)

    if trigger_reset:
        try:
            from app.models.user import User
            user = User.query.filter_by(email=to_email.lower()).first()
            if not user:
                result['reset_email_send'] = {
                    'attempted': False,
                    'error': f'No user found for {to_email} — cannot send reset email.',
                }
            else:
                from app.services.sendgrid_service import send_password_reset
                reset_url = 'https://magnoliaanalytics.golf/auth/reset-password/diagnostic-test-token'
                success = send_password_reset(user, reset_url)
                result['reset_email_send'] = {
                    'attempted': True,
                    'success':   success,
                    'to':        user.email,
                }
        except Exception as exc:
            result['reset_email_send'] = {
                'attempted': True,
                'error':     str(exc),
                'traceback': traceback.format_exc(),
            }

    return jsonify(result), 200


@admin_bp.route('/db-users')
@staff_required
def db_users():
    try:
        from app.models.user import User
        users = User.query.order_by(User.id).all()
        return jsonify({
            'count': len(users),
            'users': [
                {
                    'id':         u.id,
                    'email':      u.email,
                    'first_name': u.first_name,
                    'created':    u.created_at.isoformat() if u.created_at else None,
                    'is_staff':   u.is_staff,
                }
                for u in users
            ],
        }), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'traceback': traceback.format_exc()}), 200

"""
Temporary admin diagnostics blueprint.
REMOVE after all email flows are confirmed working.
"""
import os
import traceback
from types import SimpleNamespace
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app, render_template
from app import db

admin_bp = Blueprint('admin', __name__)


# ---------------------------------------------------------------------------
# Helper: try to render a template and return ok/error string
# ---------------------------------------------------------------------------
def _try_render(template, **ctx):
    try:
        render_template(template, **ctx)
        return 'ok'
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# /admin/test-email
# Comprehensive SendGrid + template diagnostic.
# Optional query-param: ?to=someone@email.com  — overrides the default to_email
# Optional query-param: ?reset=1              — also trigger a real forgot-password
#                                               email for an existing user whose
#                                               email matches `to` (no DB write).
# ---------------------------------------------------------------------------
@admin_bp.route('/admin/test-email')
def test_email():
    """
    Hit this in a browser to diagnose email sending end-to-end.
    Returns JSON. TEMPORARY — remove once all email flows are confirmed working.
    """
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

    # ------------------------------------------------------------------
    # 1. Direct SendGrid call (proves API key + from_email work)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2. Template render checks (catches Jinja2 errors for every email type)
    # ------------------------------------------------------------------
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
    }

    # ------------------------------------------------------------------
    # 3. DB user lookup — confirms whether forgot-password would find this user
    # ------------------------------------------------------------------
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
            result['db_user_lookup']['note']  = (
                'No user with this email in the database. '
                'forgot-password silently skips sending — this is why 0 SendGrid requests. '
                'Register on the production site first, or pass a different ?to= email.'
            )
            # Also report total user count so we know what emails DO exist
            count = User.query.count()
            result['db_user_lookup']['total_users_in_db'] = count
            if count > 0:
                # Show first few emails (masked) so we know what to test with
                users = User.query.limit(5).all()
                result['db_user_lookup']['sample_emails'] = [
                    u.email[:3] + '***@' + u.email.split('@')[-1]
                    for u in users
                ]
    except Exception as exc:
        result['db_user_lookup']['error'] = str(exc)

    # ------------------------------------------------------------------
    # 4. Optional: trigger a real password-reset email for the looked-up user
    #    GET /admin/test-email?to=real@email.com&reset=1
    # ------------------------------------------------------------------
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
                reset_url = f'https://magnoliaanalytics.golf/auth/reset-password/diagnostic-test-token'
                success = send_password_reset(user, reset_url)
                result['reset_email_send'] = {
                    'attempted': True,
                    'success':   success,
                    'to':        user.email,
                    'note': (
                        'Called send_password_reset() directly. '
                        'Check SendGrid dashboard for a new request, '
                        'and check the inbox for the email.'
                    ),
                }
        except Exception as exc:
            result['reset_email_send'] = {
                'attempted': True,
                'error':     str(exc),
                'traceback': traceback.format_exc(),
            }

    return jsonify(result), 200


# ---------------------------------------------------------------------------
# /admin/db-users
# List all user emails in the DB (masked) so we know what's registered.
# ---------------------------------------------------------------------------
@admin_bp.route('/admin/db-users')
def db_users():
    """Temporary: show registered users so we know what email to test forgot-password with."""
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
                    'created':    str(u.id),  # no created_at field, use id as proxy
                }
                for u in users
            ],
        }), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'traceback': traceback.format_exc()}), 200

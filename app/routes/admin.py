"""
Admin dashboard blueprint.
All routes require is_staff=True on the current user.
"""
import os
import random
import string
import traceback
from datetime import datetime, timedelta
from functools import wraps
from types import SimpleNamespace

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, jsonify, request, current_app,
)
from flask_login import current_user

from app import db

admin_bp = Blueprint('admin', __name__)

INVITE_CAP_PER_WEEK = 50


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
# Helpers
# ---------------------------------------------------------------------------
def _generate_invite_code() -> str:
    """Generate a unique single-use GOLF-XXXX-XXXX code."""
    from app.models.access_code import AccessCode
    part = lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    while True:
        code = f'GOLF-{part()}-{part()}'
        if not AccessCode.query.filter_by(code=code).first():
            return code


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
    from app.models.waitlist import WaitingList
    from app.models.user import User

    q             = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    page          = request.args.get('page', 1, type=int)
    per_page      = 50

    # Registered emails (for 'converted' detection)
    registered_emails = {
        row[0] for row in db.session.query(User.email).all()
    }

    # Stats
    total           = WaitingList.query.count()
    pending_count   = WaitingList.query.filter_by(status='pending').count()
    invited_count   = WaitingList.query.filter_by(status='invited').count()
    converted_count = (
        WaitingList.query
        .filter(WaitingList.email.in_(registered_emails))
        .count()
    ) if registered_emails else 0

    week_ago           = datetime.utcnow() - timedelta(days=7)
    invites_this_week  = (
        WaitingList.query
        .filter(WaitingList.invited_at >= week_ago)
        .count()
    )

    # Filtered query
    query = WaitingList.query
    if q:
        query = query.filter(
            db.or_(
                WaitingList.name.ilike(f'%{q}%'),
                WaitingList.email.ilike(f'%{q}%'),
            )
        )
    if status_filter == 'pending':
        query = query.filter(
            WaitingList.status == 'pending',
            ~WaitingList.email.in_(registered_emails) if registered_emails else db.true(),
        )
    elif status_filter == 'invited':
        query = query.filter(WaitingList.status == 'invited')
    elif status_filter == 'converted':
        if registered_emails:
            query = query.filter(WaitingList.email.in_(registered_emails))
        else:
            query = query.filter(db.false())

    query      = query.order_by(WaitingList.signed_up_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'admin/waitlist.html',
        active_tab        = 'waitlist',
        entries           = pagination.items,
        pagination        = pagination,
        registered_emails = registered_emails,
        q                 = q,
        status_filter     = status_filter,
        total             = total,
        pending_count     = pending_count,
        invited_count     = invited_count,
        converted_count   = converted_count,
        invites_this_week = invites_this_week,
        invite_cap        = INVITE_CAP_PER_WEEK,
    )


@admin_bp.route('/waitlist/send-invite', methods=['POST'])
@staff_required
def send_invite():
    from app.models.waitlist import WaitingList
    from app.models.access_code import AccessCode
    from app.services.sendgrid_service import send_invite_code

    entry_ids = request.form.getlist('entry_ids', type=int)
    if not entry_ids:
        flash('No entries selected.', 'error')
        return redirect(url_for('admin.waitlist'))

    sent    = 0
    skipped = 0
    failed  = 0

    for entry_id in entry_ids:
        entry = WaitingList.query.get(entry_id)
        if not entry:
            continue

        # Don't re-invite already-converted users
        from app.models.user import User
        if User.query.filter_by(email=entry.email).first():
            skipped += 1
            continue

        code_str = _generate_invite_code()
        code     = AccessCode(code=code_str, is_admin=False)
        db.session.add(code)

        entry.status     = 'invited'
        entry.invited_at = datetime.utcnow()
        entry.access_code = code_str

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('[admin.send_invite] DB error for entry %s: %s', entry_id, exc)
            failed += 1
            continue

        first_name = entry.name.split()[0] if entry.name else None
        try:
            send_invite_code(entry.email, code_str, first_name=first_name)
        except Exception as exc:
            current_app.logger.warning('[admin.send_invite] Email failed for %s: %s', entry.email, exc)

        sent += 1

    if sent:
        flash(f'{sent} invite{"s" if sent != 1 else ""} sent.', 'success')
    if skipped:
        flash(f'{skipped} skipped — already registered.', 'info')
    if failed:
        flash(f'{failed} failed — check logs.', 'error')

    return redirect(url_for('admin.waitlist', q=request.args.get('q', ''), status=request.args.get('status', 'all')))


@admin_bp.route('/users')
@staff_required
def users():
    from app.models.user import User
    all_users = User.query.order_by(User.created_at.desc()).all()
    total = len(all_users)
    active_subs = sum(1 for u in all_users if u.subscription_active)
    founding_count = sum(1 for u in all_users if u.is_founding_member)
    return render_template(
        'admin/users.html',
        active_tab='users',
        users=all_users,
        total=total,
        active_subs=active_subs,
        founding_count=founding_count,
    )


@admin_bp.route('/rounds')
@staff_required
def rounds():
    return render_template('admin/rounds.html', active_tab='rounds')


@admin_bp.route('/founding-members')
@staff_required
def founding_members():
    from app.models.user import User
    members = User.query.filter_by(is_founding_member=True).order_by(User.founding_member_since.asc()).all()
    return render_template(
        'admin/founding_members.html',
        active_tab='founding_members',
        members=members,
        count=len(members),
    )


@admin_bp.route('/kpis')
@staff_required
def kpis():
    """Render the KPI metrics panel. All calculations delegated to kpi_service."""
    from app.services.kpi_service import get_all_kpis
    from app.models.admin_setting import AdminSetting

    metrics = get_all_kpis()
    nps            = AdminSetting.get('nps_score', '')
    email_open_rate = AdminSetting.get('email_open_rate', '')

    return render_template(
        'admin/kpis.html',
        active_tab      = 'kpis',
        metrics         = metrics,
        nps             = nps,
        email_open_rate = email_open_rate,
    )


@admin_bp.route('/kpis/settings', methods=['POST'])
@staff_required
def kpi_settings():
    """Persist manually-entered KPI values (NPS, email open rate) to AdminSetting."""
    from app.models.admin_setting import AdminSetting

    nps             = request.form.get('nps_score', '').strip()
    email_open_rate = request.form.get('email_open_rate', '').strip()

    if nps:
        AdminSetting.set('nps_score', nps)
    if email_open_rate:
        AdminSetting.set('email_open_rate', email_open_rate)

    try:
        db.session.commit()
        flash('KPI settings saved.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[admin.kpi_settings] Save failed: %s', exc)
        flash('Failed to save settings — check logs.', 'error')

    return redirect(url_for('admin.kpis'))


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
            'to': to_email, 'called': False,
            'status_code': None, 'success': False, 'error': None,
        },
        'template_renders': {},
        'db_user_lookup': {'email': to_email, 'found': False, 'note': None},
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

    mock_user = SimpleNamespace(first_name='Test', last_name='User', email=to_email)
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
        'waitlist_confirm': _try_render('email/waitlist_confirm.html', name='Test', position=42),
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
            entry=SimpleNamespace(name='Test User', email=to_email, handicap=12.4, rounds_per_month=4),
            position=319,
            real_count=1,
        ),
    }

    try:
        from app.models.user import User
        user = User.query.filter_by(email=to_email.lower()).first()
        if user:
            result['db_user_lookup']['found'] = True
            result['db_user_lookup']['note']  = f'User found: first_name={user.first_name!r}.'
        else:
            count = User.query.count()
            result['db_user_lookup']['total_users_in_db'] = count
            result['db_user_lookup']['note'] = f'No user with this email. Total users: {count}.'
            if count > 0:
                users = User.query.limit(5).all()
                result['db_user_lookup']['sample_emails'] = [
                    u.email[:3] + '***@' + u.email.split('@')[-1] for u in users
                ]
    except Exception as exc:
        result['db_user_lookup']['error'] = str(exc)

    if trigger_reset:
        try:
            from app.models.user import User
            user = User.query.filter_by(email=to_email.lower()).first()
            if not user:
                result['reset_email_send'] = {
                    'attempted': False, 'error': f'No user found for {to_email}.',
                }
            else:
                from app.services.sendgrid_service import send_password_reset
                reset_url = 'https://magnoliaanalytics.golf/auth/reset-password/diagnostic-test-token'
                success = send_password_reset(user, reset_url)
                result['reset_email_send'] = {'attempted': True, 'success': success, 'to': user.email}
        except Exception as exc:
            result['reset_email_send'] = {
                'attempted': True, 'error': str(exc), 'traceback': traceback.format_exc(),
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

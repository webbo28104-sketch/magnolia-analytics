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
    return redirect(url_for('admin.rounds'))


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
    from app.models.round import Round
    from sqlalchemy import func

    q             = request.args.get('q', '').strip()
    page          = request.args.get('page', 1, type=int)
    tier_filter   = request.args.get('tier', 'all')
    status_filter = request.args.get('status', 'all')
    per_page      = 25

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Base query
    query = User.query
    if q:
        query = query.filter(
            db.or_(
                User.email.ilike(f'%{q}%'),
                User.first_name.ilike(f'%{q}%'),
                User.last_name.ilike(f'%{q}%'),
            )
        )

    # Tier filter
    if tier_filter == 'founding':
        query = query.filter(User.subscription_tier == 'founding_member')
    elif tier_filter == 'standard':
        query = query.filter(User.subscription_tier.in_(['premium', 'standard']))
    elif tier_filter == 'pro':
        query = query.filter_by(subscription_active=True)
    elif tier_filter == 'free':
        query = query.filter_by(subscription_active=False)

    # Status filter: active = at least one round in last 30 days
    if status_filter == 'active':
        active_user_ids = db.session.query(Round.user_id).filter(
            Round.status == 'complete',
            Round.date_played >= thirty_days_ago.date(),
        ).distinct()
        query = query.filter(User.id.in_(active_user_ids))
    elif status_filter == 'inactive':
        active_user_ids = db.session.query(Round.user_id).filter(
            Round.status == 'complete',
            Round.date_played >= thirty_days_ago.date(),
        ).distinct()
        query = query.filter(~User.id.in_(active_user_ids))

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Per-user round counts and last active date (bulk query for the current page)
    user_ids = [u.id for u in pagination.items]
    round_stats = {}
    if user_ids:
        rows = (
            db.session.query(
                Round.user_id,
                func.count(Round.id).label('cnt'),
                func.max(Round.date_played).label('last_date'),
            )
            .filter(Round.user_id.in_(user_ids), Round.status == 'complete')
            .group_by(Round.user_id)
            .all()
        )
        for row in rows:
            round_stats[row.user_id] = {'count': row.cnt, 'last_date': row.last_date}

    # Summary stats (always across all users, not filtered)
    total_users    = User.query.count()
    active_subs    = User.query.filter_by(subscription_active=True).count()
    founding_count = User.query.filter_by(is_founding_member=True).count()

    return render_template(
        'admin/users.html',
        active_tab     = 'users',
        pagination     = pagination,
        round_stats    = round_stats,
        q              = q,
        tier_filter    = tier_filter,
        status_filter  = status_filter,
        total_users    = total_users,
        active_subs    = active_subs,
        founding_count = founding_count,
    )


@admin_bp.route('/users/<int:user_id>')
@staff_required
def user_detail(user_id):
    from app.models.user import User
    from app.models.round import Round

    user = User.query.get_or_404(user_id)
    rounds = (
        Round.query
        .filter_by(user_id=user_id, status='complete')
        .order_by(Round.date_played.desc())
        .all()
    )
    return render_template(
        'admin/user_detail.html',
        active_tab = 'users',
        u          = user,
        rounds     = rounds,
    )


@admin_bp.route('/users/<int:user_id>/grant-founding', methods=['POST'])
@staff_required
def grant_founding(user_id):
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    if not user.is_founding_member:
        user.is_founding_member    = True
        user.founding_member_since = datetime.utcnow()
        try:
            db.session.commit()
            current_app.logger.info('[admin] Founding status granted to user_id=%s by %s', user_id, current_user.email)
            flash(f'Founding member status granted to {user.full_name}.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('[admin] grant_founding failed for user_id=%s: %s', user_id, exc)
            flash('Failed to update — check logs.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/revoke-founding', methods=['POST'])
@staff_required
def revoke_founding(user_id):
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    if user.is_founding_member:
        user.is_founding_member    = False
        user.founding_member_since = None
        try:
            db.session.commit()
            current_app.logger.info('[admin] Founding status revoked from user_id=%s by %s', user_id, current_user.email)
            flash(f'Founding member status revoked from {user.full_name}.', 'success')
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('[admin] revoke_founding failed for user_id=%s: %s', user_id, exc)
            flash('Failed to update — check logs.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/set-tier', methods=['POST'])
@staff_required
def set_user_tier(user_id):
    """Manually override a user's subscription tier and active status."""
    from app.models.user import User

    user = User.query.get_or_404(user_id)

    new_active = request.form.get('subscription_active') == '1'
    new_tier   = request.form.get('subscription_tier', 'standard')
    if new_tier not in ('standard', 'premium', 'founding', 'founding_member'):
        new_tier = 'standard'

    user.subscription_active = new_active
    user.subscription_tier   = new_tier

    # Grant founding eligibility when explicitly setting founding tier.
    # Never clear it — is_founding_member is a lifetime eligibility flag;
    # access is controlled solely by subscription_active.
    if new_tier in ('founding_member', 'founding'):
        user.is_founding_member = True

    try:
        db.session.commit()
        status = 'Pro' if new_active else 'Free'
        flash(f'{user.full_name} updated — {status} ({new_tier}).', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[admin.set_user_tier] Failed for user %s: %s', user_id, exc)
        flash('Failed to update user — check logs.', 'error')

    return redirect(url_for('admin.users', q=request.args.get('q', ''), tier=request.args.get('tier', 'all')))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@staff_required
def delete_user(user_id):
    """Permanently delete a user and all their data (rounds, holes, reports)."""
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.users'))
    name = user.full_name
    email = user.email
    try:
        db.session.delete(user)
        db.session.commit()
        current_app.logger.info('[admin] User deleted: %s <%s> by %s', name, email, current_user.email)
        flash(f'Account for {name} ({email}) has been permanently deleted.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[admin] delete_user failed for user_id=%s: %s', user_id, exc)
        flash('Failed to delete account — check logs.', 'error')
    return redirect(url_for('admin.users', q=request.args.get('q', ''), tier=request.args.get('tier', 'all')))


@admin_bp.route('/users/<int:user_id>/toggle-staff', methods=['POST'])
@staff_required
def toggle_staff(user_id):
    """Toggle is_staff on a user. A staff member cannot remove their own staff status."""
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own staff status.', 'error')
        return redirect(url_for('admin.users'))
    user.is_staff = not user.is_staff
    try:
        db.session.commit()
        action = 'granted' if user.is_staff else 'removed'
        flash(f'Staff access {action} for {user.full_name}.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[admin.toggle_staff] Failed for user %s: %s', user_id, exc)
        flash('Failed to update — check logs.', 'error')
    return redirect(url_for('admin.users', q=request.args.get('q', ''), tier=request.args.get('tier', 'all')))


@admin_bp.route('/rounds')
@staff_required
def rounds():
    from app.models.round import Round
    from app.models.user import User
    from sqlalchemy import func
    from collections import defaultdict
    from datetime import date

    now             = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    fourteen_days_ago = now - timedelta(days=14)

    # ── Summary stats ────────────────────────────────────────────────────────
    total_rounds = Round.query.filter_by(status='complete').count()

    rounds_last_30 = Round.query.filter(
        Round.status == 'complete',
        Round.date_played >= thirty_days_ago.date(),
    ).count()

    active_user_count = (
        db.session.query(Round.user_id)
        .filter(Round.status == 'complete', Round.date_played >= thirty_days_ago.date())
        .distinct()
        .count()
    )
    avg_rounds = round(rounds_last_30 / active_user_count, 1) if active_user_count else 0

    # ── Rounds by month (last 12 months) ─────────────────────────────────────
    twelve_ago = now - timedelta(days=366)
    recent_rounds = (
        Round.query
        .filter(Round.status == 'complete', Round.date_played >= twelve_ago.date())
        .with_entities(Round.date_played)
        .all()
    )
    month_counts = defaultdict(int)
    for (dp,) in recent_rounds:
        month_counts[dp.strftime('%Y-%m')] += 1

    months_data = []
    for i in range(11, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        key   = f'{y:04d}-{m:02d}'
        label = date(y, m, 1).strftime('%b %y')
        months_data.append({'key': key, 'label': label, 'count': month_counts[key]})

    max_bar = max((m['count'] for m in months_data), default=1) or 1

    # ── Top 10 users by total rounds ─────────────────────────────────────────
    top_users = (
        db.session.query(User, func.count(Round.id).label('round_count'),
                         func.max(Round.date_played).label('last_date'))
        .join(Round, Round.user_id == User.id)
        .filter(Round.status == 'complete')
        .group_by(User.id)
        .order_by(func.count(Round.id).desc())
        .limit(10)
        .all()
    )

    # ── At-risk cohort ────────────────────────────────────────────────────────
    users_with_rounds = (
        db.session.query(Round.user_id)
        .filter(Round.status == 'complete')
        .distinct()
    )
    at_risk = (
        User.query
        .filter(User.created_at <= fourteen_days_ago)
        .filter(~User.id.in_(users_with_rounds))
        .order_by(User.created_at.asc())
        .all()
    )

    return render_template(
        'admin/rounds.html',
        active_tab        = 'rounds',
        total_rounds      = total_rounds,
        rounds_last_30    = rounds_last_30,
        avg_rounds        = avg_rounds,
        months_data       = months_data,
        max_bar           = max_bar,
        top_users         = top_users,
        at_risk           = at_risk,
        now               = now,
    )


@admin_bp.route('/founding-members')
@staff_required
def founding_members():
    from app.models.user import User
    from decimal import Decimal

    cfg = current_app.config
    pid_fm = cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', '')
    pid_fa = cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL', '')
    pid_sm = cfg.get('STRIPE_PRICE_STANDARD_MONTHLY', '')
    pid_sa = cfg.get('STRIPE_PRICE_STANDARD_ANNUAL', '')

    # All users ordered by founding date
    sort = request.args.get('sort', 'asc')
    members_q = User.query.filter_by(is_founding_member=True)
    if sort == 'desc':
        members_q = members_q.order_by(User.founding_member_since.desc())
    else:
        members_q = members_q.order_by(User.founding_member_since.asc())
    members = members_q.all()

    total_founding  = len(members)
    active_founding = sum(1 for u in members if u.subscription_active)
    churned_founding = sum(
        1 for u in members
        if u.subscription_tier == 'free' or not u.subscription_active
    )

    # Conversion rate: paid founding / all registered users
    total_users = User.query.count()
    conversion_pct = round(active_founding / total_users * 100, 1) if total_users else 0

    # MRR calculation
    active_users = User.query.filter_by(subscription_active=True).all()
    fm_monthly_count = sum(1 for u in active_users if u.stripe_price_id == pid_fm)
    fm_annual_count  = sum(1 for u in active_users if u.stripe_price_id == pid_fa)
    sm_monthly_count = sum(1 for u in active_users if u.stripe_price_id == pid_sm)
    sa_annual_count  = sum(1 for u in active_users if u.stripe_price_id == pid_sa)
    # Catch-all: active founding members not matched by price ID
    if pid_fm or pid_fa:
        fm_other = sum(
            1 for u in active_users
            if u.subscription_tier == 'founding_member'
            and u.stripe_price_id not in (pid_fm, pid_fa)
        )
    else:
        fm_other = sum(1 for u in active_users if u.subscription_tier == 'founding_member')

    founding_mrr = round(
        fm_monthly_count * 9.99
        + fm_annual_count * 89 / 12
        + fm_other * 9.99,
        2,
    )
    standard_mrr = round(
        sm_monthly_count * 12.99
        + sa_annual_count * 109 / 12,
        2,
    )
    total_mrr = round(founding_mrr + standard_mrr, 2)

    founding_pct = round(founding_mrr / total_mrr * 100) if total_mrr else 0
    standard_pct = 100 - founding_pct

    return render_template(
        'admin/founding_members.html',
        active_tab       = 'founding_members',
        members          = members,
        sort             = sort,
        total_founding   = total_founding,
        active_founding  = active_founding,
        churned_founding = churned_founding,
        conversion_pct   = conversion_pct,
        founding_mrr     = founding_mrr,
        standard_mrr     = standard_mrr,
        total_mrr        = total_mrr,
        founding_pct     = founding_pct,
        standard_pct     = standard_pct,
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


@admin_bp.route('/recompute-all-rounds', methods=['GET', 'POST'])
@staff_required
def recompute_all_rounds():
    from app.models.round import Round
    from app.utils.round_stats import compute_all_stats
    from app import db
    rounds = Round.query.filter_by(status='complete').order_by(Round.id).all()
    updated = errors = 0
    log = []
    for round_ in rounds:
        try:
            holes = round_.holes.all()
            if not holes:
                continue
            for hole in holes:
                if hole.score is not None and hole.putts is not None and hole.par is not None:
                    hole.gir = (hole.score - hole.putts) <= (hole.par - 2)
            db.session.flush()
            compute_all_stats(round_)
            updated += 1
            log.append(f'Round {round_.id} ({round_.date_played}) — OK')
        except Exception as exc:
            db.session.rollback()
            errors += 1
            log.append(f'Round {round_.id} — ERROR: {exc}')
    db.session.commit()
    return '<pre>Done. updated={} errors={}\n\n{}</pre>'.format(updated, errors, '\n'.join(log))

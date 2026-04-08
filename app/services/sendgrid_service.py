"""
SendGrid email service — delivers all transactional emails via Jinja2 templates.

Templates live in app/templates/email/.  Each send_* function renders the
appropriate template and calls _send_email.  When SENDGRID_API_KEY is not set,
emails are printed to stdout so local development still exercises the flow.
"""
import os
from datetime import datetime

from flask import current_app, render_template, url_for

from app import db
from app.utils.access import is_pro

ADMIN_EMAIL = 'team@magnoliaanalytics.golf'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Core delivery function.  Uses SendGrid when API key is present."""
    # Strip whitespace — a trailing newline or space in a Railway env var is a
    # common copy-paste mistake that makes the key silently falsy or invalid.
    api_key    = os.environ.get('SENDGRID_API_KEY', '').strip()
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'hello@magnoliaanalytics.golf').strip()

    if api_key:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            message = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content,
            )
            current_app.logger.info('[SendGrid] calling API to=%s subject=%s', to_email, subject)
            response = SendGridAPIClient(api_key).send(message)
            return response.status_code in (200, 202)
        except Exception as exc:
            current_app.logger.error('[SendGrid] send failed to=%s subject=%s: %s', to_email, subject, exc, exc_info=True)
            return False

    # No API key — log and return success so callers don't break in dev
    current_app.logger.info('[SendGrid] PLACEHOLDER  to=%-40s  subject=%s', to_email, subject)
    return True


def _sg_color(val) -> str:
    """Bar colour matching dashboard: green / gold / warm-red."""
    if val is None:
        return '#c9a84c'
    if val >= 0.3:
        return '#2d6a4f'
    if val <= -0.3:
        return '#c0635a'
    return '#c9a84c'


def _sg_bar_pct(val, scale: float = 4.0) -> int:
    """0–100 integer representing abs(val) relative to ±scale."""
    if val is None:
        return 0
    return min(100, int(abs(val) / scale * 100))


def _fmt_sg(val) -> str:
    if val is None:
        return '—'
    return f'+{val:.2f}' if val >= 0 else f'{val:.2f}'


# ---------------------------------------------------------------------------
# 1. Round report
# ---------------------------------------------------------------------------

def send_report_email(round_, force_free: bool = False) -> bool:
    """Send the post-submission round performance report to the golfer.

    Pro users receive the full report (all SG categories + coaching narrative).
    Free users receive a trimmed version showing their free-tier data, with paid
    sections teased to encourage upgrade.  Pass force_free=True to always render
    the free variant regardless of subscription status (used in admin previews).
    """
    user        = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'
    round_type  = 'Casual' if round_.counts_for_official_hc is False else 'Official'

    # Score vs par display string
    svp = round_.score_vs_par()
    if svp is None:
        svp_display = '—'
    elif svp == 0:
        svp_display = 'E'
    elif svp > 0:
        svp_display = f'+{svp}'
    else:
        svp_display = str(svp)

    # Hole-level stats not stored on Round
    holes      = round_.holes.all()
    gir_misses = [h for h in holes if not h.gir]
    scramble_pct = None
    if gir_misses:
        saves = sum(
            1 for h in gir_misses
            if h.score is not None and h.par is not None and h.score - h.par <= 0
        )
        scramble_pct = round(saves / len(gir_misses) * 100)

    fir_pct = None
    if round_.fairways_available:
        fir_pct = round((round_.fairways_hit or 0) / round_.fairways_available * 100)

    gir_pct = None
    if round_.holes_played and round_.gir_count is not None:
        gir_pct = round(round_.gir_count / round_.holes_played * 100)

    putts_per_hole = None
    if round_.total_putts and round_.holes_played:
        putts_per_hole = round(round_.total_putts / round_.holes_played, 1)

    # Strokes Gained bar data
    sg_cats = []
    for label, attr in [
        ('Off the Tee',      'sg_off_tee'),
        ('Approach',         'sg_approach'),
        ('Around the Green', 'sg_atg'),
        ('Putting',          'sg_putting'),
    ]:
        val = getattr(round_, attr, None)
        sg_cats.append({
            'label':   label,
            'value':   val,
            'display': _fmt_sg(val),
            'color':   _sg_color(val),
            'bar_pct': _sg_bar_pct(val, 4.0),
            'positive': val is not None and val >= 0,
        })

    sg_total_color   = _sg_color(round_.sg_total)
    sg_total_bar_pct = _sg_bar_pct(round_.sg_total, 8.0)
    sg_total_display = _fmt_sg(round_.sg_total)
    sg_total_positive = round_.sg_total is not None and round_.sg_total >= 0

    user_is_pro = (not force_free) and is_pro(user)

    # First paragraph of coaching narrative only (if already generated, pro only)
    narrative = None
    if user_is_pro and round_.report and round_.report.narrative_text:
        paras = [p.strip() for p in round_.report.narrative_text.split('\n\n') if p.strip()]
        narrative = paras[0] if paras else round_.report.narrative_text

    report_url   = url_for('reports.view_report', round_id=round_.id, _external=True)
    upgrade_url  = url_for('main.upgrade', _external=True)

    html = render_template(
        'email/round_report.html',
        user               = user,
        user_is_pro        = user_is_pro,
        course_name        = course_name,
        date_played        = round_.date_played.strftime('%d %B %Y'),
        round_type         = round_type,
        total_score        = round_.total_score,
        score_vs_par_display = svp_display,
        fir_pct            = fir_pct,
        gir_pct            = gir_pct,
        putts_per_hole     = putts_per_hole,
        scramble_pct       = scramble_pct,
        sg_cats            = sg_cats,
        sg_total_display   = sg_total_display,
        sg_total_color     = sg_total_color,
        sg_total_bar_pct   = sg_total_bar_pct,
        sg_total_positive  = sg_total_positive,
        narrative          = narrative,
        report_url         = report_url,
        upgrade_url        = upgrade_url,
    )

    subject = f'Your round at {course_name} — {round_.date_played.strftime("%d %b")}'
    success = _send_email(user.email, subject, html)

    if success and round_.report:
        round_.report.emailed_at  = datetime.utcnow()
        round_.report.email_status = 'sent'
        db.session.commit()

    return success


# ---------------------------------------------------------------------------
# 2. Waitlist confirmation
# ---------------------------------------------------------------------------

def send_waitlist_confirm(entry) -> bool:
    """Confirm a new waitlist signup to the applicant."""
    from app.models.waitlist import WaitingList
    real_count = WaitingList.query.count()
    position   = real_count * 7 + 312
    first_name = entry.name.split()[0] if entry.name else 'there'

    html = render_template(
        'email/waitlist_confirm.html',
        name     = first_name,
        position = position,
    )
    return _send_email(entry.email, "You're on the Magnolia Analytics list", html)


# ---------------------------------------------------------------------------
# 3. Invite code delivery
# ---------------------------------------------------------------------------

def send_invite_code(to_email: str, code: str, first_name: str = None) -> bool:
    """Send a GOLF-XXXX-XXXX invite code to a prospective member."""
    register_url = url_for('waitlist.index', _external=True)
    html = render_template(
        'email/invite_code.html',
        first_name   = first_name or 'Golfer',
        code         = code,
        register_url = register_url,
    )
    return _send_email(to_email, "You're in — your Magnolia Analytics access code", html)


# ---------------------------------------------------------------------------
# 4. Welcome after registration
# ---------------------------------------------------------------------------

def send_welcome(user) -> bool:
    """Welcome email sent immediately after a new user registers."""
    new_round_url = url_for('rounds.new_round', _external=True)
    html = render_template(
        'email/welcome.html',
        first_name    = user.first_name,
        new_round_url = new_round_url,
    )
    return _send_email(user.email, f'Welcome to Magnolia Analytics, {user.first_name}', html)


# ---------------------------------------------------------------------------
# 5. Password reset
# ---------------------------------------------------------------------------

def send_password_reset(user, reset_url: str) -> bool:
    """Send a password reset link (1-hour expiry)."""
    html = render_template(
        'email/password_reset.html',
        first_name = user.first_name,
        reset_url  = reset_url,
    )
    current_app.logger.info('Sending password reset email to %s', user.email)
    return _send_email(user.email, 'Reset your Magnolia Analytics password', html)


# ---------------------------------------------------------------------------
# 6. Personal best notification
# ---------------------------------------------------------------------------

def send_personal_best(round_, pb_banner: dict) -> bool:
    """Notify the golfer that they set a personal best in their last round."""
    user        = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'
    report_url  = url_for('reports.view_report', round_id=round_.id, _external=True)

    html = render_template(
        'email/personal_best.html',
        first_name  = user.first_name,
        pb_label    = pb_banner['label'],
        course_name = course_name,
        date_played = round_.date_played.strftime('%d %B %Y'),
        report_url  = report_url,
    )
    return _send_email(user.email, f'Personal best at {course_name}!', html)


# ---------------------------------------------------------------------------
# 7. Password changed confirmation
# ---------------------------------------------------------------------------

def send_password_changed(user) -> bool:
    """Security confirmation sent after a successful password reset."""
    html = render_template(
        'email/password_changed.html',
        first_name = user.first_name,
        changed_at = datetime.utcnow().strftime('%d %B %Y at %H:%M UTC'),
    )
    return _send_email(
        user.email,
        'Your Magnolia Analytics password has been changed',
        html,
    )


# ---------------------------------------------------------------------------
# 8. Subscription welcome (post-Stripe checkout)
# ---------------------------------------------------------------------------

def send_subscription_welcome(user, plan_name: str, plan_price: str, is_founding: bool) -> bool:
    """
    Send a subscription confirmation and getting-started email immediately
    after a successful Stripe Checkout.  Distinct from the registration
    welcome — this one confirms the specific plan and price.
    """
    dashboard_url = url_for('dashboard.index', _external=True)
    install_url   = url_for('main.index', _external=True) + '#install'
    html = render_template(
        'email/subscription_welcome.html',
        first_name    = user.first_name,
        plan_name     = plan_name,
        plan_price    = plan_price,
        is_founding   = is_founding,
        dashboard_url = dashboard_url,
        install_url   = install_url,
    )
    return _send_email(user.email, 'Welcome to Magnolia Analytics \u2726', html)


# ---------------------------------------------------------------------------
# 9. Admin waitlist notification
# ---------------------------------------------------------------------------

def send_admin_waitlist_notification(entry, position: int, real_count: int) -> bool:
    """Notify the Magnolia team of every new waitlist signup."""
    html = render_template(
        'email/admin_waitlist.html',
        entry      = entry,
        position   = position,
        real_count = real_count,
    )
    return _send_email(
        ADMIN_EMAIL,
        f'New waitlist signup: {entry.name}',
        html,
    )

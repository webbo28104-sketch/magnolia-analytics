"""
KPI calculation service for the Magnolia Analytics admin dashboard.

All public functions return a consistent dict:
    {
        'value':     raw numeric value (or None),
        'display':   formatted string for the card,
        'prior':     raw numeric value for prior 30d window (or None),
        'delta_str': e.g. '+12.5%' or '—',
        'delta_dir': 'up' | 'down' | 'flat',
        'sub':       optional subtitle string,
        'note':      optional small-print annotation (flagged field gaps, etc.),
    }

Windows:
  current: now-30d → now
  prior:   now-60d → now-30d
"""

from datetime import datetime, timedelta
from app import db
from app.models.user import User
from app.models.round import Round
from app.models.report import Report
from app.models.waitlist import WaitingList

# ---------------------------------------------------------------------------
# Pricing constants — update when pricing changes.
# ---------------------------------------------------------------------------
FOUNDING_PRICE_GBP = 4.99
STANDARD_PRICE_GBP = 7.99

# Subscription tier strings as stored in User.subscription_tier.
# NOTE: 'founding' tier does not yet exist in the DB — it will read 0 until
# founding member tiers are assigned. Standard paid users are stored as
# subscription_tier='premium' with subscription_active=True.
TIER_FOUNDING = 'founding'
TIER_PAID     = 'premium'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _windows():
    """Return (now, cur_start, pri_start, pri_end) datetimes for both windows."""
    now       = datetime.utcnow()
    cur_start = now - timedelta(days=30)
    pri_start = now - timedelta(days=60)
    pri_end   = cur_start          # pri window: [pri_start, pri_end)
    return now, cur_start, pri_start, pri_end


def _pct_delta(current, prior):
    """
    Calculate percentage change from prior to current.
    Returns (display_str, direction) where direction is 'up'|'down'|'flat'.
    Returns (None, 'flat') when prior is zero or None (insufficient data).
    """
    if prior is None or prior == 0:
        return None, 'flat'
    change = (current - prior) / prior * 100
    if abs(change) < 0.05:
        return '—', 'flat'
    direction = 'up' if change > 0 else 'down'
    sign      = '+' if change > 0 else ''
    return f'{sign}{change:.1f}%', direction


def _metric(value, prior=None, sub=None, note=None, fmt=None):
    """
    Package a single KPI value into the standard dict.
    fmt: optional callable to format value/prior for display (e.g. currency formatter).
    """
    delta_str, delta_dir = _pct_delta(
        value if value is not None else 0,
        prior,
    )
    if value is None:
        display = 'N/A'
    elif fmt:
        display = fmt(value)
    else:
        display = str(value)

    return {
        'value':     value,
        'display':   display,
        'prior':     prior,
        'delta_str': delta_str,
        'delta_dir': delta_dir,
        'sub':       sub,
        'note':      note,
    }


def _gbp(v):
    """Format a float as £X.XX."""
    return f'£{v:,.2f}'


def _pct_fmt(v):
    """Format a float as X.X%."""
    if v is None:
        return 'N/A'
    return f'{v:.1f}%'


# ---------------------------------------------------------------------------
# Individual KPI calculations
# ---------------------------------------------------------------------------

def kpi_total_users():
    """
    Total registered accounts (cumulative snapshot).
    Current value = all users now.
    Prior value   = users who existed before the current 30d window started.
    Delta shows growth rate of the total base.
    """
    now, cur_start, pri_start, pri_end = _windows()

    total_now   = User.query.count()
    total_prior = User.query.filter(User.created_at < cur_start).count()
    new_current = User.query.filter(User.created_at >= cur_start).count()

    return _metric(
        total_now,
        prior = total_prior,
        sub   = f'+{new_current} new this period',
    )


def kpi_paid_subscribers():
    """
    Users with subscription_active=True (any paid tier).
    Current = active paid users now.
    Prior   = active paid users who were created before the current window
              (rough proxy — no subscription history table exists).
    NOTE: No paid_at / activated_at field on User. Prior period is approximated
    using User.created_at < cur_start AND subscription_active=True.
    """
    now, cur_start, pri_start, pri_end = _windows()

    current = User.query.filter_by(subscription_active=True).count()

    # Proxy for prior: paid users who existed before the current window
    prior = User.query.filter(
        User.subscription_active == True,
        User.created_at < cur_start,
    ).count()

    new_paid = User.query.filter(
        User.subscription_active == True,
        User.created_at >= cur_start,
    ).count()

    return _metric(
        current,
        prior = prior,
        sub   = f'+{new_paid} new this period',
        note  = 'Prior based on created_at proxy — no subscription history table',
    )


def kpi_free_users():
    """
    Users with subscription_active=False (registered but not paying).
    NOTE: subscription_tier defaults to 'standard' for all users, so
    we distinguish free vs paid purely by subscription_active.
    """
    now, cur_start, pri_start, pri_end = _windows()

    current = User.query.filter_by(subscription_active=False).count()
    prior   = User.query.filter(
        User.subscription_active == False,
        User.created_at < cur_start,
    ).count()

    return _metric(
        current,
        prior = prior,
    )


def kpi_waitlist_signups():
    """
    New waitlist entries in the current 30d window vs prior 30d window.
    """
    now, cur_start, pri_start, pri_end = _windows()

    current = WaitingList.query.filter(WaitingList.signed_up_at >= cur_start).count()
    prior   = WaitingList.query.filter(
        WaitingList.signed_up_at >= pri_start,
        WaitingList.signed_up_at < pri_end,
    ).count()
    total   = WaitingList.query.count()

    return _metric(
        current,
        prior = prior,
        sub   = f'{total} total on list',
    )


def kpi_mrr():
    """
    Monthly Recurring Revenue split by tier.
    Returns a dict with 'founding', 'standard', and 'combined' sub-metrics.

    NOTE: 'founding' tier (subscription_tier='founding') does not exist in the
    DB yet — founding MRR will read £0.00 until that tier is assigned.
    Standard paid users are stored as subscription_tier='premium'.
    Prices: founding=£{FOUNDING_PRICE_GBP}, standard=£{STANDARD_PRICE_GBP}.
    """
    now, cur_start, pri_start, pri_end = _windows()

    def _mrr_for_tier(tier, price):
        count = User.query.filter(
            User.subscription_tier    == tier,
            User.subscription_active  == True,
        ).count()
        return count, count * price

    def _prior_mrr_for_tier(tier, price):
        count = User.query.filter(
            User.subscription_tier    == tier,
            User.subscription_active  == True,
            User.created_at           < cur_start,
        ).count()
        return count * price

    founding_count, founding_mrr = _mrr_for_tier(TIER_FOUNDING, FOUNDING_PRICE_GBP)
    standard_count, standard_mrr = _mrr_for_tier(TIER_PAID,     STANDARD_PRICE_GBP)
    combined_mrr                  = founding_mrr + standard_mrr

    prior_founding = _prior_mrr_for_tier(TIER_FOUNDING, FOUNDING_PRICE_GBP)
    prior_standard = _prior_mrr_for_tier(TIER_PAID,     STANDARD_PRICE_GBP)
    prior_combined  = prior_founding + prior_standard

    return {
        'founding': _metric(
            founding_mrr,
            prior   = prior_founding,
            sub     = f'{founding_count} founding member{"s" if founding_count != 1 else ""}',
            note    = "Tier 'founding' not yet assigned — will show £0.00 until populated",
            fmt     = _gbp,
        ),
        'standard': _metric(
            standard_mrr,
            prior   = prior_standard,
            sub     = f'{standard_count} paid subscriber{"s" if standard_count != 1 else ""}',
            fmt     = _gbp,
        ),
        'combined': _metric(
            combined_mrr,
            prior   = prior_combined,
            fmt     = _gbp,
        ),
        'founding_price': FOUNDING_PRICE_GBP,
        'standard_price': STANDARD_PRICE_GBP,
    }


def kpi_churn_rate():
    """
    Monthly churn rate = churned paid users in last 30d / paid users at start of window × 100.

    NOTE: No churned_at field exists on User. Proxy: users whose
    subscription_expires_at fell within the current 30d window AND
    subscription_active=False. This undercounts churn for manual cancellations
    that don't set subscription_expires_at. Add a churned_at field for accuracy.
    """
    now, cur_start, pri_start, pri_end = _windows()

    # Paid users at the start of the current window (denominator)
    paid_at_window_start = User.query.filter(
        User.subscription_active == True,
        User.created_at          < cur_start,
    ).count()

    # Proxy churn: expired subscriptions in the window with active=False
    churned_current = User.query.filter(
        User.subscription_active     == False,
        User.subscription_expires_at >= cur_start,
        User.subscription_expires_at <  now,
    ).count()

    churned_prior = User.query.filter(
        User.subscription_active     == False,
        User.subscription_expires_at >= pri_start,
        User.subscription_expires_at <  pri_end,
    ).count()

    paid_at_prior_start = User.query.filter(
        User.subscription_active == True,
        User.created_at          < pri_start,
    ).count()

    if paid_at_window_start > 0:
        rate_current = round(churned_current / paid_at_window_start * 100, 1)
    else:
        rate_current = None

    if paid_at_prior_start > 0:
        rate_prior = round(churned_prior / paid_at_prior_start * 100, 1)
    else:
        rate_prior = None

    # For churn, lower is better — invert delta direction
    delta_str, raw_dir = _pct_delta(
        rate_current if rate_current is not None else 0,
        rate_prior,
    )
    # Flip: churn going up is bad (down arrow for improvement UX is handled in template)
    delta_dir = {'up': 'down', 'down': 'up', 'flat': 'flat'}.get(raw_dir, 'flat')

    return {
        'value':     rate_current,
        'display':   _pct_fmt(rate_current),
        'prior':     rate_prior,
        'delta_str': delta_str,
        'delta_dir': delta_dir,
        'sub':       f'{churned_current} lapsed in 30d (proxy)',
        'note':      'No churned_at field — using subscription_expires_at proxy. Add churned_at for accuracy.',
        'lower_is_better': True,
    }


def kpi_free_to_paid_conversion():
    """
    Free-to-paid conversion rate for the current 30d window.
    Numerator:   users who registered free AND became paid within the window.
    Denominator: free users at the start of the window.

    NOTE: No converted_at field on User. Proxy: paid users (subscription_active=True)
    who registered (created_at) within the current window. This conflates
    'signed up and immediately chose paid' with 'converted from free', but is
    the best available signal. Add a converted_at field for true conversion tracking.
    """
    now, cur_start, pri_start, pri_end = _windows()

    free_at_window_start = User.query.filter(
        User.subscription_active == False,
        User.created_at          < cur_start,
    ).count()

    new_paid_current = User.query.filter(
        User.subscription_active == True,
        User.created_at          >= cur_start,
    ).count()

    free_at_prior_start = User.query.filter(
        User.subscription_active == False,
        User.created_at          < pri_start,
    ).count()

    new_paid_prior = User.query.filter(
        User.subscription_active == True,
        User.created_at          >= pri_start,
        User.created_at          < pri_end,
    ).count()

    rate_current = round(new_paid_current / free_at_window_start * 100, 1) if free_at_window_start else None
    rate_prior   = round(new_paid_prior   / free_at_prior_start   * 100, 1) if free_at_prior_start  else None

    return _metric(
        rate_current,
        prior = rate_prior,
        sub   = f'{new_paid_current} new paid this period',
        note  = 'No converted_at field — proxy uses created_at of paid users. Add converted_at for accuracy.',
        fmt   = _pct_fmt,
    )


def kpi_activation_rate():
    """
    Activation rate = users who have logged ≥1 complete round / total registered users.
    A user is 'activated' when they log their first round (regardless of window).
    Delta compares activation rate now vs rate 30d ago (users who had a round before cur_start
    / users who existed before cur_start).
    """
    now, cur_start, pri_start, pri_end = _windows()

    total_now    = User.query.count()
    activated_ids = {
        row[0] for row in
        db.session.query(Round.user_id)
        .filter(Round.status == 'complete')
        .distinct()
        .all()
    }
    activated_now = len(activated_ids)

    # Prior: activated users who existed before cur_start / total users before cur_start
    total_prior = User.query.filter(User.created_at < cur_start).count()
    activated_prior_ids = {
        row[0] for row in
        db.session.query(Round.user_id)
        .join(User, Round.user_id == User.id)
        .filter(
            Round.status    == 'complete',
            Round.completed_at < cur_start,
            User.created_at  < cur_start,
        )
        .distinct()
        .all()
    }
    activated_prior = len(activated_prior_ids)

    rate_current = round(activated_now  / total_now    * 100, 1) if total_now    else None
    rate_prior   = round(activated_prior / total_prior  * 100, 1) if total_prior  else None

    return _metric(
        rate_current,
        prior = rate_prior,
        sub   = f'{activated_now} of {total_now} users have logged a round',
        fmt   = _pct_fmt,
    )


def kpi_avg_rounds_per_active_user():
    """
    Average rounds per active user in the current 30d window.
    Active user = logged ≥1 complete round in the window.
    Prior = same calculation for the prior 30d window.
    """
    now, cur_start, pri_start, pri_end = _windows()

    rounds_current = Round.query.filter(
        Round.status       == 'complete',
        Round.completed_at >= cur_start,
        Round.completed_at <  now,
    ).count()

    active_users_current = db.session.query(Round.user_id).filter(
        Round.status       == 'complete',
        Round.completed_at >= cur_start,
        Round.completed_at <  now,
    ).distinct().count()

    rounds_prior = Round.query.filter(
        Round.status       == 'complete',
        Round.completed_at >= pri_start,
        Round.completed_at <  pri_end,
    ).count()

    active_users_prior = db.session.query(Round.user_id).filter(
        Round.status       == 'complete',
        Round.completed_at >= pri_start,
        Round.completed_at <  pri_end,
    ).distinct().count()

    avg_current = round(rounds_current / active_users_current, 1) if active_users_current else None
    avg_prior   = round(rounds_prior   / active_users_prior,   1) if active_users_prior   else None

    return _metric(
        avg_current,
        prior = avg_prior,
        sub   = f'{rounds_current} rounds by {active_users_current} active users',
        fmt   = lambda v: f'{v:.1f}',
    )


def kpi_reports_generated():
    """
    Reports generated in the current 30d window vs prior 30d window.
    Uses Report.generated_at as the timestamp.

    NOTE: No separate ShareCard model exists in this codebase. Share cards
    (Instagram export) are generated client-side via canvas and are not
    persisted to the DB. This metric tracks server-generated reports only.
    Add a share_cards table or a counter field to Report to track shares.
    """
    now, cur_start, pri_start, pri_end = _windows()

    current = Report.query.filter(
        Report.generated_at >= cur_start,
        Report.generated_at <  now,
    ).count()

    prior = Report.query.filter(
        Report.generated_at >= pri_start,
        Report.generated_at <  pri_end,
    ).count()

    total = Report.query.filter(Report.generated_at.isnot(None)).count()

    return _metric(
        current,
        prior = prior,
        sub   = f'{total} total reports all time',
        note  = 'Share cards not tracked — no ShareCard model. Add one to measure shares.',
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_all_kpis():
    """
    Calculate and return all KPI metrics for the admin dashboard.
    Each top-level key maps to a metric dict (see module docstring for schema).
    The 'mrr' key returns a nested dict with founding/standard/combined sub-metrics.
    """
    return {
        'total_users':          kpi_total_users(),
        'paid_subs':            kpi_paid_subscribers(),
        'free_users':           kpi_free_users(),
        'waitlist_signups':     kpi_waitlist_signups(),
        'mrr':                  kpi_mrr(),
        'churn_rate':           kpi_churn_rate(),
        'conversion_rate':      kpi_free_to_paid_conversion(),
        'activation_rate':      kpi_activation_rate(),
        'avg_rounds_per_user':  kpi_avg_rounds_per_active_user(),
        'reports_generated':    kpi_reports_generated(),
    }

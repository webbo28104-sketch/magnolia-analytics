"""
Stripe payment routes.

  /subscribe/<price_id>   — create Checkout Session and redirect
  /stripe/webhook/        — receive and verify Stripe webhook events
"""
from datetime import datetime
from decimal import Decimal
from functools import wraps

import stripe
from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for, abort,
)
from flask_login import current_user, login_required

from app import db

payments_bp = Blueprint('payments', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stripe():
    """Return the stripe module configured with the app's secret key."""
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    return stripe


def _get_or_create_customer(user):
    """
    Return the Stripe Customer ID for this user, creating one if needed.
    Persists stripe_customer_id to the DB immediately so re-runs are safe.
    """
    s = _stripe()
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = s.Customer.create(
        email=user.email,
        name=user.full_name,
        metadata={'user_id': str(user.id)},
    )
    user.stripe_customer_id = customer['id']
    db.session.commit()
    return customer['id']


def _price_to_tier(price_id):
    """Map a Stripe Price ID to a subscription_tier string."""
    cfg = current_app.config
    founding_ids = {
        cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', ''),
        cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL', ''),
    }
    founding_ids.discard('')

    if price_id in founding_ids:
        return 'founding_member'
    return 'premium'


def _price_to_locked_amount(price_id):
    """Return the Decimal amount to lock for founding members, or None."""
    cfg = current_app.config
    if price_id == cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', ''):
        return Decimal('9.99')
    if price_id == cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL', ''):
        return Decimal('89.00')
    return None


def _price_to_plan_display(price_id):
    """
    Return (plan_name, plan_price) strings for the subscription welcome email.
    Falls back to generic strings if the price ID isn't in config.
    """
    cfg = current_app.config
    mapping = {
        cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', ''): ('Founding Member Monthly', '£9.99/month'),
        cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL',  ''): ('Founding Member Annual',  '£89/year'),
        cfg.get('STRIPE_PRICE_STANDARD_MONTHLY', ''): ('Standard Monthly',         '£12.99/month'),
        cfg.get('STRIPE_PRICE_STANDARD_ANNUAL',  ''): ('Standard Annual',           '£109/year'),
    }
    mapping.pop('', None)  # remove any unconfigured entries keyed on ''
    return mapping.get(price_id, ('Magnolia Analytics', ''))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

@payments_bp.route('/subscribe/<price_id>')
@login_required
def checkout(price_id):
    """
    Create a Stripe Checkout Session for the given Price ID and redirect.
    Accepts only price IDs that are configured in the app — anything else 404s.
    """
    cfg = current_app.config
    known_prices = {
        cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', ''),
        cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL', ''),
        cfg.get('STRIPE_PRICE_STANDARD_MONTHLY', ''),
        cfg.get('STRIPE_PRICE_STANDARD_ANNUAL', ''),
    }
    known_prices.discard('')

    if price_id not in known_prices:
        abort(404)

    # Founding prices are only accessible to founding members.
    # Blocks URL manipulation by non-founding users.
    founding_ids = {
        cfg.get('STRIPE_PRICE_FOUNDING_MONTHLY', ''),
        cfg.get('STRIPE_PRICE_FOUNDING_ANNUAL', ''),
    }
    founding_ids.discard('')
    if price_id in founding_ids and not current_user.is_founding_member:
        abort(403)

    customer_id = _get_or_create_customer(current_user)

    s = _stripe()
    session = s.checkout.Session.create(
        customer=customer_id,
        mode='subscription',
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={'price_id': price_id, 'user_id': str(current_user.id)},
        success_url=url_for('dashboard.index', subscribed='true', _external=True),
        cancel_url=url_for('main.pricing', _external=True),
    )
    return redirect(session['url'], 303)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@payments_bp.route('/stripe/webhook/', methods=['POST'])
def webhook_handler():
    """
    Receive and verify Stripe webhook events.

    Security: payload is verified via HMAC signature before any processing.
    Authentication: exempt from the session-based access gate — Stripe sends
    no cookies.  The signature check is the sole auth mechanism.
    """
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    secret     = current_app.config.get('STRIPE_WEBHOOK_SECRET', '')

    s = _stripe()
    try:
        event = s.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        # Bad payload or invalid signature — reject silently
        abort(400)

    event_type = event['type']
    data       = event['data']['object']

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(data)
    elif event_type == 'customer.subscription.deleted':
        _handle_subscription_deleted(data)

    return '', 200


def _handle_checkout_completed(session_obj):
    """
    Activate a subscription after successful Stripe Checkout.

    Reads the price_id from the session metadata (set when creating the
    Checkout Session) to determine tier without a second API call.

    Duplicate-delivery guard: Stripe can re-deliver the same webhook event.
    We detect this by checking whether the subscription ID is already stored
    and active on the user — if so, we skip both the DB write and the email.
    """
    from app.models.user import User

    customer_id     = session_obj.get('customer')
    subscription_id = session_obj.get('subscription')
    price_id        = (session_obj.get('metadata') or {}).get('price_id', '')

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        current_app.logger.warning(
            '[stripe] checkout.session.completed: no user for customer %s', customer_id
        )
        return

    # Idempotency: if this subscription is already active on the user, a
    # duplicate webhook arrived — acknowledge it but do nothing.
    if user.stripe_subscription_id == subscription_id and user.subscription_active:
        current_app.logger.info(
            '[stripe] Duplicate checkout.session.completed ignored for sub %s (user_id=%s)',
            subscription_id, user.id,
        )
        return

    tier   = _price_to_tier(price_id)
    locked = _price_to_locked_amount(price_id)

    user.stripe_subscription_id = subscription_id
    user.stripe_price_id        = price_id
    user.subscription_tier      = tier
    user.subscription_active    = True

    if tier == 'founding_member':
        user.is_founding_member = True
        if not user.founding_member_since:
            user.founding_member_since = datetime.utcnow()
        if locked is not None:
            user.pricing_locked_at = locked

    try:
        db.session.commit()
        current_app.logger.info(
            '[stripe] Activated %s → tier=%s (user_id=%s)', subscription_id, tier, user.id
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[stripe] DB commit failed after checkout: %s', exc)
        return

    # Confirmation email — fires once, after a successful commit
    try:
        from app.services.sendgrid_service import send_subscription_welcome
        plan_name, plan_price = _price_to_plan_display(price_id)
        send_subscription_welcome(
            user        = user,
            plan_name   = plan_name,
            plan_price  = plan_price,
            is_founding = (tier == 'founding_member'),
        )
    except Exception as exc:
        # Email failure must never roll back a successful subscription activation
        current_app.logger.error(
            '[stripe] Subscription welcome email failed for user_id=%s: %s', user.id, exc
        )


def _handle_subscription_deleted(subscription_obj):
    """
    Downgrade a user when their Stripe subscription is cancelled / expires.

    Founding member status (is_founding_member, founding_member_since,
    pricing_locked_at) is intentionally preserved — it represents a
    historical fact about when they joined and what they were offered.
    """
    from app.models.user import User

    subscription_id = subscription_obj.get('id')
    user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not user:
        current_app.logger.warning(
            '[stripe] subscription.deleted: no user for subscription %s', subscription_id
        )
        return

    user.subscription_tier      = 'free'
    user.subscription_active    = False
    user.stripe_subscription_id = None
    user.stripe_price_id        = None

    try:
        db.session.commit()
        current_app.logger.info(
            '[stripe] Deactivated subscription for user_id=%s', user.id
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('[stripe] DB commit failed after deletion: %s', exc)


# ---------------------------------------------------------------------------
# Cancel subscription
# ---------------------------------------------------------------------------

@payments_bp.route('/cancel-subscription', methods=['GET'])
@login_required
def cancel_subscription_page():
    """Confirmation page before cancelling."""
    if not current_user.subscription_active or not current_user.stripe_subscription_id:
        flash("You don't have an active subscription to cancel.", 'info')
        return redirect(url_for('dashboard.index'))
    return render_template('payments/cancel.html')


@payments_bp.route('/cancel-subscription', methods=['POST'])
@login_required
def cancel_subscription():
    """
    Cancel the user's Stripe subscription at period end.

    Uses cancel_at_period_end=True so the user retains access until the
    billing period expires. The webhook (customer.subscription.deleted)
    will fire at that point and downgrade the account.
    """
    if not current_user.subscription_active or not current_user.stripe_subscription_id:
        flash("You don't have an active subscription to cancel.", 'info')
        return redirect(url_for('dashboard.index'))

    s = _stripe()
    try:
        s.Subscription.modify(
            current_user.stripe_subscription_id,
            cancel_at_period_end=True,
        )
        current_app.logger.info(
            '[stripe] cancel_at_period_end set for sub %s (user_id=%s)',
            current_user.stripe_subscription_id, current_user.id,
        )
        flash(
            'Your subscription has been cancelled and will end at the close of your current billing period. '
            'You keep full access until then.',
            'success',
        )
    except stripe.error.StripeError as exc:
        current_app.logger.error('[stripe] Cancel failed for user %s: %s', current_user.id, exc)
        flash('Something went wrong — please try again or contact support.', 'error')

    return redirect(url_for('dashboard.index'))

"""
Feature-access helpers for Magnolia Analytics.

Single source of truth for all subscription gates. Every gated feature in
routes and templates must go through these functions — no inline checks.
"""
from functools import wraps

from flask import redirect, url_for, flash
from flask_login import current_user


# Tiers that carry active access — anything not in this set is 'free' / lapsed.
_PAID_TIERS = {'founding_member', 'premium', 'standard'}


def is_pro(user) -> bool:
    """
    Return True if the user has active paid access.

    Checks subscription_active OR founding member status (founding members
    always have access regardless of subscription_active, because their
    billing may be set up separately).
    """
    if user is None:
        return False
    if getattr(user, 'is_founding_member', False):
        return True
    return bool(getattr(user, 'subscription_active', False))


def subscription_required(f):
    """
    Decorator that gates a view behind an active subscription.

    Redirects unauthenticated users to the login page.
    Redirects users with subscription_tier == 'free' to the pricing page.
    All other tiers (founding_member, premium, standard) pass through.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.subscription_tier == 'free':
            flash('A subscription is required to access this page.', 'info')
            return redirect(url_for('main.pricing'))
        return f(*args, **kwargs)
    return decorated

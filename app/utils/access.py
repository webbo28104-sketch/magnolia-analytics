"""
Feature-access helpers for Magnolia Analytics.

Single source of truth for all subscription gates. Every gated feature in
routes and templates must go through these functions — no inline checks.
"""


def is_pro(user) -> bool:
    """
    Return True if the user has active pro (paid) access.

    Currently checks subscription_active only. When founding vs standard
    tiers are introduced (subscription_tier='founding' / 'premium'), update
    this function — do NOT add inline tier checks elsewhere.

    # TODO: when Stripe is live, also verify subscription_expires_at has not
    # lapsed for non-admin-granted subscriptions.
    """
    if user is None:
        return False
    return bool(getattr(user, 'subscription_active', False))

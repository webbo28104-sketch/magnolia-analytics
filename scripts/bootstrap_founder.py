"""
Bootstrap founder/developer account with pro access.

Usage:
    python scripts/bootstrap_founder.py

Or from a Railway one-off job / Flask shell:
    exec(open('scripts/bootstrap_founder.py').read())

# TEMP: founder access — remove once Stripe is live
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.user import User

FOUNDER_EMAIL = 'webbo28104@gmail.com'

app = create_app()
with app.app_context():
    user = User.query.filter_by(email=FOUNDER_EMAIL).first()
    if not user:
        print(f'[bootstrap_founder] User not found: {FOUNDER_EMAIL}')
        print('Run this script again after the account has been registered.')
        sys.exit(0)

    if user.subscription_active:
        print(f'[bootstrap_founder] {FOUNDER_EMAIL} already has subscription_active=True — nothing to do.')
        sys.exit(0)

    user.subscription_active = True
    db.session.commit()
    print(f'[bootstrap_founder] Set subscription_active=True for {FOUNDER_EMAIL}')

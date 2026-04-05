import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///magnolia_dev.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Claude API
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

    # SendGrid
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
    SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'reports@magnoliaanalytics.com')

    # Square Payments
    SQUARE_ACCESS_TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN', '')
    SQUARE_ENVIRONMENT = os.environ.get('SQUARE_ENVIRONMENT', 'sandbox')

    # App
    APP_NAME = 'Magnolia Analytics'
    DEFAULT_COURSE = 'Seaford GC'

    # Access control — set to True to require an invite code at registration
    INVITE_ONLY = True

    # Founding member period — set False at public launch
    BETA_MODE = True

    # Stripe
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_SECRET_KEY      = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET  = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    # Stripe Price IDs (filled in .env — never hardcode)
    STRIPE_PRICE_FOUNDING_MONTHLY = os.environ.get('STRIPE_PRICE_FOUNDING_MONTHLY', '')
    STRIPE_PRICE_FOUNDING_ANNUAL  = os.environ.get('STRIPE_PRICE_FOUNDING_ANNUAL', '')
    STRIPE_PRICE_STANDARD_MONTHLY = os.environ.get('STRIPE_PRICE_STANDARD_MONTHLY', '')
    STRIPE_PRICE_STANDARD_ANNUAL  = os.environ.get('STRIPE_PRICE_STANDARD_ANNUAL', '')


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///magnolia_dev.db')


class ProductionConfig(Config):
    DEBUG = False
    # Railway injects DATABASE_URL automatically
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://'  # SQLAlchemy requires postgresql://
    )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

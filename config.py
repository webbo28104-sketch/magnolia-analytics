import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///magnolia_dev.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # DeepSeek API
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

    # SendGrid
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
    SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'reports@magnoliaanalytics.com')

    # Square Payments
    SQUARE_ACCESS_TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN', '')
    SQUARE_ENVIRONMENT = os.environ.get('SQUARE_ENVIRONMENT', 'sandbox')

    # App
    APP_NAME = 'Magnolia Analytics'
    DEFAULT_COURSE = 'Seaford GC'

    # Access control — invite-only gate removed; direct signup now open
    INVITE_ONLY = False

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


def _db_url():
    """DATABASE_URL normalised for SQLAlchemy + psycopg2 (Neon / Railway / Heroku styles)."""
    url = os.environ.get('DATABASE_URL', '')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _db_url()
    # Serverless hosting: connections can go stale between invocations
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 280, 'pool_size': 2, 'max_overflow': 3}


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

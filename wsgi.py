"""WSGI entry point (Vercel detects the Flask `app` here)."""
import os

from app import create_app

app = create_app(os.environ.get('FLASK_ENV', 'production'))

"""
Railway pre-deploy migration runner.

Called by the preDeployCommand in railway.json before gunicorn starts.
Runs _run_column_migrations() against the configured database, then exits.
If this script fails, Railway aborts the deploy — which is the correct
behaviour: never start the app with a broken schema.
"""
import os
import sys

from app import create_app

app = create_app(os.environ.get('FLASK_ENV', 'production'))
print('[migrate] Column migrations complete.', flush=True)

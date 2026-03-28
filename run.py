import os
import logging
from app import create_app

app = create_app(os.environ.get('FLASK_ENV', 'production'))

# Wire Flask's logger to gunicorn's error-log handlers so application
# log lines actually appear in Railway's deploy log stream.
# This block is skipped when running via `flask run` or `python run.py`.
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

    # Emit a startup diagnostic so we can confirm logging is wired correctly
    # and verify that the SendGrid env vars are present.
    with app.app_context():
        sg_key = os.environ.get('SENDGRID_API_KEY', '')
        sg_from = os.environ.get('SENDGRID_FROM_EMAIL', '')
        app.logger.info(
            '[startup] SENDGRID_API_KEY present=%s len=%d  SENDGRID_FROM_EMAIL=%s',
            bool(sg_key), len(sg_key), sg_from or '(not set)',
        )
        if not sg_key:
            app.logger.warning(
                '[startup] SENDGRID_API_KEY is MISSING — emails will not be sent!'
            )

if __name__ == '__main__':
    app.run(debug=True)

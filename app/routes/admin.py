"""
Temporary admin diagnostics blueprint.
REMOVE after SendGrid emails are confirmed working.
"""
import os
import traceback

from flask import Blueprint, jsonify

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin/test-email')
def test_email():
    """
    Hit this in a browser to test SendGrid end-to-end and see the exact result.
    Returns JSON — no auth required (temporary diagnostic only).
    REMOVE this route once emails are confirmed working.
    """
    api_key    = os.environ.get('SENDGRID_API_KEY', '')
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', '') or 'team@magnoliaanalytics.golf'
    to_email   = 'team@magnoliaanalytics.golf'

    result = {
        'api_key_present':  bool(api_key),
        'api_key_prefix':   (api_key[:8] + '…') if len(api_key) > 8 else '(empty)',
        'from_email':       from_email,
        'to_email':         to_email,
        'sendgrid_called':  False,
        'status_code':      None,
        'success':          False,
        'error':            None,
    }

    if not api_key:
        result['error'] = (
            'SENDGRID_API_KEY env var is not set or is empty. '
            'Check Railway → Variables and ensure the key is present with no extra whitespace.'
        )
        return jsonify(result), 200

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject='[TEST] Magnolia Analytics — SendGrid diagnostic',
            html_content=(
                '<p>This is a test email sent from the '
                '<code>/admin/test-email</code> diagnostic route.</p>'
                '<p>If you received this, SendGrid is working correctly.</p>'
            ),
        )

        result['sendgrid_called'] = True
        response = SendGridAPIClient(api_key).send(message)
        result['status_code'] = response.status_code
        result['success']     = response.status_code in (200, 202)

    except Exception as exc:
        result['error']     = str(exc)
        result['traceback'] = traceback.format_exc()

    return jsonify(result), 200

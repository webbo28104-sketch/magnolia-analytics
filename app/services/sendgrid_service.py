"""
SendGrid email service — delivers branded HTML reports to golfers.
Placeholder implementation: replace with live SendGrid SDK call
when your API key is ready.
"""
import os
from datetime import datetime
from app import db


REPORT_EMAIL_SUBJECT = "Your Magnolia Analytics Round Report 🏌️"


def _build_email_html(round_, report_html: str) -> str:
    """Wrap the report HTML fragment in a full branded email template."""
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Your Course'

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Magnolia Analytics — Round Report</title>
  <style>
    body {{ margin: 0; padding: 0; background-color: #f4f1eb; font-family: Georgia, serif; }}
    .wrapper {{ max-width: 640px; margin: 0 auto; background: #fff; }}
    .header {{ background-color: #1B4332; padding: 32px 40px; text-align: center; }}
    .header h1 {{ color: #C9A84C; font-size: 28px; margin: 0; letter-spacing: 2px; }}
    .header p {{ color: #a8c5b5; margin: 8px 0 0; font-size: 14px; }}
    .body {{ padding: 40px; }}
    .footer {{ background-color: #1B4332; padding: 24px 40px; text-align: center; }}
    .footer p {{ color: #a8c5b5; font-size: 12px; margin: 0; }}
    .footer a {{ color: #C9A84C; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>MAGNOLIA ANALYTICS</h1>
      <p>{round_.date_played} &nbsp;·&nbsp; {course_name}</p>
    </div>
    <div class="body">
      <p style="color: #1B4332;">Hello {user.first_name},</p>
      <p style="color: #555;">Here is your performance report from today's round.</p>
      {report_html}
    </div>
    <div class="footer">
      <p>
        Magnolia Analytics &nbsp;·&nbsp;
        <a href="#">View in browser</a> &nbsp;·&nbsp;
        <a href="#">Unsubscribe</a>
      </p>
    </div>
  </div>
</body>
</html>
"""


def send_report_email(round_) -> bool:
    """
    Send the generated report to the golfer via SendGrid.

    Returns True on success, False on failure.
    Replace the placeholder block with the live SendGrid SDK call.
    """
    api_key = os.environ.get('SENDGRID_API_KEY', '')
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'reports@magnoliaanalytics.com')

    report = round_.report
    if not report or not report.html_content:
        return False

    user = round_.golfer
    email_html = _build_email_html(round_, report.html_content)

    # ------------------------------------------------------------------ #
    # LIVE IMPLEMENTATION — uncomment when SendGrid key is available       #
    # ------------------------------------------------------------------ #
    # from sendgrid import SendGridAPIClient
    # from sendgrid.helpers.mail import Mail
    #
    # message = Mail(
    #     from_email=from_email,
    #     to_emails=user.email,
    #     subject=REPORT_EMAIL_SUBJECT,
    #     html_content=email_html
    # )
    # sg = SendGridAPIClient(api_key)
    # response = sg.send(message)
    # success = response.status_code in (200, 202)
    # ------------------------------------------------------------------ #

    # PLACEHOLDER
    print(f'[SendGrid Placeholder] Would send report to {user.email}')
    success = True

    if success:
        report.emailed_at = datetime.utcnow()
        report.email_status = 'sent'
        db.session.commit()

    return success

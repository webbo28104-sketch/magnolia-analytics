"""
One-off script: send a test email for every template to a single address.
Run with: railway run python3 send_test_emails.py

All 9 emails are sent to TEST_TO regardless of the real recipient.
Uses a temporary SQLite DB so the script runs locally without needing
access to the production Railway Postgres instance.
"""

import os
import sys
import tempfile

TEST_TO = 'webbo28104@gmail.com'

# ---------------------------------------------------------------------------
# Point to a local SQLite DB so create_app() doesn't need Postgres
# ---------------------------------------------------------------------------
_tmp_db = tempfile.mktemp(suffix='.db')
os.environ['DATABASE_URL'] = f'sqlite:///{_tmp_db}'
os.environ.setdefault('FLASK_ENV', 'production')

from run import app  # noqa — creates the Flask app

app.config['SERVER_NAME']          = 'magnoliaanalytics.golf'
app.config['PREFERRED_URL_SCHEME'] = 'https'

with app.app_context():
    from flask import render_template, url_for
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    from datetime import datetime

    from app.services.sendgrid_service import _sg_color, _sg_bar_pct, _fmt_sg

    api_key    = os.environ.get('SENDGRID_API_KEY', '').strip()
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'hello@magnoliaanalytics.golf').strip()

    if not api_key:
        print('ERROR: SENDGRID_API_KEY is not set — aborting.')
        sys.exit(1)

    sg = SendGridAPIClient(api_key)

    def _send(subject: str, html: str) -> int:
        msg = Mail(from_email=from_email, to_emails=TEST_TO,
                   subject=subject, html_content=html)
        resp = sg.send(msg)
        return resp.status_code

    # -------------------------------------------------------------------------
    # Fake data — no DB queries needed
    # -------------------------------------------------------------------------
    class _FakeUser:
        first_name = 'Charlie'
        last_name  = 'Webb'
        email      = TEST_TO

    class _FakeRound:
        id                    = 1
        total_score           = 82
        holes_played          = 18
        fairways_hit          = 9
        fairways_available    = 14
        gir_count             = 7
        total_putts           = 33
        sg_off_tee            = 0.4
        sg_approach           = -0.3
        sg_atg                = 0.1
        sg_putting            = 0.7
        sg_total              = 0.9
        counts_for_official_hc = True
        date_played           = datetime(2026, 3, 29)

        class course:
            name = 'Wentworth Club'

        class report:
            narrative_text = (
                "A solid round showing real improvement around the greens. "
                "Your putting was the standout category this week, gaining nearly "
                "a stroke on the field. The approach game needs attention — "
                "several mid-iron shots missed their landing zones on the back nine."
            )

        def score_vs_par(self):
            return 10   # +10 vs par

    class _FakeWaitlistEntry:
        name             = 'Alex Golfer'
        email            = TEST_TO
        message          = 'Been playing for 10 years, 12hcp, keen to improve.'
        handicap         = 12
        rounds_per_month = 3
        created_at       = datetime(2026, 3, 28)

    user           = _FakeUser()
    r              = _FakeRound()
    waitlist_entry = _FakeWaitlistEntry()

    course_name = r.course.name
    svp         = r.score_vs_par()
    svp_display = ('E' if svp == 0 else (f'+{svp}' if svp > 0 else str(svp)))

    fir_pct        = round(r.fairways_hit / r.fairways_available * 100)
    gir_pct        = round(r.gir_count / r.holes_played * 100)
    putts_per_hole = round(r.total_putts / r.holes_played, 1)
    scramble_pct   = 40   # fake

    sg_cats = []
    for label, attr in [('Off the Tee',       'sg_off_tee'),
                         ('Approach',           'sg_approach'),
                         ('Around the Green',   'sg_atg'),
                         ('Putting',            'sg_putting')]:
        val = getattr(r, attr)
        sg_cats.append({'label': label, 'value': val, 'display': _fmt_sg(val),
                        'color': _sg_color(val), 'bar_pct': _sg_bar_pct(val, 4.0),
                        'positive': val >= 0})

    paras     = [p.strip() for p in r.report.narrative_text.split('\n\n') if p.strip()]
    narrative = paras[0] if paras else r.report.narrative_text

    position   = 319
    real_count = 1

    # -------------------------------------------------------------------------
    # 1. round_report
    # -------------------------------------------------------------------------
    html = render_template(
        'email/round_report.html',
        user=user, course_name=course_name,
        date_played=r.date_played.strftime('%d %B %Y'),
        round_type='Official' if r.counts_for_official_hc else 'Casual',
        total_score=r.total_score, score_vs_par_display=svp_display,
        fir_pct=fir_pct, gir_pct=gir_pct, putts_per_hole=putts_per_hole,
        scramble_pct=scramble_pct, sg_cats=sg_cats,
        sg_total_display=_fmt_sg(r.sg_total),
        sg_total_color=_sg_color(r.sg_total),
        sg_total_bar_pct=_sg_bar_pct(r.sg_total, 8.0),
        sg_total_positive=r.sg_total >= 0,
        narrative=narrative,
        report_url=url_for('reports.view_report', round_id=r.id, _external=True),
    )
    code = _send('TEMPLATE REVIEW: Round Report Email', html)
    print(f'1. round_report         → {code}')

    # -------------------------------------------------------------------------
    # 2. welcome
    # -------------------------------------------------------------------------
    html = render_template(
        'email/welcome.html',
        first_name=user.first_name,
        new_round_url=url_for('rounds.new_round', _external=True),
    )
    code = _send('TEMPLATE REVIEW: Welcome Email', html)
    print(f'2. welcome              → {code}')

    # -------------------------------------------------------------------------
    # 3. subscription_welcome
    # -------------------------------------------------------------------------
    html = render_template(
        'email/subscription_welcome.html',
        first_name=user.first_name,
        plan_name='Founding Member Monthly',
        plan_price='£9.99/month',
        is_founding=True,
        dashboard_url=url_for('dashboard.index', _external=True),
        install_url=url_for('main.index', _external=True) + '#install',
    )
    code = _send('TEMPLATE REVIEW: Subscription Welcome Email', html)
    print(f'3. subscription_welcome → {code}')

    # -------------------------------------------------------------------------
    # 4. invite_code
    # -------------------------------------------------------------------------
    html = render_template(
        'email/invite_code.html',
        first_name=user.first_name,
        code='GOLF-TEST-0001',
        register_url=url_for('waitlist.index', _external=True),
    )
    code = _send('TEMPLATE REVIEW: Invite Code Email', html)
    print(f'4. invite_code          → {code}')

    # -------------------------------------------------------------------------
    # 5. waitlist_confirm
    # -------------------------------------------------------------------------
    html = render_template('email/waitlist_confirm.html',
                           name=waitlist_entry.name.split()[0], position=position)
    code = _send('TEMPLATE REVIEW: Waitlist Confirmation Email', html)
    print(f'5. waitlist_confirm     → {code}')

    # -------------------------------------------------------------------------
    # 6. personal_best
    # -------------------------------------------------------------------------
    html = render_template(
        'email/personal_best.html',
        first_name=user.first_name,
        pb_label="Best score vs par you've ever recorded (-3)",
        course_name=course_name,
        date_played=r.date_played.strftime('%d %B %Y'),
        report_url=url_for('reports.view_report', round_id=r.id, _external=True),
    )
    code = _send('TEMPLATE REVIEW: Personal Best Email', html)
    print(f'6. personal_best        → {code}')

    # -------------------------------------------------------------------------
    # 7. password_reset
    # -------------------------------------------------------------------------
    html = render_template(
        'email/password_reset.html',
        first_name=user.first_name,
        reset_url=url_for('auth.reset_password', token='test-token-abc123', _external=True),
    )
    code = _send('TEMPLATE REVIEW: Password Reset Email', html)
    print(f'7. password_reset       → {code}')

    # -------------------------------------------------------------------------
    # 8. password_changed
    # -------------------------------------------------------------------------
    html = render_template(
        'email/password_changed.html',
        first_name=user.first_name,
        changed_at=datetime.utcnow().strftime('%d %B %Y at %H:%M UTC'),
    )
    code = _send('TEMPLATE REVIEW: Password Changed Email', html)
    print(f'8. password_changed     → {code}')

    # -------------------------------------------------------------------------
    # 9. admin_waitlist  (normally goes to team@ — redirected to TEST_TO)
    # -------------------------------------------------------------------------
    html = render_template(
        'email/admin_waitlist.html',
        entry=waitlist_entry, position=position, real_count=real_count,
    )
    msg = Mail(from_email=from_email, to_emails=TEST_TO,
               subject='TEMPLATE REVIEW: Admin Waitlist Notification Email',
               html_content=html)
    resp = sg.send(msg)
    print(f'9. admin_waitlist       → {resp.status_code}')

    print('\nDone. All 9 templates sent to', TEST_TO)

# Tidy up temp DB file
try:
    os.unlink(_tmp_db)
except OSError:
    pass

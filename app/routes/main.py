from flask import Blueprint, render_template, send_from_directory, current_app
from flask_login import current_user

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/pricing')
def pricing():
    is_founding = (
        current_user.is_authenticated and
        getattr(current_user, 'is_founding_member', False)
    )
    return render_template('pricing.html', is_founding_member=is_founding)


@main_bp.route('/glossary')
def glossary():
    return render_template('glossary.html')


@main_bp.route('/upgrade')
def upgrade():
    is_founding = (
        current_user.is_authenticated and
        getattr(current_user, 'is_founding_member', False)
    )
    pid_fm = current_app.config.get('STRIPE_PRICE_FOUNDING_MONTHLY', '')
    pid_sm = current_app.config.get('STRIPE_PRICE_STANDARD_MONTHLY', '')
    return render_template(
        'upgrade.html',
        is_founding_member=is_founding,
        pid_fm=pid_fm,
        pid_sm=pid_sm,
    )


@main_bp.route('/sw.js')
def service_worker():
    """Serve the service worker from root scope so it can intercept all requests."""
    response = send_from_directory(current_app.static_folder, 'sw.js',
                                   mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@main_bp.route('/manifest.json')
def manifest():
    return send_from_directory(current_app.static_folder, 'manifest.json',
                               mimetype='application/manifest+json')


@main_bp.route('/internal/eg-sync', methods=['POST'])
def eg_sync_all():
    """Daily England Golf sync for every linked user. Called by a GitHub Actions schedule."""
    import hmac
    import os
    from flask import request, jsonify
    from app.models.user import User
    from app.utils.eg_sync import sync_user

    secret = os.environ.get('CRON_SECRET', '')
    given = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if not secret or not hmac.compare_digest(given, secret):
        return jsonify({'error': 'unauthorised'}), 401
    ok = failed = 0
    for user in User.query.filter(User.eg_member_no.isnot(None)).all():
        try:
            if sync_user(user):
                ok += 1
            else:
                failed += 1
        except Exception:
            current_app.logger.exception(f'[eg-sync] user {user.id} failed')
            failed += 1
    return jsonify({'synced': ok, 'failed': failed})

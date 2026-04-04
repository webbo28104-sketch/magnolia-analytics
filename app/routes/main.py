from flask import Blueprint, render_template, send_from_directory, current_app

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/pricing')
def pricing():
    return render_template('pricing.html')

@main_bp.route('/glossary')
def glossary():
    return render_template('glossary.html')

@main_bp.route('/upgrade')
def upgrade():
    return render_template('upgrade.html')

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

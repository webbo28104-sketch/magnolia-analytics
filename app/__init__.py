from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, user_logged_in
from config import config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access your dashboard.'
login_manager.login_message_category = 'info'


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.rounds import rounds_bp
    from app.routes.reports import reports_bp
    from app.routes.courses import courses_bp
    from app.routes.profile import profile_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(rounds_bp, url_prefix='/rounds')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(courses_bp)
    app.register_blueprint(profile_bp, url_prefix='/profile')

    # Recompute stale stats for the user on every login (covers login + register)
    user_logged_in.connect(_recompute_stale_on_login, app)

    # Create all tables on startup (safe to call repeatedly)
    with app.app_context():
        from app.models.user import User            # noqa
        from app.models.course import Course        # noqa
        from app.models.tee_set import TeeSet       # noqa
        from app.models.course_hole import CourseHole  # noqa
        from app.models.round import Round          # noqa
        from app.models.hole import Hole            # noqa
        from app.models.report import Report        # noqa
        db.create_all()
        _run_column_migrations()

    return app


def _run_column_migrations():
    """Safely add columns that were added after initial table creation."""
    migrations = [
        ('holes',     'approach_distance',   'INTEGER'),
        ('holes',     'second_shot_distance', 'INTEGER'),
        ('tee_sets',  'front_course_rating',  'REAL'),
        ('tee_sets',  'back_course_rating',   'REAL'),
        ('tee_sets',  'front_slope_rating',   'INTEGER'),
        ('tee_sets',  'back_slope_rating',    'INTEGER'),
        ('rounds',    'nine_hole_selection',  'VARCHAR(10)'),
        ('users',     'home_country',          'VARCHAR(100)'),
        ('reports',   'narrative_text',        'TEXT'),
        ('reports',   'weather_json',          'TEXT'),
        ('reports',   'insights_json',         'TEXT'),
        ('rounds',    'sg_off_tee',             'REAL'),
        ('rounds',    'sg_approach',            'REAL'),
        ('rounds',    'sg_atg',                 'REAL'),
        ('rounds',    'sg_putting',             'REAL'),
        ('rounds',    'sg_total',               'REAL'),
        ('rounds',    'algo_version',           'INTEGER'),
        ('rounds',    'counts_for_official_hc', 'BOOLEAN DEFAULT TRUE'),
        ('users',     'official_handicap_index', 'REAL'),
    ]
    for table, column, col_type in migrations:
        try:
            db.session.execute(
                db.text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
            )
            db.session.commit()
        except Exception:
            db.session.rollback()   # column already exists — fine


def _recompute_stale_on_login(sender, user, **kwargs):
    """
    Recompute stored stats for any of the user's rounds that are stale.

    Connected to Flask-Login's user_logged_in signal, so it fires after
    every successful login_user() call — including new registrations.
    Runs synchronously on the login thread before the redirect completes;
    with typical round counts this adds negligible latency.

    Stale = algo_version is NULL or < CURRENT_ALGO_VERSION.
    """
    from app.utils.round_stats import compute_all_stats, CURRENT_ALGO_VERSION
    from app.models.round import Round
    try:
        stale = Round.query.filter(
            Round.user_id == user.id,
            Round.status == 'complete',
            db.or_(
                Round.algo_version.is_(None),
                Round.algo_version < CURRENT_ALGO_VERSION,
            )
        ).all()

        if not stale:
            return

        updated = sum(1 for r in stale if compute_all_stats(r))
        if updated:
            db.session.commit()
            sender.logger.info(
                f'[login] Recomputed stats for {updated} stale round(s) '
                f'(user_id={user.id}, algo_version={CURRENT_ALGO_VERSION})'
            )
    except Exception as exc:
        db.session.rollback()
        sender.logger.warning(
            f'[login] Stale round recompute failed for user_id={user.id}: {exc}'
        )

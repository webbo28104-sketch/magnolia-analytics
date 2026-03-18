from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
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
    ]
    for table, column, col_type in migrations:
        try:
            db.session.execute(
                db.text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
            )
            db.session.commit()
        except Exception:
            db.session.rollback()   # column already exists — fine

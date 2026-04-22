"""Railway pre-deploy migration runner."""
import os
from sqlalchemy import text, inspect
from app import create_app, db

def _run_column_migrations(engine):
    inspector = inspect(engine)
    holes_cols = {c['name'] for c in inspector.get_columns('holes')}
    with engine.connect() as conn:
        if 'shots_json' not in holes_cols:
            conn.execute(text('ALTER TABLE holes ADD COLUMN shots_json TEXT'))
        if 'atg_strokes' not in holes_cols:
            conn.execute(text('ALTER TABLE holes ADD COLUMN atg_strokes INTEGER DEFAULT 1'))
        conn.commit()

app = create_app(os.environ.get('FLASK_ENV', 'production'))
with app.app_context():
    _run_column_migrations(db.engine)
print('[migrate] Column migrations complete.', flush=True)

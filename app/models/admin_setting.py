from app import db
from datetime import datetime


class AdminSetting(db.Model):
    """Simple key/value store for manually-entered admin metrics (NPS, email open rate, etc.)."""

    __tablename__ = 'admin_settings'

    id         = db.Column(db.Integer, primary_key=True)
    key        = db.Column(db.String(100), unique=True, nullable=False)
    value      = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, key, default=None):
        """Fetch a setting by key, returning default if absent."""
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key, value):
        """Upsert a setting. Caller is responsible for db.session.commit()."""
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value      = value
            row.updated_at = datetime.utcnow()
        else:
            row = cls(key=key, value=value)
            db.session.add(row)

    def __repr__(self):
        return f'<AdminSetting {self.key}={self.value!r}>'

from app import db
from datetime import datetime


class AccessCode(db.Model):
    __tablename__ = 'access_codes'

    id            = db.Column(db.Integer, primary_key=True)
    code          = db.Column(db.String(30), unique=True, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    used_at       = db.Column(db.DateTime, nullable=True)
    used_by_email = db.Column(db.String(120), nullable=True)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def is_available(self):
        """True if this code can still be used to register."""
        return self.is_admin or self.used_at is None

    def mark_used(self, email: str):
        """Mark a single-use code as consumed."""
        if not self.is_admin:
            self.used_at       = datetime.utcnow()
            self.used_by_email = email

    def __repr__(self):
        return f'<AccessCode {self.code}>'

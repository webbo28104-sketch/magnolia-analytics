from app import db
from datetime import datetime


class WaitingList(db.Model):
    __tablename__ = 'waiting_list'

    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(100), nullable=False)
    email            = db.Column(db.String(120), nullable=False, unique=True)
    handicap         = db.Column(db.Float, nullable=True)
    rounds_per_month = db.Column(db.Integer, nullable=True)
    signed_up_at     = db.Column(db.DateTime, default=datetime.utcnow)
    access_code      = db.Column(db.String(30), nullable=True)
    status           = db.Column(db.String(20), default='pending')
    invited_at       = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<WaitingList {self.email}>'

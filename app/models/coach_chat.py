from app import db
from datetime import datetime


class CoachChat(db.Model):
    """
    A saved conversation with the coach.

    round_id is set for the small ask-bar embedded in a round report's
    Coaching tab (one chat per round, auto-created on first question).
    round_id is NULL for a general chat started from the dashboard, where
    the coach can draw on the golfer's whole history rather than one round.
    """
    __tablename__ = 'coach_chats'

    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    round_id = db.Column(db.Integer, db.ForeignKey('rounds.id'), nullable=True)

    title = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship(
        'CoachMessage', backref='chat', lazy='dynamic',
        order_by='CoachMessage.created_at', cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<CoachChat id={self.id} user_id={self.user_id} round_id={self.round_id}>'


class CoachMessage(db.Model):
    __tablename__ = 'coach_messages'

    id      = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('coach_chats.id'), nullable=False)

    role    = db.Column(db.String(20), nullable=False)   # 'user' or 'coach'
    content = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CoachMessage id={self.id} chat_id={self.chat_id} role={self.role}>'

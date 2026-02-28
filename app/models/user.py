from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    handicap_index = db.Column(db.Float, default=0.0)
    home_course = db.Column(db.String(200), default='Seaford GC')

    # Subscription
    subscription_tier = db.Column(db.String(20), default='standard')
    subscription_active = db.Column(db.Boolean, default=False)
    square_customer_id = db.Column(db.String(255), nullable=True)
    subscription_expires_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    rounds = db.relationship('Round', backref='golfer', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def is_premium(self):
        return self.subscription_tier == 'premium' and self.subscription_active

    def __repr__(self):
        return f'<User {self.email}>'

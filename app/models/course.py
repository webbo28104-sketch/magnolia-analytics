from app import db
from datetime import datetime


class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(200), nullable=True)
    par = db.Column(db.Integer, default=72)
    course_rating = db.Column(db.Float, nullable=True)  # e.g. 71.4
    slope_rating = db.Column(db.Integer, nullable=True)  # e.g. 128
    yardage = db.Column(db.Integer, nullable=True)
    tee_set = db.Column(db.String(50), default='White')  # White, Yellow, Red, etc.

    # Hole-by-hole pars (stored as comma-separated string for simplicity)
    # e.g. "4,3,5,4,4,4,3,5,4,4,4,3,5,4,4,4,3,4"
    hole_pars = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    rounds = db.relationship('Round', backref='course', lazy='dynamic')

    @property
    def par_list(self):
        """Returns list of ints for each hole par."""
        if self.hole_pars:
            return [int(p) for p in self.hole_pars.split(',')]
        return [4] * 18  # Default to all par 4s

    def __repr__(self):
        return f'<Course {self.name}>'

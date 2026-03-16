from app import db
from datetime import datetime


class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(100), nullable=True, unique=True, index=True)  # API course ID
    name = db.Column(db.String(200), nullable=False, index=True)
    country = db.Column(db.String(100), default='England', index=True)
    region = db.Column(db.String(100), nullable=True)   # e.g. "East Sussex", "Fife"
    city = db.Column(db.String(100), nullable=True)     # nearest town/city
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    holes = db.Column(db.Integer, default=18)
    par = db.Column(db.Integer, default=72)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    tee_sets = db.relationship(
        'TeeSet', backref='course', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    course_holes = db.relationship(
        'CourseHole', backref='course', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    rounds = db.relationship('Round', backref='course', lazy='dynamic')

    @property
    def par_list(self):
        """Returns hole pars from the first available men's tee set, or defaults."""
        from app.models.tee_set import _default_pars
        ts = self.tee_sets.filter_by(gender='M').first() or self.tee_sets.first()
        if ts:
            return ts.par_list
        return _default_pars(self.par)

    @property
    def location_string(self):
        parts = [p for p in [self.city, self.region, self.country] if p]
        return ', '.join(parts)

    def to_dict(self):
        from app.models.tee_set import TeeSet
        tees = self.tee_sets.order_by(TeeSet.gender, TeeSet.course_rating).all()
        return {
            'id': self.id,
            'external_id': self.external_id,
            'name': self.name,
            'country': self.country,
            'region': self.region or '',
            'city': self.city or '',
            'par': self.par,
            'holes': self.holes,
            'location': self.location_string,
            'tees_count': len(tees),
        }

    def __repr__(self):
        return f'<Course {self.name}>'

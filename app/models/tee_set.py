from app import db


class TeeSet(db.Model):
    __tablename__ = 'tee_sets'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)

    name = db.Column(db.String(50), nullable=False)     # e.g. "Medal", "Yellow", "Championship"
    color = db.Column(db.String(30), nullable=True)     # e.g. "white", "yellow", "red", "black"
    gender = db.Column(db.String(1), default='M')       # M = Men, W = Women, X = Mixed

    course_rating = db.Column(db.Float, nullable=False)
    slope_rating = db.Column(db.Integer, nullable=False)   # 55–155
    total_yardage = db.Column(db.Integer, nullable=True)
    total_par = db.Column(db.Integer, default=72)

    # Relationships
    course_holes = db.relationship(
        'CourseHole', backref='tee_set', lazy='dynamic',
        order_by='CourseHole.hole_number', cascade='all, delete-orphan'
    )
    rounds = db.relationship('Round', backref='tee_set_obj', lazy='dynamic')

    @property
    def par_list(self):
        """Returns list of pars per hole (18 items)."""
        holes = self.course_holes.order_by('CourseHole.hole_number').all()
        if holes:
            return [h.par for h in holes]
        # Fallback: distribute pars evenly based on total_par
        return _default_pars(self.total_par)

    @property
    def display_name(self):
        return f'{self.name} ({self.color.title() if self.color else ""})'

    def __repr__(self):
        return f'<TeeSet {self.name} — rating {self.course_rating}/{self.slope_rating}>'


def _default_pars(total_par):
    """Generate a reasonable 18-hole par distribution for a given total."""
    distributions = {
        72: [4, 4, 3, 4, 5, 4, 3, 4, 5, 4, 3, 4, 4, 5, 4, 3, 4, 5],
        71: [4, 4, 3, 4, 5, 4, 3, 4, 4, 4, 3, 4, 4, 5, 4, 3, 4, 5],
        70: [4, 4, 3, 4, 5, 4, 3, 4, 4, 4, 3, 4, 4, 4, 4, 3, 4, 5],
        69: [4, 4, 3, 4, 4, 4, 3, 4, 4, 4, 3, 4, 4, 5, 4, 3, 4, 4],
        68: [4, 4, 3, 4, 4, 4, 3, 4, 4, 4, 3, 4, 4, 5, 4, 3, 4, 3],
        67: [4, 4, 3, 4, 4, 4, 3, 4, 4, 4, 3, 4, 4, 4, 4, 3, 4, 3],
    }
    return distributions.get(total_par, [4] * 18)

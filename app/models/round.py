from app import db
from datetime import datetime
from app.models.hole import Hole


class Round(db.Model):
    __tablename__ = 'rounds'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    tee_set_id = db.Column(db.Integer, db.ForeignKey('tee_sets.id'), nullable=True)

    # Round metadata
    date_played = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    holes_played = db.Column(db.Integer, default=18)          # 9 or 18
    nine_hole_selection = db.Column(db.String(10), nullable=True)  # 'front', 'back', or None
    tee_set = db.Column(db.String(50), default='White')       # human-readable label

    # Totals (computed after submission)
    total_score = db.Column(db.Integer, nullable=True)
    total_putts = db.Column(db.Integer, nullable=True)
    fairways_hit = db.Column(db.Integer, nullable=True)
    fairways_available = db.Column(db.Integer, nullable=True)  # Par 4s + Par 5s
    gir_count = db.Column(db.Integer, nullable=True)
    penalties = db.Column(db.Integer, nullable=True)

    # Handicap
    hc_differential = db.Column(db.Float, nullable=True)

    # Status
    status = db.Column(db.String(20), default='in_progress')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    holes = db.relationship('Hole', backref='round', lazy='dynamic',
                            order_by=Hole.hole_number, cascade='all, delete-orphan')
    report = db.relationship('Report', backref='round', uselist=False, cascade='all, delete-orphan')

    def compute_totals(self):
        """Recalculate summary stats from hole data."""
        holes = self.holes.all()
        self.total_score = sum(h.score for h in holes if h.score)
        self.total_putts = sum(h.putts for h in holes if h.putts is not None)
        self.gir_count = sum(1 for h in holes if h.gir)
        self.penalties = sum(h.penalties for h in holes if h.penalties)
        fw_holes = [h for h in holes if h.par in (4, 5)]
        self.fairways_available = len(fw_holes)
        self.fairways_hit = sum(1 for h in fw_holes if h.tee_shot == 'fairway')

    def score_vs_par(self):
        if not self.total_score:
            return None
        # Prefer tee-specific par (most accurate), fall back to course par
        if self.tee_set_obj:
            return self.total_score - self.tee_set_obj.total_par
        if self.course:
            return self.total_score - self.course.par
        return None

    def compute_differential(self):
        """USGA handicap differential: (Score - Course Rating) × 113 / Slope Rating.

        For 9-hole rounds, uses front or back split ratings when available,
        falling back to half of the full-round rating.
        """
        if not (self.total_score and self.tee_set_obj):
            return
        ts = self.tee_set_obj
        if self.holes_played == 9:
            if self.nine_hole_selection == 'back':
                rating = ts.back_course_rating  or (ts.course_rating / 2)
                slope  = ts.back_slope_rating   or ts.slope_rating
            else:
                rating = ts.front_course_rating or (ts.course_rating / 2)
                slope  = ts.front_slope_rating  or ts.slope_rating
        else:
            rating = ts.course_rating
            slope  = ts.slope_rating
        diff = (self.total_score - rating) * 113 / slope
        self.hc_differential = round(diff, 1)

    def __repr__(self):
        return f'<Round {self.id} — {self.date_played}>'

from app import db
from datetime import datetime
from app.models.hole import Hole


class Round(db.Model):
    __tablename__ = 'rounds'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id   = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    tee_set_id  = db.Column(db.Integer, db.ForeignKey('tee_sets.id'), nullable=True)

    # Round metadata
    date_played         = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    holes_played        = db.Column(db.Integer, default=18)        # actual holes completed (updated at submission)
    nine_hole_selection = db.Column(db.String(10), nullable=True)  # 'front', 'back', or None
    tee_set             = db.Column(db.String(50), default='White')

    # Totals (computed after submission)
    total_score        = db.Column(db.Integer, nullable=True)
    total_putts        = db.Column(db.Integer, nullable=True)
    fairways_hit       = db.Column(db.Integer, nullable=True)
    fairways_available = db.Column(db.Integer, nullable=True)  # Par 4s + Par 5s
    gir_count          = db.Column(db.Integer, nullable=True)
    penalties          = db.Column(db.Integer, nullable=True)

    # Strokes Gained (PGA Tour baseline — Broadie methodology)
    sg_off_tee  = db.Column(db.Float, nullable=True)
    sg_approach = db.Column(db.Float, nullable=True)
    sg_atg      = db.Column(db.Float, nullable=True)   # around the green
    sg_putting  = db.Column(db.Float, nullable=True)
    sg_total    = db.Column(db.Float, nullable=True)

    # Computation version — matches CURRENT_ALGO_VERSION in app/utils/round_stats.py.
    # NULL or a lower value means stored stats are stale and need recomputing.
    algo_version = db.Column(db.Integer, nullable=True)

    # Handicap
    hc_differential        = db.Column(db.Float, nullable=True)
    counts_for_official_hc = db.Column(db.Boolean, default=True, nullable=True)

    # Status
    status       = db.Column(db.String(20), default='in_progress')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    holes  = db.relationship('Hole', backref='round', lazy='dynamic',
                             order_by=Hole.hole_number, cascade='all, delete-orphan')
    report = db.relationship('Report', backref='round', uselist=False, cascade='all, delete-orphan')

    def compute_totals(self):
        """Recalculate summary stats from actual hole data only."""
        holes                   = self.holes.all()
        self.total_score        = sum(h.score      for h in holes if h.score)
        self.total_putts        = sum(h.putts       for h in holes if h.putts      is not None)
        self.gir_count          = sum(1             for h in holes if h.gir)
        self.penalties          = sum(h.penalties   for h in holes if h.penalties)
        fw_holes                = [h for h in holes if h.par in (4, 5)]
        self.fairways_available = len(fw_holes)
        self.fairways_hit       = sum(1 for h in fw_holes if h.tee_shot == 'fairway')

    def score_vs_par(self):
        if not self.total_score:
            return None
        # Use actual hole pars stored on this round (most accurate)
        holes = self.holes.all()
        if holes:
            return self.total_score - sum(h.par for h in holes if h.par is not None)
        # Fall back to tee-set or course par
        if self.tee_set_obj:
            return self.total_score - self.tee_set_obj.total_par
        if self.course:
            return self.total_score - self.course.par
        return None

    def compute_differential(self):
        """USGA handicap differential: (Score - Course Rating) x 113 / Slope Rating.

        Uses the actual recorded hole count to determine round type:
          < 9 holes  -> clears hc_differential (no qualifying score)
          9-17 holes -> 9-hole differential using split ratings
          18 holes   -> full-round differential using complete course rating

        For 9-hole scoring, front/back is read from nine_hole_selection when set;
        otherwise inferred from the majority of actual hole numbers played.
        Split ratings fall back to half of full-round values when absent.
        """
        if not (self.total_score and self.tee_set_obj):
            return

        actual_holes = self.holes.count()

        if actual_holes < 9:
            self.hc_differential = None
            return

        ts = self.tee_set_obj

        if actual_holes == 18:
            # Complete 18-hole round - use full course rating
            rating = ts.course_rating
            slope  = ts.slope_rating
        else:
            # 9-17 holes: score as a 9-hole differential
            if self.nine_hole_selection == 'back':
                is_back = True
            elif self.nine_hole_selection == 'front':
                is_back = False
            else:
                # Infer front/back from which hole numbers were actually recorded
                nums        = [h.hole_number for h in self.holes.all()]
                back_count  = sum(1 for n in nums if n >= 10)
                front_count = sum(1 for n in nums if n <  10)
                is_back     = back_count > front_count

            if is_back:
                rating = ts.back_course_rating  or (ts.course_rating / 2)
                slope  = ts.back_slope_rating   or ts.slope_rating
            else:
                rating = ts.front_course_rating or (ts.course_rating / 2)
                slope  = ts.front_slope_rating  or ts.slope_rating

        diff = (self.total_score - rating) * 113 / slope
        self.hc_differential = round(diff, 1)

    def compute_differential_full_round(self):
        """Alias kept for backward compatibility — delegates to compute_differential."""
        self.compute_differential()

    def __repr__(self):
        return f'<Round {self.id} — {self.date_played}>'

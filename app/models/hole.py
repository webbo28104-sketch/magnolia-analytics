from app import db


class Hole(db.Model):
    __tablename__ = 'holes'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('rounds.id'), nullable=False)

    hole_number = db.Column(db.Integer, nullable=False)  # 1–18
    par = db.Column(db.Integer, nullable=False)          # 3, 4, or 5
    score = db.Column(db.Integer, nullable=False)

    # Tee shot (only meaningful on par 4s and 5s)
    tee_shot = db.Column(db.String(20), nullable=True)

    # Approach / GIR
    gir = db.Column(db.Boolean, default=False)  # Green In Regulation — auto-calculated on save

    # Approach shot
    approach_distance = db.Column(db.Integer, nullable=True)   # yards (always on par 3; on miss for par 4/5)

    # If GIR missed:
    approach_miss = db.Column(db.String(20), nullable=True)   # comma-separated: 'left,long' etc.
    lie_type      = db.Column(db.String(100), nullable=True)  # comma-separated: 'bunker,rough' etc.
    scramble_distance = db.Column(db.String(20), nullable=True)

    # Par 5 second shot
    second_shot_distance = db.Column(db.Integer, nullable=True)  # yards, par 5s only

    # Putting
    putts = db.Column(db.Integer, nullable=False, default=2)
    first_putt_distance = db.Column(db.Integer, nullable=True)  # in feet

    # Sand save (only shown when approach_miss == 'bunker')
    sand_save_attempt = db.Column(db.Boolean, nullable=True)
    sand_save_made = db.Column(db.Boolean, nullable=True)

    # Penalties
    penalties = db.Column(db.Integer, default=0)

    @property
    def score_vs_par(self):
        return self.score - self.par

    @property
    def score_label(self):
        diff = self.score_vs_par
        labels = {-3: 'Albatross', -2: 'Eagle', -1: 'Birdie',
                  0: 'Par', 1: 'Bogey', 2: 'Double', 3: 'Triple'}
        return labels.get(diff, f'+{diff}' if diff > 0 else str(diff))

    def __repr__(self):
        return f'<Hole {self.hole_number} — {self.score_label}>'

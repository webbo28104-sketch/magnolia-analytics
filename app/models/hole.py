from app import db


class Hole(db.Model):
    __tablename__ = 'holes'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('rounds.id'), nullable=False)

    hole_number = db.Column(db.Integer, nullable=False)  # 1–18
    par = db.Column(db.Integer, nullable=False)          # 3, 4, or 5
    score = db.Column(db.Integer, nullable=False)

    # Tee shot (only meaningful on par 4s and 5s)
    tee_shot = db.Column(
        db.Enum('fairway', 'left', 'right', 'penalty', name='tee_shot_result'),
        nullable=True
    )

    # Approach / GIR
    gir = db.Column(db.Boolean, default=False)  # Green In Regulation

    # If GIR missed:
    approach_miss = db.Column(
        db.Enum('left', 'right', 'short', 'long', 'bunker', name='approach_miss_dir'),
        nullable=True
    )
    scramble_distance = db.Column(
        db.Enum('fringe', '0_10', '10_20', '20_40', '40_plus', name='scramble_dist'),
        nullable=True
    )

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

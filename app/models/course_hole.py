from app import db


class CourseHole(db.Model):
    __tablename__ = 'course_holes'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    tee_set_id = db.Column(db.Integer, db.ForeignKey('tee_sets.id'), nullable=False)

    hole_number = db.Column(db.Integer, nullable=False)       # 1–18
    par = db.Column(db.Integer, nullable=False)               # 3, 4, or 5
    yardage = db.Column(db.Integer, nullable=True)
    stroke_index = db.Column(db.Integer, nullable=True)       # 1–18 (handicap allocation)

    def __repr__(self):
        return f'<CourseHole {self.hole_number} par {self.par}>'

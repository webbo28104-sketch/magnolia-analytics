"""
seed.py — Populate the database with default data.
Run once after `flask db upgrade`:
    python seed.py
"""
from app import create_app, db
from app.models.course import Course

app = create_app()

COURSES = [
    {
        'name': 'Seaford GC',
        'location': 'Seaford, East Sussex',
        'par': 68,
        'course_rating': 66.9,
        'slope_rating': 120,
        'yardage': 5884,
        'tee_set': 'White',
        # Seaford GC hole pars (9 holes x2 for 18-hole layout — adjust to actual card)
        'hole_pars': '4,4,3,4,4,3,5,4,3,4,4,3,4,4,3,5,4,3',
    },
    {
        'name': 'Royal Eastbourne GC',
        'location': 'Eastbourne, East Sussex',
        'par': 69,
        'course_rating': 68.2,
        'slope_rating': 123,
        'yardage': 6118,
        'tee_set': 'White',
        'hole_pars': '4,4,4,3,4,5,4,3,4,4,4,3,5,4,4,3,4,4',
    },
    {
        'name': 'Custom Course',
        'location': None,
        'par': 72,
        'course_rating': None,
        'slope_rating': None,
        'yardage': None,
        'tee_set': 'White',
        'hole_pars': '4,4,3,5,4,4,3,4,5,4,4,3,5,4,4,3,4,5',
    },
]

with app.app_context():
    for c in COURSES:
        existing = Course.query.filter_by(name=c['name']).first()
        if not existing:
            course = Course(**c)
            db.session.add(course)
            print(f'  Added: {c["name"]}')
        else:
            print(f'  Skipped (exists): {c["name"]}')
    db.session.commit()
    print('\nSeed complete.')

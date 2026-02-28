"""
Course API routes.

GET /api/courses/search?country=England&q=seaford
    → calls GolfCourseAPI, returns lightweight list (no caching here)

GET /api/courses/<external_id>/tees
    → checks local DB; if not cached, fetches full detail from API,
      stores Course + TeeSet + CourseHole records, then returns tees

GET /api/countries
    → static list of supported country names (no DB query needed)
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required
from app import db
from app.models.course import Course
from app.models.tee_set import TeeSet
from app.models.course_hole import CourseHole
from app.services.golfcourse_api import (
    search_courses as api_search,
    get_course_details as api_detail,
    GolfCourseAPIError,
)

courses_bp = Blueprint('courses', __name__)

SUPPORTED_COUNTRIES = [
    'England', 'Scotland', 'Wales', 'Ireland',
    'USA', 'Spain', 'France', 'Germany', 'Australia',
    'South Africa', 'Portugal', 'UAE', 'New Zealand',
    'Japan', 'Sweden', 'Denmark', 'Netherlands', 'Canada',
]


# ---------------------------------------------------------------------------
# Search — calls API live, no local caching
# ---------------------------------------------------------------------------

@courses_bp.route('/api/courses/search')
@login_required
def search_courses():
    """
    Search the GolfCourseAPI for courses.

    Query params:
        q       : free-text search (course name, town, etc.)
        country : country filter (optional)

    Returns JSON array of lightweight course objects:
        [{id, external_id, name, city, region, country, par, location}, ...]
    """
    q       = request.args.get('q', '').strip()
    country = request.args.get('country', '').strip() or None

    if not q and not country:
        return jsonify([])

    try:
        results = api_search(query=q, country=country)
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502

    return jsonify(results)


# ---------------------------------------------------------------------------
# Tees — fetch + cache on first request, serve from DB thereafter
# ---------------------------------------------------------------------------

@courses_bp.route('/api/courses/<external_id>/tees')
@login_required
def get_tees(external_id: str):
    """
    Return tee sets for a course, fetching from API and caching if needed.

    On first call for a course:
        1. Fetch full course detail from GolfCourseAPI
        2. Create Course, TeeSet, and CourseHole records in local DB
        3. Return tee data

    On subsequent calls:
        Serve directly from local DB.

    Returns JSON array:
        [{id, name, color, gender, course_rating, slope_rating,
          total_yardage, total_par, holes: [{hole_number, par, yardage, stroke_index}]}, ...]
    """
    # Check local cache first
    course = Course.query.filter_by(external_id=str(external_id)).first()

    if course:
        tees = course.tee_sets.all()
        return jsonify([_tee_to_dict(t, include_holes=True) for t in tees])

    # Not cached — fetch from API
    try:
        detail = api_detail(external_id)
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502

    # Persist course
    course = Course(
        external_id=str(external_id),
        name=detail['name'],
        country=detail.get('country', ''),
        region=detail.get('region', ''),
        city=detail.get('city', ''),
        lat=detail.get('lat'),
        lng=detail.get('lng'),
        holes=detail.get('holes', 18),
        par=detail.get('par', 72),
    )
    db.session.add(course)
    db.session.flush()  # get course.id before inserting children

    # Persist tee sets + holes
    for tee_data in detail.get('tees', []):
        ts = TeeSet(
            course_id=course.id,
            name=tee_data['name'],
            color=tee_data.get('color', ''),
            gender=tee_data.get('gender', 'M'),
            course_rating=tee_data['course_rating'],
            slope_rating=tee_data['slope_rating'],
            total_yardage=tee_data.get('total_yardage'),
            total_par=tee_data.get('total_par', 72),
        )
        db.session.add(ts)
        db.session.flush()  # get ts.id

        for hole in tee_data.get('holes', []):
            db.session.add(CourseHole(
                course_id=course.id,
                tee_set_id=ts.id,
                hole_number=hole['hole_number'],
                par=hole['par'],
                yardage=hole.get('yardage'),
                stroke_index=hole.get('stroke_index'),
            ))

    db.session.commit()

    # Return freshly cached tees
    tees = course.tee_sets.all()
    return jsonify([_tee_to_dict(t, include_holes=True) for t in tees])


# ---------------------------------------------------------------------------
# Countries list
# ---------------------------------------------------------------------------

@courses_bp.route('/api/countries')
@login_required
def get_countries():
    return jsonify(SUPPORTED_COUNTRIES)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _tee_to_dict(tee: TeeSet, include_holes: bool = False) -> dict:
    d = {
        'id':            tee.id,
        'name':          tee.name,
        'color':         tee.color or '',
        'gender':        tee.gender,
        'course_rating': tee.course_rating,
        'slope_rating':  tee.slope_rating,
        'total_yardage': tee.total_yardage,
        'total_par':     tee.total_par,
    }
    if include_holes:
        holes = tee.course_holes.order_by(CourseHole.hole_number).all()
        d['holes'] = [{
            'hole_number':  h.hole_number,
            'par':          h.par,
            'yardage':      h.yardage,
            'stroke_index': h.stroke_index,
        } for h in holes]
    return d

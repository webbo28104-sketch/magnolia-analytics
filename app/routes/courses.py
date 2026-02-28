"""
Course API routes.

GET /api/courses/search?country=England&q=seaford
    → calls GolfCourseAPI, applies client-side country filter as fallback

GET /api/courses/<external_id>/tees
    → checks local DB; if not cached, fetches + stores; returns tees
    → tees are returned even if no hole data (graceful fallback)

GET /api/debug/raw-search?q=seaford
GET /api/debug/raw-course/<id>
    → raw API JSON for debugging field mapping (dev only)
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required
from app import db
from app.models.course import Course
from app.models.tee_set import TeeSet
from app.models.course_hole import CourseHole
from app.services.golfcourse_api import (
    _get as api_get,
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
# DEBUG endpoints — see raw API response to fix field mapping
# ---------------------------------------------------------------------------

@courses_bp.route('/api/debug/raw-search')
@login_required
def debug_raw_search():
    """
    Returns the raw, unmodified JSON from GolfCourseAPI for a search query.
    Use this to inspect actual field names and structure.

    e.g. /api/debug/raw-search?q=seaford
    """
    q = request.args.get('q', 'seaford')
    try:
        raw = api_get('/courses', params={'search': q})
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify(raw)


@courses_bp.route('/api/debug/raw-course/<course_id>')
@login_required
def debug_raw_course(course_id):
    """
    Returns the raw, unmodified JSON from GolfCourseAPI for a specific course.
    Use this to inspect tee / hole field names.

    e.g. /api/debug/raw-course/12345
    """
    try:
        raw = api_get(f'/courses/{course_id}')
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502
    return jsonify(raw)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@courses_bp.route('/api/courses/search')
@login_required
def search_courses():
    q       = request.args.get('q', '').strip()
    country = request.args.get('country', '').strip() or None

    if not q:
        return jsonify([])

    try:
        results = api_search(query=q, country=country)
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502

    # Client-side country filter as fallback (in case the API ignores the param)
    if country and country.lower() not in ('', 'international'):
        results = [
            r for r in results
            if (r.get('country') or '').lower() == country.lower()
        ]

    return jsonify(results)


# ---------------------------------------------------------------------------
# Tees — fetch + cache on first request, serve from DB thereafter
# ---------------------------------------------------------------------------

@courses_bp.route('/api/courses/<external_id>/tees')
@login_required
def get_tees(external_id: str):
    """
    Return tee sets for a course. Fetches from API and caches locally on first call.

    Tees are returned even when the API provides no hole-by-hole data —
    the round can still be started and pars entered manually per hole.
    """
    # Serve from local cache if already fetched
    course = Course.query.filter_by(external_id=str(external_id)).first()
    if course:
        tees = course.tee_sets.all()
        return jsonify([_tee_to_dict(t) for t in tees])

    # Not cached — fetch from API
    try:
        detail = api_detail(external_id)
    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502

    api_tees = detail.get('tees', [])

    # Require at least one tee — if the API gave us nothing, bail clearly
    if not api_tees:
        return jsonify({
            'error': 'No tee data returned by the API for this course.',
            'hint': f'Check /api/debug/raw-course/{external_id} to inspect the raw response.'
        }), 404

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
    db.session.flush()

    for tee_data in api_tees:
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
        db.session.flush()

        holes = tee_data.get('holes', [])
        for hole in holes:
            db.session.add(CourseHole(
                course_id=course.id,
                tee_set_id=ts.id,
                hole_number=hole['hole_number'],
                par=hole['par'],
                yardage=hole.get('yardage'),
                stroke_index=hole.get('stroke_index'),
            ))

    db.session.commit()

    tees = course.tee_sets.all()
    return jsonify([_tee_to_dict(t) for t in tees])


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

def _tee_to_dict(tee: TeeSet) -> dict:
    holes = tee.course_holes.order_by(CourseHole.hole_number).all()
    return {
        'id':            tee.id,
        'name':          tee.name,
        'color':         tee.color or '',
        'gender':        tee.gender,
        'course_rating': tee.course_rating,
        'slope_rating':  tee.slope_rating,
        'total_yardage': tee.total_yardage,
        'total_par':     tee.total_par,
        'has_hole_data': len(holes) > 0,
        'holes': [{
            'hole_number':  h.hole_number,
            'par':          h.par,
            'yardage':      h.yardage,
            'stroke_index': h.stroke_index,
        } for h in holes],
    }

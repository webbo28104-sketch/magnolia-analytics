"""
Course API routes.

GET /api/courses/search?country=England&q=seaford
    -> calls GolfCourseAPI, applies client-side country filter as fallback

GET /api/courses/<external_id>/tees
    -> checks local DB; if not cached, fetches + stores; returns tees
    -> tees are returned even if no hole data (graceful fallback)

GET /api/debug/raw-search?q=seaford
GET /api/debug/raw-course/<id>
    -> raw API JSON for debugging field mapping (dev only)
"""

import logging
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
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
        raw = api_get('/search', params={'search_query': q})
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
    from rapidfuzz import fuzz as _fuzz

    q       = request.args.get('q', '').strip()
    country = request.args.get('country', '').strip() or None

    if not q:
        return jsonify([])

    try:
        results = api_search(query=q, country=country)

        # If the primary query returns few results, broaden by trimming 2 chars
        # (e.g. "foxhill" → "foxhi" finds "Foxhills"). Merge, dedup by id+name.
        if len(results) < 5 and len(q) >= 5:
            short_q = q[:max(4, len(q) - 2)]
            broader = api_search(query=short_q, country=country)
            seen = {(r.get('id'), (r.get('name') or '').lower()) for r in results}
            for r in broader:
                key = (r.get('id'), (r.get('name') or '').lower())
                if key not in seen:
                    results.append(r)
                    seen.add(key)

    except GolfCourseAPIError as e:
        return jsonify({'error': str(e)}), 502

    # Supplement with locally cached courses — catches previously searched courses
    # even when the external API misses them (ILIKE handles case-insensitivity).
    q_like = f"%{q}%"
    cached = Course.query.filter(Course.name.ilike(q_like)).limit(15).all()
    api_ids = {str(r.get('id')) for r in results if r.get('id') is not None}
    for cached_course in cached:
        ext = str(cached_course.external_id) if cached_course.external_id else None
        if ext not in api_ids:
            results.append({
                'id':      ext,
                'name':    cached_course.name,
                'city':    cached_course.city    or '',
                'region':  cached_course.region  or '',
                'country': cached_course.country or '',
                'lat':     cached_course.lat,
                'lng':     cached_course.lng,
                'holes':   cached_course.holes,
                'par':     cached_course.par,
            })
            if ext:
                api_ids.add(ext)

    # ── Country priority ──────────────────────────────────────────────────────────────
    UK_VARIANTS = {'england', 'scotland', 'wales', 'ireland',
                   'united kingdom', 'uk', 'great britain', 'northern ireland'}

    if country and country.lower() not in ('', 'international'):
        selected_lower = country.lower()
        match_set = UK_VARIANTS if selected_lower in UK_VARIANTS else {selected_lower}
    else:
        match_set = set()

    q_lower = q.lower()

    # ── Fuzzy scoring ──────────────────────────────────────────────────────────────────
    # partial_ratio handles substrings/prefixes; token_set_ratio handles word
    # reordering and extra words (e.g. "Foxhills Golf Club" vs "foxhill").
    def _score(r):
        name        = (r.get('name')    or '').lower()
        city        = (r.get('city')    or '').lower()
        region      = (r.get('region')  or '').lower()
        country_val = (r.get('country') or '').lower()

        name_sim = max(
            _fuzz.partial_ratio(q_lower, name),
            _fuzz.token_set_ratio(q_lower, name),
        )
        loc_sim = max(
            _fuzz.partial_ratio(q_lower, city),
            _fuzz.partial_ratio(q_lower, region),
        ) // 2   # location match weighted at half

        relevance     = max(name_sim, loc_sim)
        country_bonus = 1 if (match_set and country_val in match_set) else 0
        return (country_bonus, relevance)

    # Pre-compute scores once, filter results below 50% similarity, sort desc
    scored   = [(r, _score(r)) for r in results]
    filtered = [(r, s) for r, s in scored if s[1] >= 50]
    filtered.sort(key=lambda x: x[1], reverse=True)

    return jsonify([r for r, _ in filtered])


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
    current_app.logger.info(f"[tees] Fetching from API for external_id={external_id}")
    try:
        detail = api_detail(external_id)
    except GolfCourseAPIError as e:
        current_app.logger.error(f"[tees] GolfCourseAPIError for {external_id}: {e}")
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        current_app.logger.exception(f"[tees] Unexpected error fetching {external_id}")
        return jsonify({'error': 'Unexpected error fetching course data.'}), 500

    api_tees = detail.get('tees', [])
    current_app.logger.info(f"[tees] Got {len(api_tees)} tee(s) for {external_id}")

    # Require at least one tee — if the API gave us nothing, bail clearly
    if not api_tees:
        current_app.logger.warning(f"[tees] No tees returned for {external_id}. Raw detail keys: {list(detail.keys())}")
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
        current_app.logger.debug(f"[tees] Persisting tee: {tee_data.get('name')} ({tee_data.get('gender')})")
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

    try:
        db.session.commit()
        current_app.logger.info(f"[tees] Committed {len(api_tees)} tee(s) for {external_id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[tees] DB commit failed for {external_id}")
        return jsonify({'error': 'Failed to save course data. Please try again.'}), 500

    tees = course.tee_sets.all()
    return jsonify([_tee_to_dict(t) for t in tees])


# ---------------------------------------------------------------------------
# Manual course add (when course not found in API)
# ---------------------------------------------------------------------------

@courses_bp.route('/api/courses/manual', methods=['POST'])
@login_required
def add_manual_course():
    """
    Create a course + single tee set from user-supplied data.
    Returns the new tee dict so the frontend can proceed straight to step 2.
    """
    data = request.get_json(force=True, silent=True) or {}

    name          = (data.get('name') or '').strip()
    city          = (data.get('city') or '').strip()
    country       = (data.get('country') or '').strip()
    tee_name      = (data.get('tee_name') or 'Standard').strip()
    course_rating = data.get('course_rating')
    slope_rating  = data.get('slope_rating')
    total_par     = data.get('total_par', 72)

    if not name:
        return jsonify({'error': 'Course name is required.'}), 400
    if not course_rating or not slope_rating:
        return jsonify({'error': 'Course rating and slope are required.'}), 400

    try:
        course_rating = float(course_rating)
        slope_rating  = int(slope_rating)
        total_par     = int(total_par)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid rating or slope value.'}), 400

    import time
    course = Course(
        external_id=f'manual_{current_user.id}_{int(time.time())}',
        name=name,
        country=country,
        city=city,
        holes=18,
        par=total_par,
    )
    db.session.add(course)
    db.session.flush()

    ts = TeeSet(
        course_id=course.id,
        name=tee_name,
        color='',
        gender='M',
        course_rating=course_rating,
        slope_rating=slope_rating,
        total_par=total_par,
    )
    db.session.add(ts)
    db.session.commit()

    current_app.logger.info(
        f"[manual_course] Created '{name}' (course {course.id}, tee {ts.id}) "
        f"by user {current_user.id}"
    )
    return jsonify({'course': {'id': course.external_id, 'name': name, 'city': city, 'country': country},
                    'tee': _tee_to_dict(ts)})


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
        'id':                  tee.id,
        'name':                tee.name,
        'color':               tee.color or '',
        'gender':              tee.gender,
        'course_rating':       tee.course_rating,
        'slope_rating':        tee.slope_rating,
        'total_yardage':       tee.total_yardage,
        'total_par':           tee.total_par,
        # Split ratings for 9-hole rounds
        'front_course_rating': tee.front_course_rating,
        'back_course_rating':  tee.back_course_rating,
        'front_slope_rating':  tee.front_slope_rating,
        'back_slope_rating':   tee.back_slope_rating,
        'has_hole_data': len(holes) > 0,
        'holes': [{
            'hole_number':  h.hole_number,
            'par':          h.par,
            'yardage':      h.yardage,
            'stroke_index': h.stroke_index,
        } for h in holes],
    }

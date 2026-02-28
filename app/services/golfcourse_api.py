"""
GolfCourseAPI service layer.
Wraps https://api.golfcourseapi.com/v1

Authentication: Authorization: Key <GOLFCOURSE_API_KEY>

Endpoints used:
  GET /v1/courses?search=<q>&country=<c>   → list of matching courses
  GET /v1/courses/<id>                      → course detail incl. tees + holes
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = "https://api.golfcourseapi.com/v1"


class GolfCourseAPIError(Exception):
    """Raised when the GolfCourseAPI returns an error or is unreachable."""
    pass


def _api_key():
    key = os.getenv("GOLFCOURSE_API_KEY")
    if not key:
        raise GolfCourseAPIError(
            "GOLFCOURSE_API_KEY environment variable is not set."
        )
    return key


def _get(path: str, params=None):
    """Perform a GET request against the API using stdlib urllib."""
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Key {_api_key()}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8", errors="replace")
        if status == 401:
            raise GolfCourseAPIError("GolfCourseAPI: invalid or missing API key.")
        if status == 404:
            raise GolfCourseAPIError(f"GolfCourseAPI: resource not found at {path}.")
        if status == 429:
            raise GolfCourseAPIError("GolfCourseAPI: rate limit exceeded. Try again shortly.")
        raise GolfCourseAPIError(f"GolfCourseAPI error {status}: {body[:200]}")
    except urllib.error.URLError as e:
        raise GolfCourseAPIError(f"Could not connect to GolfCourseAPI: {e.reason}") from e
    except TimeoutError:
        raise GolfCourseAPIError("GolfCourseAPI request timed out.") from None

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise GolfCourseAPIError(f"GolfCourseAPI returned non-JSON response: {e}") from e


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def search_courses(query: str, country=None):
    """
    Search for courses by name/location text and optional country.

    Returns a list of lightweight course dicts, each containing at minimum:
        id, name, city, region/state, country, lat, lng, holes, par

    These are NOT cached — call get_or_cache_course() to persist to DB.
    """
    params: dict = {}
    if query:
        params["search"] = query
    if country:
        params["country"] = country

    data = _get("/courses", params=params)

    # API may return {"courses": [...]} or a plain list
    if isinstance(data, dict):
        courses = data.get("courses") or data.get("results") or data.get("data") or []
    else:
        courses = data

    return [_normalise_course_summary(c) for c in courses]


def get_course_details(course_id):
    """
    Fetch full course detail including tee sets and hole-by-hole data.

    Returns a normalised dict:
    {
        "id": <external_id>,
        "name": str,
        "city": str,
        "region": str,
        "country": str,
        "lat": float | None,
        "lng": float | None,
        "holes": int,
        "par": int,
        "tees": [
            {
                "id": <external_tee_id>,
                "name": str,
                "gender": "M" | "W" | "X",
                "course_rating": float,
                "slope_rating": int,
                "total_yardage": int | None,
                "total_par": int,
                "holes": [
                    {"hole_number": int, "par": int, "yardage": int | None, "stroke_index": int | None},
                    ...  # 18 items
                ]
            },
            ...
        ]
    }
    """
    data = _get(f"/courses/{course_id}")

    # API may wrap in an object
    if isinstance(data, dict) and "course" in data:
        data = data["course"]

    return _normalise_course_detail(data)


# ---------------------------------------------------------------------------
# Normalisation helpers
# (Field names are mapped here — update if API returns different names)
# ---------------------------------------------------------------------------

def _normalise_course_summary(raw: dict) -> dict:
    """Map raw API course summary to a consistent internal dict."""
    return {
        "id":      raw.get("id") or raw.get("course_id") or raw.get("club_id"),
        "name":    raw.get("name") or raw.get("course_name") or raw.get("club_name", "Unknown"),
        "city":    raw.get("city") or raw.get("location", {}).get("city", "") if isinstance(raw.get("location"), dict) else raw.get("city", ""),
        "region":  raw.get("state") or raw.get("region") or raw.get("county") or "",
        "country": raw.get("country") or raw.get("country_name", ""),
        "lat":     _safe_float(raw.get("latitude") or raw.get("lat")),
        "lng":     _safe_float(raw.get("longitude") or raw.get("lng") or raw.get("lon")),
        "holes":   _safe_int(raw.get("holes"), 18),
        "par":     _safe_int(raw.get("par"), 72),
    }


def _normalise_course_detail(raw: dict) -> dict:
    """Map raw API course detail to internal dict including tees + holes."""
    summary = _normalise_course_summary(raw)

    raw_tees = (
        raw.get("tees") or
        raw.get("tee_sets") or
        raw.get("scorecard") or
        []
    )

    tees = [_normalise_tee(t) for t in raw_tees]
    summary["tees"] = tees
    return summary


def _normalise_tee(raw: dict) -> dict:
    """Map a raw tee set object to internal dict."""
    raw_holes = (
        raw.get("holes") or
        raw.get("hole_data") or
        raw.get("scorecard") or
        []
    )

    # Gender: API may use "M"/"F"/"Male"/"Female"/"Mens"/"Ladies"
    gender_raw = str(raw.get("gender") or raw.get("tee_gender") or "M").upper()
    if gender_raw.startswith("F") or gender_raw.startswith("W") or "LADI" in gender_raw:
        gender = "W"
    elif gender_raw.startswith("X") or "MIX" in gender_raw:
        gender = "X"
    else:
        gender = "M"

    return {
        "id":             raw.get("id") or raw.get("tee_id"),
        "name":           raw.get("name") or raw.get("tee_name") or raw.get("tee_colour") or "Standard",
        "color":          (raw.get("colour") or raw.get("color") or raw.get("tee_colour") or "").lower(),
        "gender":         gender,
        "course_rating":  _safe_float(raw.get("course_rating") or raw.get("rating") or raw.get("courseRating"), 72.0),
        "slope_rating":   _safe_int(raw.get("slope_rating") or raw.get("slope") or raw.get("slopeRating"), 113),
        "total_yardage":  _safe_int(raw.get("total_yards") or raw.get("yardage") or raw.get("total_yardage")),
        "total_par":      _safe_int(raw.get("par") or raw.get("total_par"), 72),
        "holes":          [_normalise_hole(h) for h in raw_holes],
    }


def _normalise_hole(raw: dict) -> dict:
    """Map a raw hole object to internal dict."""
    return {
        "hole_number":  _safe_int(raw.get("hole_number") or raw.get("hole") or raw.get("number"), 0),
        "par":          _safe_int(raw.get("par"), 4),
        "yardage":      _safe_int(raw.get("yards") or raw.get("yardage") or raw.get("distance")),
        "stroke_index": _safe_int(raw.get("stroke_index") or raw.get("handicap") or raw.get("si")),
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_float(val, default=None):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=None):
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default

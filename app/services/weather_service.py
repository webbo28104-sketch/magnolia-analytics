"""
Weather data for round reports.

Uses the Open-Meteo archive API — free, no API key required.
Fetches historical hourly weather for the course location on the date played,
then picks the midday (12:00) snapshot as representative of the round.

Result is cached in Report.weather_json so we only call the API once per round.
A sentinel value of "null" is stored when the fetch fails or the course has no
coordinates — this prevents retrying on every page load.
"""

import json
import logging
import urllib.request
import urllib.parse
from datetime import date as date_type

logger = logging.getLogger(__name__)

# Sentinel stored in weather_json when weather is unavailable — prevents
# re-fetching on every page load for courses without lat/lng.
_WEATHER_UNAVAILABLE = 'null'

# ---------------------------------------------------------------------------
# WMO Weather Interpretation Codes → human-readable label
# ---------------------------------------------------------------------------
_WMO_CONDITIONS = {
    0:  'Clear sky',
    1:  'Mainly clear',
    2:  'Partly cloudy',
    3:  'Overcast',
    45: 'Foggy',
    48: 'Icy fog',
    51: 'Light drizzle',
    53: 'Drizzle',
    55: 'Heavy drizzle',
    56: 'Freezing drizzle',
    57: 'Heavy freezing drizzle',
    61: 'Light rain',
    63: 'Rain',
    65: 'Heavy rain',
    66: 'Freezing rain',
    67: 'Heavy freezing rain',
    71: 'Light snow',
    73: 'Snow',
    75: 'Heavy snow',
    77: 'Snow grains',
    80: 'Light showers',
    81: 'Showers',
    82: 'Heavy showers',
    85: 'Snow showers',
    86: 'Heavy snow showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm with hail',
    99: 'Thunderstorm with heavy hail',
}


def _wmo_label(code) -> str:
    if code is None:
        return 'Unknown'
    return _WMO_CONDITIONS.get(int(code), f'Code {code}')


def fetch_weather(lat: float, lng: float, date_played: date_type):
    """
    Fetch hourly weather from Open-Meteo archive API for a given location
    and date. Returns the midday (12:00) snapshot, or None on any failure.

    Return dict shape:
        {
            "temp_c":    float,
            "wind_kph":  float,
            "precip_mm": float,
            "condition": str,
        }
    """
    if lat is None or lng is None:
        logger.warning('fetch_weather: lat/lng not available, skipping')
        return None

    date_str = date_played.strftime('%Y-%m-%d')

    params = urllib.parse.urlencode({
        'latitude':        lat,
        'longitude':       lng,
        'start_date':      date_str,
        'end_date':        date_str,
        'hourly':          'temperature_2m,precipitation,windspeed_10m,weathercode',
        'wind_speed_unit': 'kmh',
        'timezone':        'auto',
    })
    url = f'https://archive-api.open-meteo.com/v1/archive?{params}'

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MagnoliaAnalytics/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        hourly = data.get('hourly', {})
        times  = hourly.get('time', [])

        if not times:
            logger.warning('fetch_weather: API returned no time data for %s', date_str)
            return None

        target = date_str + 'T12:00'
        idx    = next((i for i, t in enumerate(times) if t == target), None)
        if idx is None:
            idx = len(times) // 2   # fallback: midpoint of the day
            logger.info('fetch_weather: 12:00 slot not found, using idx=%d', idx)

        weather = {
            'temp_c':    round(float(hourly['temperature_2m'][idx]), 1),
            'wind_kph':  round(float(hourly['windspeed_10m'][idx]), 1),
            'precip_mm': round(float(hourly['precipitation'][idx]), 1),
            'condition': _wmo_label(hourly['weathercode'][idx]),
        }
        logger.info('fetch_weather: success — %s', weather)
        return weather

    except Exception as exc:
        logger.warning('fetch_weather: failed for lat=%s lng=%s date=%s — %s',
                       lat, lng, date_str, exc)
        return None


def get_round_weather(round_):
    """
    Return weather dict for the given round.

    Checks Report.weather_json first (cached). If the sentinel 'null' is
    stored, the course has no coordinates and we skip the fetch.
    If empty, fetches from Open-Meteo and persists the result (or sentinel).

    Callers must commit the DB session after calling this function.
    """
    report = round_.report
    course = round_.course

    # --- serve from cache ---
    if report and report.weather_json:
        if report.weather_json == _WEATHER_UNAVAILABLE:
            # Re-check: course may have acquired coordinates since sentinel was set.
            # If coords are now present, clear the sentinel and re-fetch.
            _lat = getattr(round_.course, 'lat', None) if round_.course else None
            _lng = getattr(round_.course, 'lng', None) if round_.course else None
            if not _lat or not _lng:
                return None   # still no coordinates — skip
            report.weather_json = None  # clear sentinel; fall through to fetch
        else:
            try:
                return json.loads(report.weather_json)
            except (json.JSONDecodeError, TypeError):
                pass  # corrupted — fall through and re-fetch

    # --- check for coordinates ---
    lat = getattr(course, 'lat', None) if course else None
    lng = getattr(course, 'lng', None) if course else None

    if not course:
        logger.warning('get_round_weather: round %s has no course', round_.id)
        _cache_sentinel(report)
        return None

    if lat is None or lng is None:
        logger.warning(
            'get_round_weather: course "%s" has no lat/lng — weather unavailable',
            course.name,
        )
        _cache_sentinel(report)
        return None

    # --- fetch from API ---
    weather = fetch_weather(lat, lng, round_.date_played)

    # --- cache result (or sentinel on failure) ---
    if report:
        if weather:
            report.weather_json = json.dumps(weather)
        else:
            _cache_sentinel(report)

    return weather


def _cache_sentinel(report) -> None:
    """Store the unavailable sentinel to prevent repeated failed fetches."""
    if report:
        report.weather_json = _WEATHER_UNAVAILABLE

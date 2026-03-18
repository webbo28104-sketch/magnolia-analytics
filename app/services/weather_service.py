"""
Weather data for round reports.

Uses the Open-Meteo archive API — free, no API key required.
Fetches historical hourly weather for the course location on the date played,
then picks the midday (12:00) snapshot as representative of the round.

Result is cached in Report.weather_json so we only call the API once per round.
"""

import json
import urllib.request
import urllib.parse
from datetime import date as date_type


# ---------------------------------------------------------------------------
# WMO Weather Interpretation Codes → human-readable label
# https://open-meteo.com/en/docs#weathervariables
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


def fetch_weather(lat: float, lng: float, date_played: date_type) -> dict | None:
    """
    Fetch hourly weather from Open-Meteo archive API for a given location
    and date. Returns the midday (12:00) snapshot, or None on any failure.

    Return dict shape:
        {
            "temp_c":    float,   # temperature at 12:00
            "wind_kph":  float,   # wind speed at 12:00
            "precip_mm": float,   # precipitation at 12:00
            "condition": str,     # human-readable WMO label
        }
    """
    if lat is None or lng is None:
        return None

    date_str = date_played.strftime('%Y-%m-%d')

    params = urllib.parse.urlencode({
        'latitude':            lat,
        'longitude':           lng,
        'start_date':          date_str,
        'end_date':            date_str,
        'hourly':              'temperature_2m,precipitation,windspeed_10m,weathercode',
        'wind_speed_unit':     'kmh',
        'timezone':            'auto',
    })
    url = f'https://archive-api.open-meteo.com/v1/archive?{params}'

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MagnoliaAnalytics/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        hourly = data.get('hourly', {})
        times  = hourly.get('time', [])

        # Find the 12:00 slot (or closest available)
        target = date_str + 'T12:00'
        idx = next((i for i, t in enumerate(times) if t == target), None)
        if idx is None and times:
            idx = len(times) // 2   # fallback: midpoint of the day

        if idx is None:
            return None

        return {
            'temp_c':    round(hourly['temperature_2m'][idx], 1),
            'wind_kph':  round(hourly['windspeed_10m'][idx], 1),
            'precip_mm': round(hourly['precipitation'][idx], 1),
            'condition': _wmo_label(hourly['weathercode'][idx]),
        }

    except Exception:
        return None


def get_round_weather(round_) -> dict | None:
    """
    Return weather dict for the given round.

    Checks Report.weather_json first (cached). If empty, fetches from
    Open-Meteo and persists the result back to the report row.

    Callers must commit the DB session after calling this function if they
    want the cache to persist (the route handler does this).
    """
    from app import db  # avoid circular import at module level

    report = round_.report
    course = round_.course

    # --- serve from cache if available ---
    if report and report.weather_json:
        try:
            return json.loads(report.weather_json)
        except (json.JSONDecodeError, TypeError):
            pass  # corrupted cache — fall through and re-fetch

    # --- fetch from API ---
    if not course or course.lat is None or course.lng is None:
        return None

    weather = fetch_weather(course.lat, course.lng, round_.date_played)

    # --- cache result on the report row ---
    if weather and report:
        report.weather_json = json.dumps(weather)
        # Caller is responsible for db.session.commit()

    return weather

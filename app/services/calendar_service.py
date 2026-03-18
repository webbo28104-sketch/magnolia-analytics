"""
Calendar context for round reports.

Provides human-readable context for the date a round was played:
  - Proximity to a UK bank holiday (±2 days)
  - Proximity to a major golf event (±2 days)
  - A notable personal/cultural date (±2 days, exact match)
  - Season label

UK bank holidays are fetched from the gov.uk API (England & Wales division)
and cached in memory for the process lifetime. Falls back to a hardcoded
2025/2026 list if the API is unavailable.
"""

import json
import urllib.request
from datetime import date, timedelta
from functools import lru_cache


# ---------------------------------------------------------------------------
# UK Bank Holidays fallback (England & Wales, 2025–2026)
# ---------------------------------------------------------------------------
_FALLBACK_BANK_HOLIDAYS = [
    date(2025, 1, 1),   # New Year's Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 4, 21),  # Easter Monday
    date(2025, 5, 5),   # Early May bank holiday
    date(2025, 5, 26),  # Spring bank holiday
    date(2025, 8, 25),  # Summer bank holiday
    date(2025, 12, 25), # Christmas Day
    date(2025, 12, 26), # Boxing Day
    date(2026, 1, 1),   # New Year's Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 6),   # Easter Monday
    date(2026, 5, 4),   # Early May bank holiday
    date(2026, 5, 25),  # Spring bank holiday
    date(2026, 8, 31),  # Summer bank holiday
    date(2026, 12, 25), # Christmas Day
    date(2026, 12, 28), # Boxing Day (substitute)
]

_FALLBACK_BANK_HOLIDAY_NAMES = {
    date(2025, 1, 1):   "New Year's Day",
    date(2025, 4, 18):  "Good Friday",
    date(2025, 4, 21):  "Easter Monday",
    date(2025, 5, 5):   "May Bank Holiday",
    date(2025, 5, 26):  "Spring Bank Holiday",
    date(2025, 8, 25):  "August Bank Holiday",
    date(2025, 12, 25): "Christmas Day",
    date(2025, 12, 26): "Boxing Day",
    date(2026, 1, 1):   "New Year's Day",
    date(2026, 4, 3):   "Good Friday",
    date(2026, 4, 6):   "Easter Monday",
    date(2026, 5, 4):   "May Bank Holiday",
    date(2026, 5, 25):  "Spring Bank Holiday",
    date(2026, 8, 31):  "August Bank Holiday",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 28): "Boxing Day",
}


# ---------------------------------------------------------------------------
# Major golf events 2025/2026
# (start_date, end_date inclusive)
# ---------------------------------------------------------------------------
_GOLF_EVENTS = {
    # 2025
    "The Masters 2025":           (date(2025, 4, 10), date(2025, 4, 13)),
    "US PGA Championship 2025":   (date(2025, 5, 15), date(2025, 5, 18)),
    "US Open 2025":               (date(2025, 6, 12), date(2025, 6, 15)),
    "The Open Championship 2025": (date(2025, 7, 17), date(2025, 7, 20)),
    "Ryder Cup 2025":             (date(2025, 9, 26), date(2025, 9, 28)),
    # 2026
    "The Masters 2026":           (date(2026, 4, 9),  date(2026, 4, 12)),
    "US PGA Championship 2026":   (date(2026, 5, 14), date(2026, 5, 17)),
    "US Open 2026":               (date(2026, 6, 18), date(2026, 6, 21)),
    "The Open Championship 2026": (date(2026, 7, 16), date(2026, 7, 19)),
}


# ---------------------------------------------------------------------------
# Notable personal / cultural dates (month, day) → label
# Checked as exact month/day match only (year-independent)
# ---------------------------------------------------------------------------
_NOTABLE_DATES = {
    (1,  1):  "New Year's Day",
    (2,  14): "Valentine's Day",
    (3,  17): "St Patrick's Day",
    (4,  1):  "April Fools' Day",
    (6,  21): "Summer Solstice",
    (10, 31): "Halloween",
    (11, 5):  "Bonfire Night",
    (12, 24): "Christmas Eve",
    (12, 25): "Christmas Day",
    (12, 26): "Boxing Day",
    (12, 31): "New Year's Eve",
}


# ---------------------------------------------------------------------------
# Season labels (Northern Hemisphere / UK golf calendar)
# ---------------------------------------------------------------------------
def _season_label(d: date) -> str:
    m = d.month
    if m in (12, 1, 2):
        return "Winter Golf"
    if m in (3,):
        return "Early Season"
    if m in (4, 5):
        return "Spring Season"
    if m in (6, 7, 8):
        return "Summer Season"
    if m in (9, 10):
        return "Autumn Season"
    return "Late Season"  # November


# ---------------------------------------------------------------------------
# UK Bank Holidays API fetch (cached per process)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _fetch_uk_bank_holidays() -> dict:
    """
    Returns a dict: {date_obj: name_str} for England & Wales.
    Fetches from gov.uk once and caches indefinitely.
    Falls back to hardcoded list on any error.
    """
    try:
        url = 'https://www.gov.uk/bank-holidays.json'
        req = urllib.request.Request(url, headers={'User-Agent': 'MagnoliaAnalytics/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        events = data.get('england-and-wales', {}).get('events', [])
        return {
            date.fromisoformat(e['date']): e['title']
            for e in events
        }
    except Exception:
        return _FALLBACK_BANK_HOLIDAY_NAMES.copy()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_calendar_context(date_played: date) -> dict:
    """
    Return a dict of calendar context for the given date:

        {
            "bank_holiday": str | None,   # name of nearby UK bank holiday
            "golf_event":   str | None,   # name of nearby major golf event
            "notable":      str | None,   # notable cultural/personal date
            "season":       str,          # e.g. "Summer Season"
        }

    "Nearby" means within ±2 days for bank holidays and golf events,
    and exact month/day match for notable dates.
    """
    WINDOW = 2  # days either side

    bank_holiday = None
    golf_event   = None
    notable      = None

    # --- UK bank holidays ---
    bh_map = _fetch_uk_bank_holidays()
    for delta in range(-WINDOW, WINDOW + 1):
        candidate = date_played + timedelta(days=delta)
        if candidate in bh_map:
            name = bh_map[candidate]
            if delta == 0:
                bank_holiday = name
            elif delta < 0:
                bank_holiday = f"{name} weekend"
            else:
                bank_holiday = f"Post-{name}"
            break

    # --- Major golf events ---
    for event_name, (start, end) in _GOLF_EVENTS.items():
        # Expand window around the event dates
        window_start = start - timedelta(days=WINDOW)
        window_end   = end   + timedelta(days=WINDOW)
        if window_start <= date_played <= window_end:
            if start <= date_played <= end:
                golf_event = f"During {event_name}"
            elif date_played < start:
                days_to = (start - date_played).days
                golf_event = f"{event_name} starts in {days_to} day{'s' if days_to != 1 else ''}"
            else:
                days_since = (date_played - end).days
                golf_event = f"{days_since} day{'s' if days_since != 1 else ''} after {event_name}"
            break

    # --- Notable dates (exact month/day) ---
    key = (date_played.month, date_played.day)
    notable = _NOTABLE_DATES.get(key)

    return {
        'bank_holiday': bank_holiday,
        'golf_event':   golf_event,
        'notable':      notable,
        'season':       _season_label(date_played),
    }

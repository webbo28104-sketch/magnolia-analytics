"""
Club catalogue for My Bag and per-shot club tracking.

Club keys are short, stable strings stored in shots_json ('D', '3W', '4H',
'7i', 'PW', '56', 'P'). Degree wedges are stored as the loft number only.
"""

CLUB_GROUPS = [
    ('Woods',   ['D', '3W', '4W', '5W', '7W', '9W']),
    ('Hybrids', ['2H', '3H', '4H', '5H', '6H']),
    ('Irons',   ['2i', '3i', '4i', '5i', '6i', '7i', '8i', '9i']),
    ('Wedges',  ['PW', '46', '48', '50', '52', '54', '56', '58', '60', '62', '64']),
    ('Putter',  ['P']),
]

ALL_CLUBS = [c for _, clubs in CLUB_GROUPS for c in clubs]
_ORDER = {c: i for i, c in enumerate(ALL_CLUBS)}

MAX_BAG_SIZE = 14


def is_valid_club(key) -> bool:
    return key in _ORDER


def club_label(key) -> str:
    """Short display label: 'D', '3W', '7i', 'PW', '56°', 'P'."""
    if key is None:
        return ''
    if key.isdigit():
        return f'{key}°'
    return key


def club_name(key) -> str:
    """Long display name: 'Driver', '3 wood', '7 iron', '56° wedge'."""
    if key is None:
        return ''
    if key == 'D':
        return 'Driver'
    if key == 'P':
        return 'Putter'
    if key == 'PW':
        return 'Pitching wedge'
    if key.isdigit():
        return f'{key}° wedge'
    num, kind = key[:-1], key[-1]
    return f'{num} ' + {'W': 'wood', 'H': 'hybrid', 'i': 'iron'}.get(kind, '')


def sort_clubs(keys) -> list:
    """Sort club keys longest club first; unknown keys go last."""
    return sorted(keys, key=lambda k: _ORDER.get(k, 999))


def clean_bag(keys) -> list:
    """Validate, de-duplicate and order a submitted bag (max 14 clubs)."""
    seen = []
    for k in keys or []:
        if is_valid_club(k) and k not in seen:
            seen.append(k)
    return sort_clubs(seen)[:MAX_BAG_SIZE]

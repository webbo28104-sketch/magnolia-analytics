"""
England Golf (WHS platform) client — logs in as the golfer, with their permission,
and reads their Handicap Index and scoring record.

The members site (members.whsplatform.englandgolf.org) is an ASP.NET WebForms app:
GET the login page for __VIEWSTATE/__EVENTVALIDATION, then POST membership number
+ password. Login is judged failed if the response still shows the password field.

Credentials are encrypted at rest with Fernet; the key lives only in the
EG_CRED_KEY environment variable.
"""

import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet, InvalidToken

BASE = 'https://members.whsplatform.englandgolf.org'
LOGIN_URL = BASE + '/igolf-login'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
TIMEOUT = 20



class EGError(Exception):
    """Raised with a message that is safe to show the golfer."""


# ── Credential encryption ────────────────────────────────────────────────────

def _fernet():
    key = os.environ.get('EG_CRED_KEY')
    if not key:
        raise EGError('England Golf connection is not configured on the server yet.')
    return Fernet(key.encode())


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise EGError('Saved England Golf password could not be read. Please reconnect.')


# ── Session ──────────────────────────────────────────────────────────────────

def _form_fields(soup):
    fields = {}
    for inp in soup.select('form input'):
        name = inp.get('name')
        if not name or inp.get('type') in ('submit', 'checkbox', 'button'):
            continue
        fields[name] = inp.get('value', '')
    return fields


def login(member_no: str, password: str) -> tuple:
    """Return (requests.Session, landing_html). Raises EGError on failure."""
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'en-GB,en;q=0.9'})
    try:
        r = s.get(LOGIN_URL, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException:
        raise EGError('Could not reach England Golf. Try again later.')

    soup = BeautifulSoup(r.text, 'html.parser')
    form = soup.find('form')
    user_inp = soup.find('input', attrs={'name': re.compile(r'tbMembershipNumber$')})
    pass_inp = soup.find('input', attrs={'name': re.compile(r'tbPassword$')})
    btn = soup.find('input', attrs={'name': re.compile(r'btnLogin$')})
    if not (form and user_inp and pass_inp and btn):
        raise EGError('England Golf changed their login page; the sync needs updating.')

    data = _form_fields(soup)
    data[user_inp['name']] = member_no
    data[pass_inp['name']] = password
    data[btn['name']] = btn.get('value', 'Login')
    action = urljoin(r.url, form.get('action') or r.url)
    try:
        r2 = s.post(action, data=data, timeout=TIMEOUT, headers={'Referer': r.url})
    except requests.RequestException:
        raise EGError('Could not reach England Golf. Try again later.')

    soup2 = BeautifulSoup(r2.text, 'html.parser')
    if soup2.find('input', attrs={'name': re.compile(r'tbPassword$')}):
        msg = soup2.select_one('.alert, .validation-summary-errors, .error, [id$="lblError"], [id$="lblMessage"]')
        text = msg.get_text(' ', strip=True) if msg else ''
        raise EGError('England Golf rejected the login'
                      + (f': {text[:160]}' if text else '. Check your membership number and password.'))
    return s, r2.text, r2.url


# ── Parsing ──────────────────────────────────────────────────────────────────

_HI_RE = re.compile(r'Handicap\s*Index[^0-9+\-]{0,80}?([+]?\d{1,2}\.\d)', re.I | re.S)


def parse_handicap_index(html: str):
    """Best-effort Handicap Index from any page that shows it (plus handicaps as negatives)."""
    text = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
    m = _HI_RE.search(text)
    if not m:
        return None
    raw = m.group(1)
    return -float(raw[1:]) if raw.startswith('+') else float(raw)


_DATE_RE = re.compile(r'\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b')


def parse_score_rows(html: str) -> list:
    """
    Best-effort scoring record: any table row with a date plus numbers.
    Returns [{'date': 'YYYY-MM-DD', 'cells': [...]}] keeping raw cells, so nothing
    is lost while the exact column layout is confirmed.
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for tr in soup.select('table tr'):
        cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td', 'th'])]
        joined = ' | '.join(cells)
        m = _DATE_RE.search(joined)
        if not m or not any(re.fullmatch(r'\d{2,3}', c) for c in cells):
            continue
        d, mth, y = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            date = datetime(y, int(mth), int(d)).date().isoformat()
        except ValueError:
            continue
        rows.append({'date': date, 'cells': cells})
    return rows


# ── JSON API (what the My Overview page calls after login) ───────────────────

def _post_json(s, path, payload):
    r = s.post(BASE + path, json=payload, timeout=TIMEOUT,
               headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': BASE + '/my-overview'})
    r.raise_for_status()
    return r.json()


def _parse_index_text(text):
    if text is None:
        return None
    m = re.search(r'([+]?)\s*(\d{1,2}(?:\.\d)?)', str(text))
    if not m:
        return None
    v = float(m.group(2))
    return -v if m.group(1) == '+' else v


_MS_DATE = re.compile(r'/Date\((-?\d+)')


def _iso_date(v):
    if not v:
        return None
    m = _MS_DATE.search(str(v))
    if m:
        return datetime.utcfromtimestamp(int(m.group(1)) / 1000).date().isoformat()
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(v))
    if m:
        return '-'.join(m.groups())
    m = _DATE_RE.search(str(v))
    if m:
        d, mth, y = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        return f'{y:04d}-{int(mth):02d}-{int(d):02d}'
    return None


def _first(item, *keys):
    for k in keys:
        if item.get(k) not in (None, '', 0):
            return item[k]
    return None


def _score_row(item):
    """Normalise one GetMyScores item; keeps the scalar fields in 'raw'."""
    raw = {k: v for k, v in item.items()
           if not isinstance(v, (dict, list)) and v not in (None, '')
           and not re.match(r'Hole\d+(Score|Par|Distance|Fairway|GIR|Putts)', k)}
    holes = []
    for n in range(1, 19):
        sc = item.get(f'Hole{n}Score')
        if sc:
            holes.append({'n': n, 'score': sc, 'par': item.get(f'Hole{n}Par'),
                          'yds': item.get(f'Hole{n}Distance')})
    nine = item.get('IsNineHole')
    row = {
        'date': _iso_date(_first(item, 'PlayDate', 'DatePlayed', 'CaptureDate')),
        'course': _first(item, 'CourseName', 'FacilityName', 'ClubName'),
        'tees': item.get('Marker'),
        'adj_gross': _first(item, 'AdjustedGross', 'AdjustedGrossScore'),
        'stableford': item.get('StablefordPoints'),
        'differential': _first(item, 'HCDiff', 'ScoreDifferential'),
        'course_rating': item.get('CourseRating'),
        'slope': item.get('Slope'),
        'course_handicap': item.get('CourseHandicap'),
        'index_at_time': item.get('HandicapIndex'),
        'holes': 9 if nine else (18 if nine is False else len(holes) or None),
        'counted': bool(item.get('CountedInHandicap')),
        'competition': bool(item.get('IsCompetitionScore')),
        'raw': raw,
    }
    if holes:
        row['hole_scores'] = holes
    course = ' · '.join(str(x) for x in (row['course'], row['tees'] and f"{row['tees']} tees",
                                          row['holes'] == 9 and '9 holes') if x)
    row['cells'] = [x for x in (course,
                                row['adj_gross'] and f"Adj gross {row['adj_gross']}",
                                row['stableford'] is not None and f"{row['stableford']} pts",
                                row['differential'] and f"Differential {row['differential']}",
                                row['counted'] and 'counts towards index') if x]
    return row


def sync(member_no: str, password: str) -> dict:
    """
    Log in, then call the same JSON endpoints the My Overview page uses. Returns
    {'handicap_index', 'low_index', 'scores', 'pages': [(label, url, text)]}.
    """
    s, html, url = login(member_no, password)
    pages = [('Landing', url, html)]

    hi = low = None
    try:
        h = _post_json(s, '/api/Score/GetMemberHandicapIndex',
                       {'OtherPassportId': None, 'OtherPassportMemberCode': None})
        hi = _parse_index_text(h.get('HandicapIndexText'))
        low = _parse_index_text(h.get('LowHandicapIndexText'))
        pages.append(('API GetMemberHandicapIndex', '', json.dumps(h)[:4000]))
    except (requests.RequestException, ValueError) as e:
        pages.append(('API GetMemberHandicapIndex', '', f'failed: {e}'))

    scores = []
    try:
        for page in range(1, 6):
            d = _post_json(s, '/api/Score/GetMyScores', {
                'pageNumber': page, 'pageSize': 100, 'dateString': None, 'otherPassportId': None,
                'includeCasualScores': True, 'getDefaultFacility': True, 'facilityTypeUID': None,
                'noOfHoles': None, 'casualScoresOnly': False})
            items = d.get('Scores') or []
            if page == 1:
                sample = {k: v for k, v in d.items() if k != 'Scores'}
                sample['Scores[0]'] = items[0] if items else None
                pages.append(('API GetMyScores', '', json.dumps(sample, default=str)[:12000]))
            scores.extend(_score_row(it) for it in items)
            if len(items) < 100:
                break
    except (requests.RequestException, ValueError) as e:
        pages.append(('API GetMyScores', '', f'failed: {e}'))

    if hi is None:
        hi = parse_handicap_index(html)
    scores.sort(key=lambda r: r['date'] or '', reverse=True)
    return {'handicap_index': hi, 'low_index': low, 'scores': scores, 'pages': pages}

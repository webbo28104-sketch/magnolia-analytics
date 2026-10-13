"""
England Golf (WHS platform) client — logs in as the golfer, with their permission,
and reads their Handicap Index and scoring record.

The members site (members.whsplatform.englandgolf.org) is an ASP.NET WebForms app:
GET the login page for __VIEWSTATE/__EVENTVALIDATION, then POST membership number
+ password. Login is judged failed if the response still shows the password field.

Credentials are encrypted at rest with Fernet; the key lives only in the
EG_CRED_KEY environment variable.
"""

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

# Pages worth reading after login, matched against link text / href
PAGE_HINTS = ('handicap', 'record', 'score', 'dashboard', 'profile', 'my golf')


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


def _candidate_links(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    seen, out = set(), []
    for a in soup.find_all('a', href=True):
        href = urljoin(base_url, a['href'])
        label = a.get_text(' ', strip=True)
        if not href.startswith(BASE) or href in seen:
            continue
        if 'logout' in href.lower() or 'log out' in label.lower():
            continue
        if any(h in (label + ' ' + href).lower() for h in PAGE_HINTS):
            seen.add(href)
            out.append((label, href))
    return out[:8]


def sync(member_no: str, password: str) -> dict:
    """
    Log in and read handicap + scores. Returns
    {'handicap_index', 'scores', 'pages': [(label, url, html)]}.
    """
    s, html, url = login(member_no, password)
    pages = [('Landing', url, html)]
    for label, href in _candidate_links(html, url):
        try:
            r = s.get(href, timeout=TIMEOUT)
            if r.ok:
                pages.append((label, r.url, r.text))
        except requests.RequestException:
            continue

    hi = None
    scores, seen = [], set()
    for _, _, p in pages:
        if hi is None:
            hi = parse_handicap_index(p)
        for row in parse_score_rows(p):
            sig = (row['date'], tuple(row['cells']))
            if sig not in seen:
                seen.add(sig)
                scores.append(row)
    scores.sort(key=lambda r: r['date'], reverse=True)
    return {'handicap_index': hi, 'scores': scores, 'pages': pages}

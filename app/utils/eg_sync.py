"""Run an England Golf sync for one user and store the result on the user row."""

import json
from datetime import datetime

from bs4 import BeautifulSoup

from app import db
from app.utils import england_golf as eg

PAGES_TEXT_LIMIT = 60_000


def _pages_text(pages):
    parts = []
    for label, url, html in pages:
        soup = BeautifulSoup(html, 'html.parser')
        for t in soup(['script', 'style', 'noscript']):
            t.decompose()
        parts.append(f'=== {label} — {url}\n{soup.get_text(chr(10), strip=True)}')
    return '\n\n'.join(parts)[:PAGES_TEXT_LIMIT]


def sync_user(user) -> bool:
    """Sync and commit. Returns True on success; failures are stored in user.eg_error."""
    if not (user.eg_member_no and user.eg_password_enc):
        return False
    try:
        result = eg.sync(user.eg_member_no, eg.decrypt(user.eg_password_enc))
    except eg.EGError as e:
        user.eg_status, user.eg_error = 'error', str(e)[:300]
        db.session.commit()
        return False
    except Exception:
        user.eg_status, user.eg_error = 'error', 'Unexpected error while syncing with England Golf.'
        db.session.commit()
        raise
    user.eg_status, user.eg_error = 'connected', None
    user.eg_last_sync = datetime.utcnow()
    if result['handicap_index'] is not None:
        user.eg_handicap_index = result['handicap_index']
    user.eg_scores_json = json.dumps(result['scores'][:200])
    user.eg_pages_text = _pages_text(result['pages'])
    db.session.commit()
    return True

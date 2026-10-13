"""Run an England Golf sync for one user and store the result on the user row."""

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from app import db
from app.utils import england_golf as eg

PAGES_TEXT_LIMIT = 120_000


def _pages_text(pages):
    parts = []
    for label, url, html in pages:
        soup = BeautifulSoup(html, 'html.parser')
        # Data on these pages loads via script calls; keep the lines that name endpoints
        calls = []
        for sc in soup.find_all('script'):
            if sc.get('src'):
                calls.append('src ' + sc['src'])
            for line in (sc.string or '').splitlines():
                if re.search(r'asmx|ashx|/api/|url\s*:|\$\.(ajax|get|post|getJSON)|fetch\(', line):
                    calls.append(line.strip()[:300])
        if calls:
            parts.append(f'=== SCRIPTS {label}\n' + '\n'.join(dict.fromkeys(calls)))
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

    from app.routes.rounds import _recalculate_handicap
    from app.utils.eg_match import reconcile
    reconcile(user, result['scores'])
    _recalculate_handicap(user)
    return True

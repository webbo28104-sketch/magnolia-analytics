"""
My Bag: pick the 14 clubs in the bag, switch club logging on for shot entry,
and see distance gapping and strokes gained per club from logged shots.
"""

import json

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.utils.access import is_pro
from app.utils.clubs import CLUB_GROUPS, MAX_BAG_SIZE, clean_bag, club_label, club_name, sort_clubs
from app.utils.round_history import history
from app.utils.club_stats import club_profiles

bag_bp = Blueprint('bag', __name__)

GAP_ROUNDS = 20


def _gap_notes(rows):
    """Plain-language notes on overlapping or wide gaps between neighbouring clubs."""
    notes = []
    with_avg = [r for r in rows if r['avg'] and r['n'] >= 3]
    for a, b in zip(with_avg, with_avg[1:]):
        gap = a['avg'] - b['avg']
        if a['lo'] is not None and b['hi'] is not None and b['hi'] > a['lo']:
            notes.append(f"Your {a['label']} and {b['label']} overlap by {b['hi'] - a['lo']} yds.")
        elif gap >= 20:
            notes.append(f"{gap} yds between your {a['label']} and {b['label']}, the widest gap in the bag.")
    return notes[:3]


@bag_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        clubs = request.form.getlist('clubs')
        cleaned = clean_bag(clubs)
        if len(set(clubs)) > MAX_BAG_SIZE:
            flash(f'A bag holds {MAX_BAG_SIZE} clubs, so only the first {MAX_BAG_SIZE} were kept.', 'info')
        current_user.bag_json = json.dumps(cleaned)
        current_user.track_clubs = request.form.get('track_clubs') == 'on'
        db.session.commit()
        flash('Bag saved.', 'success')
        return redirect(url_for('bag.index'))

    bag = current_user.bag
    _, datas, shots = history(current_user.id, limit=GAP_ROUNDS)
    profiles = club_profiles(shots)
    pro = is_pro(current_user)

    shown = sort_clubs(set(bag) | {c for c in profiles if profiles[c]['n'] or profiles[c]['sg_n']})
    rows = []
    for club in shown:
        if club == 'P':
            continue
        p = profiles.get(club, {})
        rows.append({
            'key': club, 'label': club_label(club), 'name': club_name(club),
            'in_bag': club in bag,
            'n': p.get('n', 0), 'avg': p.get('avg'), 'lo': p.get('lo'), 'hi': p.get('hi'),
            'sg_n': p.get('sg_n', 0), 'sg_per': p.get('sg_per') if pro else None,
        })

    dists = [v for r in rows for v in (r['lo'], r['hi'], r['avg']) if v]
    lo_axis = max(0, (min(dists) // 50) * 50) if dists else 50
    hi_axis = ((max(dists) // 50) + 1) * 50 if dists else 300
    for r in rows:
        span = max(hi_axis - lo_axis, 1)
        r['x_lo'] = round((r['lo'] - lo_axis) / span * 100, 2) if r['lo'] else None
        r['x_hi'] = round((r['hi'] - lo_axis) / span * 100, 2) if r['hi'] else None
        r['x_avg'] = round((r['avg'] - lo_axis) / span * 100, 2) if r['avg'] else None

    groups = [{'name': name, 'clubs': [{'key': k, 'label': club_label(k), 'name': club_name(k), 'on': k in bag}
                                       for k in keys]} for name, keys in CLUB_GROUPS]
    return render_template(
        'bag/index.html',
        bag=bag, groups=groups, rows=rows, pro=pro,
        notes=_gap_notes([r for r in rows if r['in_bag']] or rows),
        axis={'lo': lo_axis, 'mid': (lo_axis + hi_axis) // 2, 'hi': hi_axis},
        rounds_used=len(datas), max_bag=MAX_BAG_SIZE,
        track_clubs=bool(current_user.track_clubs),
    )

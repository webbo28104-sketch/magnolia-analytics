"""
Previous-round shot history: feeds report comparisons, the caddy and the coach.
"""

import json

from app.models.round import Round
from app.utils.round_stats import build_course_hole_map
from app.utils.shot_sg import compute_round, CATEGORIES
from app.utils.sg_breakdown import add_travel


def round_weather(round_):
    """Cached weather snapshot for a round ({temp_c, wind_kph, ...}) or None."""
    rep = round_.report
    if rep and rep.weather_json and rep.weather_json != 'null':
        try:
            return json.loads(rep.weather_json)
        except (ValueError, TypeError):
            return None
    return None


def shots_for_round(round_):
    """compute_round() with travel distances, and each shot tagged with round context."""
    data = compute_round(round_, build_course_hole_map(round_))
    add_travel(data)
    wx = round_weather(round_)
    for s in data['shots']:
        s['round_id'] = round_.id
        s['date'] = round_.date_played
        s['wind_kph'] = wx.get('wind_kph') if wx else None
        s['temp_c'] = wx.get('temp_c') if wx else None
    return data


def previous_rounds(user_id, exclude_round_id=None, limit=10, before=None):
    q = Round.query.filter(Round.user_id == user_id, Round.status == 'complete')
    if exclude_round_id:
        q = q.filter(Round.id != exclude_round_id)
    if before is not None:
        q = q.filter(Round.date_played <= before)
    return q.order_by(Round.date_played.desc(), Round.id.desc()).limit(limit).all()


def history(user_id, exclude_round_id=None, limit=10, before=None):
    """Return (rounds, per-round data list, flat shots) for previous complete rounds."""
    rounds = previous_rounds(user_id, exclude_round_id, limit, before)
    datas, shots = [], []
    for r in rounds:
        try:
            d = shots_for_round(r)
        except Exception:
            continue
        datas.append((r, d))
        shots.extend(d['shots'])
    return rounds, datas, shots


def per_shot_averages(shots) -> dict:
    """{cat: {'per', 'n'}} SG per valued shot by category."""
    out = {}
    for c in CATEGORIES:
        vals = [s['sg'] for s in shots if s['cat'] == c and s['sg'] is not None]
        out[c] = {'per': round(sum(vals) / len(vals), 3) if vals else None, 'n': len(vals)}
    return out


def round_summary(round_, data) -> dict:
    """Compact per-round numbers used by the coach and dashboards."""
    shots = data['shots']
    tee = [s for s in shots if s['type'] == 'ott' and s.get('travel') and s['result'] != 'penalty']
    drivers = [s['travel'] for s in tee if s['club'] == 'D']
    return {
        'date': round_.date_played.strftime('%d %b %Y'),
        'course': round_.course.name if round_.course else 'Unknown course',
        'holes': round_.holes_played,
        'score': round_.total_score,
        'vs_par': round_.score_vs_par(),
        'putts': round_.total_putts,
        'fairways': f'{round_.fairways_hit}/{round_.fairways_available}' if round_.fairways_available else None,
        'gir': round_.gir_count,
        'sg': {c: data['totals'][c] for c in CATEGORIES},
        'sg_total': data['sg_total'],
        'avg_tee_travel': round(sum(s['travel'] for s in tee) / len(tee)) if tee else None,
        'avg_driver_travel': round(sum(drivers) / len(drivers)) if drivers else None,
        'longest_tee_travel': max((s['travel'] for s in tee), default=None),
    }

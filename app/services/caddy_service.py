"""
Caddy: club recommendations during shot entry.

Built entirely on the golfer's own logged shots (last 20 rounds):
  1. Each club's typical distance (estimated travel) from My Bag profiles.
  2. Today's conditions: the forecast temperature turns the yardage into a
     "plays like" distance (~1.2% longer per 10°C below 15°C).
  3. Strokes gained per shot with each candidate club from a similar
     distance, weighting shots played in similar wind more heavily and
     shrinking small samples toward the club's overall average.
"""

from datetime import date, datetime

from app.utils.clubs import club_label, club_name
from app.utils.club_stats import club_profiles
from app.utils.round_history import history, round_weather
from app.services.weather_service import fetch_forecast, fetch_weather

MIN_CLUB_SHOTS = 10       # logged shots with a club before the caddy speaks up
SIMILAR_YDS = 15          # approach shots within ±15 yds count as "from here"
SIMILAR_HOLE_YDS = 40     # tee shots on holes within ±40 yds
SHRINK_K = 2.0            # pseudo-shots of the club's overall average
WINDY_KPH = 20


def round_conditions(round_):
    """Weather for the round: forecast on the day, archive afterwards, else None."""
    course = round_.course
    lat = getattr(course, 'lat', None) if course else None
    lng = getattr(course, 'lng', None) if course else None
    cached = round_weather(round_)
    if cached:
        return cached
    if lat is None or lng is None:
        return None
    today = date.today()
    if round_.date_played >= today:
        hour = datetime.now().hour if round_.date_played == today else 12
        return fetch_forecast(lat, lng, round_.date_played, hour=min(max(hour, 6), 20))
    return fetch_weather(lat, lng, round_.date_played)


def plays_like(distance, temp_c):
    if distance is None or temp_c is None:
        return distance
    return round(distance * (1 + 0.0012 * (15 - temp_c)))


def _weight(shot, windy):
    w = shot.get('wind_kph')
    if w is None:
        return 1.0
    return 2.0 if (w >= 15) == windy else 1.0


def _score(sim, prior):
    wsum = sum(w for _, w in sim)
    return (sum(sg * w for sg, w in sim) + SHRINK_K * (prior or 0.0)) / (wsum + SHRINK_K)


def recommend(user, round_, shot_type, distance=None, hole_yardage=None, lie=None):
    bag = [c for c in user.bag if c != 'P']
    _, _, shots = history(user.id, limit=20)
    logged = [s for s in shots if s.get('club') and s['club'] != 'P']
    if len(logged) < MIN_CLUB_SHOTS:
        return {'status': 'learning', 'logged': len(logged), 'needed': MIN_CLUB_SHOTS}

    profiles = club_profiles(shots)
    wx = round_conditions(round_)
    windy = bool(wx and (wx.get('wind_kph') or 0) >= WINDY_KPH)
    weather = ({'temp_c': wx.get('temp_c'), 'wind_kph': wx.get('wind_kph'), 'condition': wx.get('condition')}
               if wx else None)
    pool = bag or list(profiles.keys())

    if shot_type == 'ott':
        target = hole_yardage
        cands = []
        for club in pool:
            tee = [s for s in logged if s['club'] == club and s['type'] == 'ott' and s['sg'] is not None]
            if not tee:
                continue
            prior = sum(s['sg'] for s in tee) / len(tee)
            near = [s for s in tee if target and s.get('hole_yardage')
                    and abs(s['hole_yardage'] - target) <= SIMILAR_HOLE_YDS] or tee
            sim = [(s['sg'], _weight(s, windy)) for s in near]
            cands.append({
                'club': club, 'score': _score(sim, prior),
                'n': len(near), 'per': round(sum(s['sg'] for s in near) / len(near), 3),
                'avg_dist': profiles.get(club, {}).get('avg'),
            })
        if not cands:
            return {'status': 'learning', 'logged': len(logged), 'needed': MIN_CLUB_SHOTS,
                    'message': 'Log a club on a few tee shots and the caddy will compare them.'}
        cands.sort(key=lambda c: -c['score'])
        return _result(cands, weather, None, target, 'tee')

    if not distance:
        return {'status': 'need_distance'}
    target = plays_like(distance, weather['temp_c'] if weather else None)
    fits = []
    for club in pool:
        p = profiles.get(club)
        if not p or not p.get('avg') or p['n'] < 2 or club == 'D':
            continue
        fits.append((abs(p['avg'] - target), club, p))
    if not fits:
        return {'status': 'learning', 'logged': len(logged), 'needed': MIN_CLUB_SHOTS,
                'message': 'Log clubs on a few more approach shots so the caddy knows your distances.'}
    fits.sort()
    shortlist = [f for f in fits if f[0] <= 20] or fits[:3]
    cands = []
    for fit, club, p in shortlist[:5]:
        near = [s for s in logged if s['club'] == club and s['cat'] in ('app', 'atg') and s['sg'] is not None
                and s['dist'] and abs(s['dist'] - distance) <= SIMILAR_YDS]
        sim = [(s['sg'], _weight(s, windy)) for s in near]
        score = _score(sim, p.get('sg_per')) - 0.012 * max(0, fit - 5)
        cands.append({
            'club': club, 'score': score, 'n': len(near),
            'per': round(sum(s['sg'] for s in near) / len(near), 3) if near else None,
            'avg_dist': p['avg'], 'fit': round(fit),
        })
    cands.sort(key=lambda c: -c['score'])
    return _result(cands, weather, target, distance, 'approach')


def _result(cands, weather, target, distance, kind):
    def pack(c):
        return {'club': c['club'], 'label': club_label(c['club']), 'name': club_name(c['club']),
                'n': c['n'], 'per': c['per'], 'avg_dist': c.get('avg_dist')}
    best = cands[0]
    return {
        'status': 'ok', 'kind': kind,
        'best': pack(best), 'alts': [pack(c) for c in cands[1:3]],
        'plays_like': target, 'distance': distance, 'weather': weather,
    }

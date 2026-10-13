"""
Reconcile England Golf scores with the golfer's Magnolia rounds.

Every England Golf score ends up attached to exactly one Magnolia round:
  - an existing round played the same day (±1), same course and 9/18 holes,
    choosing the closest total when there are several; or
  - a new 'score_only' round holding the England Golf score.

Linked rounds count as official and use England Golf's differential for
handicaps (it applies net double bogey, PCC and the correct ratings). Rounds
with no England Golf score are casual.
"""

from datetime import date, timedelta

from rapidfuzz import fuzz

from app import db
from app.models.course import Course
from app.models.round import Round

DAY_WINDOW = 1
MAX_SCORE_GAP = 15
COURSE_MATCH = 70


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _same_course(eg_name, rnd):
    if not eg_name or not rnd.course:
        return True   # nothing to compare; date and score decide
    return fuzz.partial_ratio(eg_name.lower(), rnd.course.name.lower()) >= COURSE_MATCH


def _holes_match(eg_holes, rnd):
    played = rnd.holes_played or 18
    return (played >= 18) == (eg_holes != 9)


def _best_round(score, candidates):
    d = date.fromisoformat(score['date'])
    best, best_cost = None, None
    for r in candidates:
        gap = abs((r.date_played - d).days)
        if gap > DAY_WINDOW or not _holes_match(score['holes'], r) or not _same_course(score['course'], r):
            continue
        diff = abs((r.total_score or 0) - (score['adj_gross'] or 0)) if r.total_score else MAX_SCORE_GAP
        if diff > MAX_SCORE_GAP:
            continue
        cost = gap * 20 + diff
        if best_cost is None or cost < best_cost:
            best, best_cost = r, cost
    return best


def _course_for(user_id, eg_name):
    """A course this golfer has played whose name matches England Golf's."""
    if not eg_name:
        return None
    played = (Course.query.join(Round, Round.course_id == Course.id)
              .filter(Round.user_id == user_id).distinct().all())
    scored = [(fuzz.partial_ratio(eg_name.lower(), c.name.lower()), c) for c in played]
    scored = [x for x in scored if x[0] >= COURSE_MATCH]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def _link(rnd, score):
    rnd.eg_score_uid = score['uid']
    rnd.eg_adj_gross = score['adj_gross']
    rnd.eg_differential = _float(score['differential'])
    rnd.counts_for_official_hc = True
    if rnd.eg_differential is not None:
        rnd.hc_differential = rnd.eg_differential


def reconcile(user, scores) -> dict:
    """Link/create rounds for every England Golf score. Commits. Returns counts."""
    usable = [s for s in scores
              if s.get('uid') and s.get('date') and not s.get('parent_uid')
              # committee penalty scores that don't count (e.g. card not returned) aren't rounds
              and not (s.get('penalty') and not s.get('counted'))]
    rounds = (Round.query.filter(Round.user_id == user.id, Round.status.in_(('complete', 'score_only')))
              .order_by(Round.date_played.desc()).all())
    by_uid = {r.eg_score_uid: r for r in rounds if r.eg_score_uid}
    free = [r for r in rounds if not r.eg_score_uid and r.status == 'complete']

    linked = created = 0
    for s in sorted(usable, key=lambda x: x['date']):
        if s['uid'] in by_uid:
            _link(by_uid[s['uid']], s)          # refresh in case England Golf revised it
            continue
        rnd = _best_round(s, free)
        if rnd:
            free.remove(rnd)
            linked += 1
        else:
            course = _course_for(user.id, s['course'])
            rnd = Round(user_id=user.id, course_id=course.id if course else None,
                        date_played=date.fromisoformat(s['date']), holes_played=s['holes'] or 18,
                        tee_set=s.get('tees') or None, total_score=s['adj_gross'], status='score_only')
            db.session.add(rnd)
            created += 1
        _link(rnd, s)
        by_uid[s['uid']] = rnd

    # Everything England Golf doesn't know about is casual
    for r in free:
        r.counts_for_official_hc = False
    db.session.commit()
    return {'linked': linked, 'created': created, 'casual': len(free)}

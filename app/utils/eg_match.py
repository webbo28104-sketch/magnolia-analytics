"""
Reconcile England Golf scores with the golfer's Magnolia rounds.

Every England Golf score ends up attached to exactly one Magnolia round:
  - an existing round played the same day (±1) at the same course whose total is
    close to England Golf's (rounds logged only part-way, e.g. to the 16th, are
    projected to 9/18 holes first), choosing the closest when there are several; or
  - a new 'score_only' round holding the England Golf score. If the golfer logs
    that round later, the next match merges it into the logged round.

Linked rounds count as official and use England Golf's differential for
handicaps (it applies net double bogey, PCC and the correct ratings). Rounds
with no England Golf score are casual.
"""

import re
from datetime import date

from rapidfuzz import fuzz

from app import db
from app.models.course import Course
from app.models.round import Round
from app.models.tee_set import TeeSet

DAY_WINDOW = 1
MAX_SCORE_GAP = 15
COURSE_MATCH = 90   # on names with generic words removed — "Seaford" ≠ "Seaford Head"

_GENERIC = {'golf', 'club', 'course', 'gc', 'the', 'and', 'links', 'ltd', 'limited', 'g', 'c'}


def _norm(name):
    words = re.sub(r'[^a-z0-9 ]+', ' ', (name or '').lower()).split()
    return ' '.join(w for w in words if w not in _GENERIC)


def _name_score(eg_name, course_name):
    """Whole-name similarity after dropping generic words, so a distinguishing
    word like 'Head' counts against the match instead of being ignored."""
    a, b = _norm(eg_name), _norm(course_name)
    if not a or not b:
        return 0
    return fuzz.token_sort_ratio(a, b)


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rating_match(score, tee_set):
    """Course rating + slope identify a course and tee far better than a name."""
    cr, slope = _float(score.get('course_rating')), _float(score.get('slope'))
    if cr is None or slope is None or score.get('holes') == 9:
        return False
    return abs(tee_set.course_rating - cr) <= 0.05 and int(tee_set.slope_rating) == int(slope)


def _same_course(score, rnd):
    eg_name = score.get('course')
    if not rnd.course:
        return True   # nothing to compare; date and score decide
    # Primary: England Golf's rating/slope matches one of this course's tees
    if any(_rating_match(score, ts) for ts in rnd.course.tee_sets):
        return True
    if not eg_name:
        return True
    # Date and score already agree, so it's enough that England Golf's words all
    # appear in the course name ("Singing Hills" → "Singing Hills … Lake And Valley")
    eg_words = set(_norm(eg_name).split())
    return bool(eg_words and eg_words <= set(_norm(rnd.course.name).split())) or \
        _name_score(eg_name, rnd.course.name) >= COURSE_MATCH


def _score_gap(score, rnd):
    """
    How far the Magnolia total is from England Golf's, allowing for holes not logged.

    A round logged to the 16th against a full 18 on England Golf is compared by
    projecting the missing holes at the golfer's own scoring rate for that round.
    Returns None when the hole counts can't be the same round.
    """
    eg_holes = 9 if score['holes'] == 9 else 18
    played = rnd.holes_played or 18
    if played > eg_holes or played < (10 if eg_holes == 18 else 6) or not rnd.total_score:
        return None
    missing = eg_holes - played
    projected = rnd.total_score + missing * rnd.total_score / played
    return abs((score['adj_gross'] or 0) - projected)


def _best_round(score, candidates):
    d = date.fromisoformat(score['date'])
    best, best_cost = None, None
    for r in candidates:
        gap = abs((r.date_played - d).days)
        if gap > DAY_WINDOW or not _same_course(score, r):
            continue
        diff = _score_gap(score, r)
        if diff is None or diff > MAX_SCORE_GAP:
            continue
        cost = gap * 20 + diff
        if best_cost is None or cost < best_cost:
            best, best_cost = r, cost
    return best


def _course_for(user_id, score):
    """
    (course, tee_set) for an England Golf score with no logged round.

    1. Tees whose course rating and slope equal England Golf's — the reliable check.
    2. Otherwise a course this golfer has played whose name matches.
    Ties go to the course the golfer has played most. Returns (None, None) rather
    than guess.
    """
    plays = dict(db.session.query(Round.course_id, db.func.count(Round.id))
                 .filter(Round.user_id == user_id, Round.status == 'complete', Round.course_id.isnot(None))
                 .group_by(Round.course_id).all())
    eg_name = score.get('course')

    cr = _float(score.get('course_rating'))
    if cr is not None and score.get('holes') != 9:
        tees = [t for t in TeeSet.query.filter(TeeSet.course_rating.between(cr - 0.05, cr + 0.05)).all()
                if _rating_match(score, t)]
        if tees:
            def rank(t):
                return (_name_score(eg_name, t.course.name) if eg_name else 0, plays.get(t.course_id, 0),
                        (score.get('tees') or '').lower() in (t.name or '').lower())
            best = max(tees, key=rank)
            return best.course, best

    if not eg_name:
        return None, None
    scored = [(_name_score(eg_name, c.name), plays[c.id], c)
              for c in Course.query.filter(Course.id.in_(list(plays))).all()]
    scored = [x for x in scored if x[0] >= COURSE_MATCH]
    return (max(scored, key=lambda x: (x[0], x[1]))[2], None) if scored else (None, None)


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

    linked = created = merged = 0
    for s in sorted(usable, key=lambda x: x['date']):
        held = by_uid.get(s['uid'])
        if held and held.status == 'score_only':
            # A logged round for this score has appeared since: merge into it
            rnd = _best_round(s, free)
            if rnd:
                free.remove(rnd)
                db.session.delete(held)
                _link(rnd, s)
                by_uid[s['uid']] = rnd
                merged += 1
                continue
        if held:
            _link(held, s)                      # refresh in case England Golf revised it
            if held.status == 'score_only':
                course, tee = _course_for(user.id, s)
                held.course_id = course.id if course else None
                held.tee_set_id = tee.id if tee else None
            continue
        rnd = _best_round(s, free)
        if rnd:
            free.remove(rnd)
            linked += 1
        else:
            course, tee = _course_for(user.id, s)
            rnd = Round(user_id=user.id, course_id=course.id if course else None,
                        tee_set_id=tee.id if tee else None,
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
    return {'linked': linked, 'created': created, 'merged': merged, 'casual': len(free)}


def reconcile_stored(user) -> dict | None:
    """Re-run matching against the scores saved at the last sync (no England Golf call)."""
    import json
    if not (user.eg_member_no and user.eg_scores_json):
        return None
    try:
        scores = json.loads(user.eg_scores_json)
    except ValueError:
        return None
    return reconcile(user, scores)

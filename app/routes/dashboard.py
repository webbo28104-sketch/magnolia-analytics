from flask import Blueprint, render_template, url_for
from flask_login import login_required, current_user
import math
from datetime import date, timedelta
from app.models.round import Round
from app.models.hole import Hole
from app.utils.personal_bests import check_recent_personal_best
from app.utils.access import is_pro

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    # Single query for all complete rounds — used for stats, glance, and recent list
    all_complete = (
        Round.query
        .filter_by(user_id=current_user.id, status='complete')
        .order_by(Round.date_played.desc())
        .all()
    )

    total_complete = len(all_complete)
    # Free users see last 10 rounds; pro users see full history.
    # TODO: when founding/standard tiers are introduced, update is_pro() in
    # app/utils/access.py — do not add inline tier checks here.
    user_is_pro = is_pro(current_user)
    recent_rounds = all_complete if user_is_pro else all_complete[:10]
    stats  = _compute_stats(all_complete[:20]) if all_complete else None
    glance = _compute_glance(all_complete) if all_complete else None

    # In-progress rounds â find the next unplayed hole for each
    in_progress = (
        Round.query
        .filter_by(user_id=current_user.id, status='in_progress')
        .order_by(Round.created_at.desc())
        .all()
    )
    in_progress_rounds = []
    for r in in_progress:
        saved_holes = {h.hole_number for h in r.holes}
        if r.holes_played == 9 and r.nine_hole_selection == 'back':
            hole_range = range(10, 19)
        elif r.holes_played == 9:
            hole_range = range(1, 10)
        else:
            hole_range = range(1, 19)
        next_seq = None
        for i, actual in enumerate(hole_range, start=1):
            if actual not in saved_holes:
                next_seq = i
                break
        if next_seq is None:
            next_seq = r.holes_played
        in_progress_rounds.append({
            'round': r,
            'next_hole_url': url_for('rounds.enter_hole', round_id=r.id, hole_number=next_seq),
            'holes_done': len(saved_holes),
        })

    sg_avgs = _compute_sg_avgs(all_complete[:20])

    return render_template('dashboard/index.html',
        recent_rounds=recent_rounds,
        total_complete=total_complete,
        user_is_pro=user_is_pro,
        stats=stats,
        glance=glance,
        in_progress_rounds=in_progress_rounds,
        sg_avgs=sg_avgs)


def _compute_stats(rounds):
    if not rounds:
        return None

    # Per-hole average score â normalises across 9 and 18-hole rounds
    scored = [r for r in rounds if r.total_score and r.holes_played]
    avg_score_per_hole = (
        round(sum(r.total_score / r.holes_played for r in scored) / len(scored), 2)
        if scored else None
    )

    # Aggregate all holes for per-hole metrics
    all_holes = [h for r in rounds for h in r.holes.all()]

    # GIR %
    gir_pct = (
        round(sum(1 for h in all_holes if h.gir) / len(all_holes) * 100, 1)
        if all_holes else None
    )

    # FIR % â only counted on par 4s and par 5s
    fir_holes = [h for h in all_holes if h.par in (4, 5) and h.tee_shot is not None]
    fir_pct = (
        round(sum(1 for h in fir_holes if h.tee_shot == 'fairway') / len(fir_holes) * 100, 1)
        if fir_holes else None
    )

    # Scramble %
    missed_gir = [h for h in all_holes if not h.gir]
    scramble_pct = (
        round(sum(1 for h in missed_gir if h.score is not None and h.par is not None and h.score <= h.par) / len(missed_gir) * 100, 1)
        if missed_gir else None
    )

    # Putts per hole
    putts_data = [h.putts for h in all_holes if h.putts is not None]
    putts_per_hole = (
        round(sum(putts_data) / len(putts_data), 2)
        if putts_data else None
    )

    # Average score by par type
    def avg_by_par(par_num):
        hs = [h for h in all_holes if h.par == par_num and h.score is not None]
        return round(sum(h.score for h in hs) / len(hs), 2) if hs else None

    return {
        'rounds_played': len(rounds),
        'avg_score_per_hole': avg_score_per_hole,
        'avg_par3': avg_by_par(3),
        'avg_par4': avg_by_par(4),
        'avg_par5': avg_by_par(5),
        'gir_pct': gir_pct,
        'fir_pct': fir_pct,
        'scramble_pct': scramble_pct,
        'putts_per_hole': putts_per_hole,
    }


def _compute_glance(all_rounds):
    """Compute 'Your Game at a Glance' engagement metrics from all complete rounds."""
    if not all_rounds:
        return None

    today = date.today()
    glance = {}

    # 1. Streak — consecutive weeks (ISO) going back from most recent round's week
    weeks_with_rounds = set()
    for r in all_rounds:
        iso = r.date_played.isocalendar()
        weeks_with_rounds.add((iso[0], iso[1]))

    streak = 0
    check = all_rounds[0].date_played          # start from most recent round
    while True:
        iso = check.isocalendar()
        if (iso[0], iso[1]) in weeks_with_rounds:
            streak += 1
            check -= timedelta(weeks=1)
        else:
            break
    glance['streak'] = streak                  # always >= 1

    # 2. Rounds this month vs last month
    glance['this_month'] = sum(
        1 for r in all_rounds
        if r.date_played.year == today.year and r.date_played.month == today.month
    )
    last_month_year = today.year if today.month > 1 else today.year - 1
    last_month_num  = today.month - 1 if today.month > 1 else 12
    glance['prev_month'] = sum(
        1 for r in all_rounds
        if r.date_played.year == last_month_year and r.date_played.month == last_month_num
    )

    # 3. Best SG category across last 5 rounds with trend (need >= 2 rounds with SG data)
    sg_cats = {
        'Putting':          'sg_putting',
        'Off the Tee':      'sg_off_tee',
        'Approach':         'sg_approach',
        'Around the Green': 'sg_atg',
    }
    last5_sg = [r for r in all_rounds[:5] if any(getattr(r, a) is not None for a in sg_cats.values())]

    if len(last5_sg) >= 2:
        avgs = {}
        for cat_name, attr in sg_cats.items():
            vals = [getattr(r, attr) for r in last5_sg if getattr(r, attr) is not None]
            if vals:
                avgs[cat_name] = sum(vals) / len(vals)

        if avgs:
            best_cat = max(avgs, key=avgs.get)
            attr     = sg_cats[best_cat]
            newest   = getattr(last5_sg[0], attr)
            oldest   = getattr(last5_sg[-1], attr)
            trend    = ('up' if newest > oldest else 'down') if (newest is not None and oldest is not None) else None
            glance['best_sg_cat']    = best_cat
            glance['best_sg_trend']  = trend
            glance['sg_rounds_count'] = len(last5_sg)
        else:
            glance['best_sg_cat'] = None
    else:
        glance['best_sg_cat'] = None

    # 4. Personal best — scan the last 5 rounds, each vs same-format previous rounds.
    # Checking 5 rounds catches cases where the most recent round isn't the relevant
    # format (e.g. the last 9-hole PB was 3 rounds ago after two 18-hole rounds).
    recent_pb = None
    for i, r in enumerate(all_rounds[:5]):
        prev = all_rounds[i + 1:]
        pb = check_recent_personal_best(r, prev)
        if pb:
            recent_pb = pb
            break
    glance['recent_pb'] = recent_pb

    return glance


def _compute_sg_avgs(rounds):
    """Average SG per category across up to 20 rounds. Returns None if < 3 rounds have data."""
    SG_ATTRS = [
        ('Off the Tee',      'sg_off_tee'),
        ('Approach',         'sg_approach'),
        ('Around the Green', 'sg_atg'),
        ('Putting',          'sg_putting'),
    ]

    sg_rounds = [
        r for r in rounds
        if any(getattr(r, attr) is not None for _, attr in SG_ATTRS)
    ]
    if len(sg_rounds) < 3:
        return None

    # Compute averages normalised to an 18-hole equivalent so that 9-hole and
    # 18-hole rounds are comparable.  For each round we convert the raw SG value
    # to a per-hole rate (÷ holes_played) then scale back to 18 holes (× 18).
    # Averaging these 18-hole equivalents gives a fair cross-format mean.
    categories = []
    for name, attr in SG_ATTRS:
        vals = [
            getattr(r, attr) / r.holes_played * 18
            for r in sg_rounds
            if getattr(r, attr) is not None and r.holes_played
        ]
        if not vals:
            continue
        categories.append({'name': name, 'avg': round(sum(vals) / len(vals), 2)})

    if not categories:
        return None

    # Relative colour ranking: best (highest avg) → green, worst → red, middle → gold
    ranked = sorted(categories, key=lambda c: c['avg'])
    for i, cat in enumerate(ranked):
        if i == len(ranked) - 1:
            cat['color'] = 'best'
        elif i == 0:
            cat['color'] = 'worst'
        else:
            cat['color'] = 'mid'

    # Dynamic scale — zero near the RIGHT (negative bars extend left, positive right)
    avgs    = [c['avg'] for c in categories]
    min_val = min(avgs)
    max_val = max(avgs)

    # Round the most negative value DOWN to nearest integer for the left-edge anchor.
    # e.g. -2.68 → -3, -3.1 → -4. This guarantees the worst bar never fully
    # reaches the left edge — there is always a small visual gap.
    floor_min = math.floor(min_val)   # always ≤ min_val

    # Right-side allowance: at least 0.5 SG of space beyond zero for positive values
    right_range = max(max_val, 0.0) + 0.5

    # Total scale range and zero position (% from left edge)
    total_range = abs(floor_min) + right_range
    zero_pct    = round(abs(floor_min) / total_range * 100, 1)   # ~80–85 % from left

    for cat in categories:
        v = cat['avg']
        if v < 0:
            # Negative bar: extends LEFT from zero line
            cat['width_pct'] = round(abs(v) / total_range * 100, 2)
            cat['positive']  = False
        else:
            # Positive bar: extends RIGHT from zero line
            cat['width_pct'] = round(v / total_range * 100, 2)
            cat['positive']  = True

    return {
        'categories':   categories,
        'rounds_count': len(sg_rounds),
        'zero_pct':     zero_pct,
    }

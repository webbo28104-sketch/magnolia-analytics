from flask import Blueprint, render_template, url_for, request, flash
from flask_login import login_required, current_user
import logging

from app.models.round import Round
from app.utils.access import is_pro
from app.utils.strokes_gained import normalize_to_18
from app.utils.shot_sg import CATEGORIES, CATEGORY_LABELS
from app.utils.round_history import shots_for_round
from app.utils import sg_breakdown as bd
from app.utils import sg_evidence as ev

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

WINDOW = 10        # rounds in the "current" window
TREND_ROUNDS = 20  # rounds plotted on the SG trend

ANALYTICS_LINKS = {
    'ott': 'analytics.off_the_tee', 'app': 'analytics.approach',
    'atg': 'analytics.around_green', 'putt': 'analytics.putting',
}


def _in_progress():
    rounds = (Round.query.filter_by(user_id=current_user.id, status='in_progress')
              .order_by(Round.created_at.desc()).all())
    out = []
    for r in rounds:
        saved = {h.hole_number for h in r.holes}
        if r.holes_played == 9 and r.nine_hole_selection == 'back':
            hole_range = range(10, 19)
        elif r.holes_played == 9:
            hole_range = range(1, 10)
        else:
            hole_range = range(1, 19)
        next_seq = next((i for i, actual in enumerate(hole_range, start=1) if actual not in saved), r.holes_played)
        out.append({'round': r, 'holes_done': len(saved),
                    'next_hole_url': url_for('rounds.enter_hole', round_id=r.id, hole_number=next_seq)})
    return out


def _per_shot(shots, cat):
    vals = [s['sg'] for s in shots if s['cat'] == cat and s['sg'] is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def _spark(values, w=90, h=24):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ''
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = []
    for i, v in enumerate(vals):
        pts.append(f'{i / (len(vals) - 1) * w:.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}')
    return ' '.join(pts)


def _trend(rounds):
    """SG per round on an 18-hole basis, oldest → newest, with a 5-round average."""
    pts = [(r, normalize_to_18(r.sg_total, r.holes_played)) for r in reversed(rounds)
           if r.sg_total is not None and (r.holes_played or 0) >= 9]
    if len(pts) < 2:
        return None
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 0.5)
    lo, hi = lo - pad, hi + pad
    y = lambda v: 20 + (hi - v) / (hi - lo) * 200
    x = lambda i: i / (len(pts) - 1) * 1000
    line = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(vals))
    avg = []
    for i in range(len(vals)):
        win = vals[max(0, i - 4):i + 1]
        avg.append(f'{x(i):.1f},{y(sum(win) / len(win)):.1f}')
    dots = [{'x': round(x(i), 1), 'y': round(y(v), 1), 'v': round(v, 1),
             'date': r.date_played.strftime('%d %b'), 'id': r.id} for i, (r, v) in enumerate(pts)]
    ticks = [round(hi - (hi - lo) * k / 2, 1) for k in range(3)]
    return {'line': line, 'avg': ' '.join(avg), 'dots': dots, 'ticks': ticks, 'n': len(pts),
            'zero': round(y(0), 1) if lo < 0 < hi else None,
            'best': max(vals), 'worst': min(vals), 'latest': vals[-1]}


@dashboard_bp.route('/')
@login_required
def index():
    if request.args.get('subscribed') == 'true':
        if current_user.is_founding_member:
            flash('Welcome, Founding Member — your rate is locked for life.', 'success')
        else:
            flash("Welcome to Magnolia — you're all set.", 'success')

    all_complete = (Round.query.filter_by(user_id=current_user.id, status='complete')
                    .order_by(Round.date_played.desc(), Round.id.desc()).all())
    user_is_pro = is_pro(current_user)

    # Per-shot data for the last 20 rounds (current window + comparison window)
    datas = {}
    for r in all_complete[:WINDOW * 2]:
        try:
            datas[r.id] = shots_for_round(r)
        except Exception as e:
            logger.warning('[dashboard] shot data failed for round %s: %s', r.id, e)
    cur = [r for r in all_complete[:WINDOW] if r.id in datas]
    prev = [r for r in all_complete[WINDOW:WINDOW * 2] if r.id in datas]
    cur_shots = [s for r in cur for s in datas[r.id]['shots']]
    prev_shots = [s for r in prev for s in datas[r.id]['shots']]

    # ── KPIs ─────────────────────────────────────────────────────────────
    full = [r for r in cur if r.holes_played == 18 and r.total_score]
    # Rounds under 9 holes are too short to project to 18 holes meaningfully
    sg18 = [normalize_to_18(r.sg_total, r.holes_played) for r in cur
            if r.sg_total is not None and (r.holes_played or 0) >= 9]
    sg18_prev = [normalize_to_18(r.sg_total, r.holes_played) for r in prev
                 if r.sg_total is not None and (r.holes_played or 0) >= 9]
    measured = [s for s in cur_shots if s['sg'] is not None]
    kpi = {
        'scoring_avg': round(sum(r.total_score for r in full) / len(full), 1) if full else None,
        'scoring_n': len(full),
        'sg_round': round(sum(sg18) / len(sg18), 2) if sg18 else None,
        'sg_round_delta': (round(sum(sg18) / len(sg18) - sum(sg18_prev) / len(sg18_prev), 2)
                           if sg18 and len(sg18_prev) >= 3 else None),
        'sg_shot': round(sum(s['sg'] for s in measured) / len(measured), 3) if measured else None,
        'shots': len(measured),
    }

    # ── Categories, leaks, trend (Pro) ───────────────────────────────────
    cats, leaks, trend = [], [], None
    if user_is_pro and cur:
        for c in CATEGORIES:
            per, n = _per_shot(cur_shots, c)
            pper, pn = _per_shot(prev_shots, c)
            per_round = [normalize_to_18(datas[r.id]['totals'][c], r.holes_played) for r in cur
                         if (r.holes_played or 0) >= 9]
            spark_vals = []
            for r in reversed(cur):
                v, k = _per_shot(datas[r.id]['shots'], c)
                spark_vals.append(v)
            cats.append({
                'cat': c, 'label': CATEGORY_LABELS[c], 'per': per, 'n': n,
                'per_round': round(sum(per_round) / len(per_round), 1) if per_round else None,
                'delta': (per - pper) if (per is not None and pper is not None and pn >= 15) else None,
                'spark': _spark(spark_vals), 'href': url_for(ANALYTICS_LINKS[c]),
            })
        leaks, _ = bd.leaks_and_strengths(cur_shots, prev_shots, n_leaks=4, n_strengths=0)
        sd = ev.category_sd(cur_shots + prev_shots)
        cur_pairs = [(r, datas[r.id]) for r in cur]
        for l in leaks:
            l['rel'] = ev.reliability(l['per'], l['n'], sd.get(ev.DIM_CAT.get(l['dim']), 0.5))
            l['pattern'] = ev.pattern(None, ev.per_round_values(cur_pairs, l['dim']).get(l['key'], []))
        for cat in cats:
            cat['rel'] = ev.reliability(cat['per'], cat['n'], sd[cat['cat']])
        trend = _trend(all_complete[:TREND_ROUNDS])

    # ── Recent rounds table ──────────────────────────────────────────────
    # Score-only rounds come from England Golf and have no shot data
    score_only = (Round.query.filter_by(user_id=current_user.id, status='score_only')
                  .order_by(Round.date_played.desc()).limit(25).all())
    listed = sorted(all_complete[:25] + score_only, key=lambda r: (r.date_played, r.id), reverse=True)[:25]
    recent = []
    for r in listed:
        if r.status == 'score_only':
            recent.append({'round': r, 'vs_par': None, 'sg': None, 'ott': None,
                           'cats': {c: None for c in CATEGORIES} if user_is_pro else None})
            continue
        d = datas.get(r.id)
        recent.append({
            'round': r, 'vs_par': r.score_vs_par(),
            'sg': r.sg_total if user_is_pro else None,
            'cats': ({c: (d['totals'][c] if d else getattr(r, {'ott': 'sg_off_tee', 'app': 'sg_approach',
                                                               'atg': 'sg_atg', 'putt': 'sg_putting'}[c]))
                      for c in CATEGORIES} if user_is_pro else None),
            'ott': r.sg_off_tee,
        })

    return render_template(
        'dashboard/index.html',
        user_is_pro=user_is_pro,
        total_complete=len(all_complete),
        window=len(cur),
        kpi=kpi, cats=cats, leaks=leaks, trend=trend,
        recent=recent, more_rounds=max(len(all_complete) - 25, 0),
        in_progress_rounds=_in_progress(),
    )

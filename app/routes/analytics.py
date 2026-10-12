"""
Game-section analysis pages — Off the Tee, Approach, Around the Green, Putting.

Every page is built on per-shot strokes gained across the golfer's last 10
complete rounds, compared with the 10 before that: SG per shot by distance
band for each round (heatmap), breakdowns by lie and club, a per-round trend,
and calm vs windy club performance.

All routes are Pro-only; free users are redirected to the upgrade page.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models.round import Round
from app.utils.access import is_pro
from app.utils.round_history import shots_for_round
from app.utils.shot_sg import CATEGORY_LABELS
from app.utils import sg_breakdown as bd

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

WINDOW = 10
WINDY_KPH = 20

PAGES = {
    'ott':  {'endpoint': 'analytics.off_the_tee', 'title': 'Off the tee', 'heat': 'ott_len',
             'heat_label': 'Hole yds', 'tables': [('ott_club', 'By club'), ('ott_result', 'By result')],
             'unit': 'shot'},
    'app':  {'endpoint': 'analytics.approach', 'title': 'Approach', 'heat': 'app_dist',
             'heat_label': 'Yds', 'tables': [('app_lie', 'By lie'), ('app_club', 'By club')], 'unit': 'shot'},
    'atg':  {'endpoint': 'analytics.around_green', 'title': 'Short game', 'heat': 'atg_dist',
             'heat_label': 'Yds', 'tables': [('atg_lie', 'By lie'), ('atg_club', 'By club')], 'unit': 'shot'},
    'putt': {'endpoint': 'analytics.putting', 'title': 'Putting', 'heat': 'putt_dist',
             'heat_label': 'Feet', 'tables': [], 'unit': 'putt'},
}


def _pro_gate():
    if not is_pro(current_user):
        flash('Game analysis is a Magnolia Pro feature.', 'info')
        return redirect(url_for('main.upgrade'))
    return None


def _per(shots):
    vals = [s['sg'] for s in shots if s['sg'] is not None]
    return (round(sum(vals) / len(vals), 3), len(vals)) if vals else (None, 0)


def _filter(shots, cat, lie, wind):
    out = [s for s in shots if s['cat'] == cat and s['sg'] is not None]
    if lie:
        out = [s for s in out if s['lie'] == lie]
    if wind == 'calm':
        out = [s for s in out if s.get('wind_kph') is not None and s['wind_kph'] < WINDY_KPH]
    elif wind == 'windy':
        out = [s for s in out if s.get('wind_kph') is not None and s['wind_kph'] >= WINDY_KPH]
    return out


def _category_page(cat):
    gate = _pro_gate()
    if gate:
        return gate
    cfg = PAGES[cat]
    lie = request.args.get('lie') or None
    wind = request.args.get('wind') or None

    rounds = (Round.query.filter_by(user_id=current_user.id, status='complete')
              .order_by(Round.date_played.desc(), Round.id.desc()).limit(WINDOW * 2).all())
    datas = []
    for r in rounds:
        try:
            datas.append((r, shots_for_round(r)))
        except Exception:
            continue
    cur, prev = datas[:WINDOW], datas[WINDOW:]
    cur_shots = _filter([s for _, d in cur for s in d['shots']], cat, lie, wind)
    prev_shots = _filter([s for _, d in prev for s in d['shots']], cat, lie, wind)

    per, n = _per(cur_shots)
    pper, pn = _per(prev_shots)
    per_round_totals = [d['totals'][cat] for r, d in cur if (r.holes_played or 0) >= 9]

    # ── Heatmap: SG per shot by band (rows) × round (columns, oldest → newest) ──
    cols = list(reversed(cur))
    heat_dim = cfg['heat']
    _, _, order = bd._dims()[heat_dim]
    overall = {r['key']: r for r in bd.rows(cur_shots, heat_dim)}
    heat = []
    for key in order:
        if key not in overall:
            continue
        cells, neg, played = [], 0, 0
        for r, d in cols:
            rs = _filter(d['shots'], cat, lie, wind)
            b = bd.aggregate(rs, heat_dim).get(key)
            if b:
                v = b['sg'] / b['n']
                played += 1
                neg += 1 if v < 0 else 0
                cells.append({'v': round(v, 2), 'n': b['n'], 'a': round(min(abs(v) / 0.5, 1) * 0.85 + 0.12, 2),
                              'pos': v >= 0})
            else:
                cells.append(None)
        row = overall[key]
        heat.append({'label': row['label'], 'per': row['per'], 'n': row['n'], 'cells': cells,
                     'neg': neg, 'played': played})
    insight = None
    regular = [h for h in heat if h['played'] >= 3]
    if regular:
        worst = max(regular, key=lambda h: (h['neg'] / h['played'], -h['per']))
        best = min(regular, key=lambda h: (h['neg'] / h['played'], -h['per']))
        unit = {'putt': 'ft', 'ott': 'yd holes'}.get(cat, 'yds')
        insight = (f"{worst['label']} {unit} has lost strokes in {worst['neg']} of the {worst['played']} rounds "
                   f"you played from there ({worst['per']:+.2f}/{cfg['unit']}).")
        if best is not worst and best['neg'] < best['played'] / 2:
            insight += (f" {best['label']} {unit} was at or above Tour level in "
                        f"{best['played'] - best['neg']} of {best['played']} ({best['per']:+.2f}/{cfg['unit']}).")

    # ── Per-round trend (SG per shot, oldest → newest) ──
    trend_vals = []
    for r, d in cols:
        v, k = _per(_filter(d['shots'], cat, lie, wind))
        if v is not None:
            trend_vals.append({'date': r.date_played.strftime('%d %b'), 'v': v})
    trend = None
    if len(trend_vals) >= 2:
        vs = [t['v'] for t in trend_vals]
        lo, hi = min(vs + [0]), max(vs + [0])
        pad = max((hi - lo) * 0.15, 0.05)
        lo, hi = lo - pad, hi + pad
        y = lambda v: 10 + (hi - v) / (hi - lo) * 180
        x = lambda i: i / (len(vs) - 1) * 1000
        trend = {'line': ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(vs)),
                 'zero': round(y(0), 1), 'hi': round(hi, 2), 'lo': round(lo, 2),
                 'first': trend_vals[0]['date'], 'last': trend_vals[-1]['date']}

    tables = [(title, bd.rows(cur_shots, dim, prev_shots), dim) for dim, title in cfg['tables']]
    heat_rows_detail = bd.rows(cur_shots, heat_dim, prev_shots)

    # ── Calm vs windy by club (approach & short game) ──
    wind_rows = []
    if cat in ('app', 'atg', 'ott') and not wind:
        all_cat = _filter([s for _, d in cur + prev for s in d['shots']], cat, lie, None)
        by_club = {}
        for s in all_cat:
            if s['club'] and s.get('wind_kph') is not None:
                by_club.setdefault(s['club'], []).append(s)
        from app.utils.clubs import sort_clubs, club_label
        for club in sort_clubs(by_club):
            calm = [s for s in by_club[club] if s['wind_kph'] < WINDY_KPH]
            windy = [s for s in by_club[club] if s['wind_kph'] >= WINDY_KPH]
            if calm and windy:
                wind_rows.append({'club': club_label(club), 'calm': _per(calm), 'windy': _per(windy)})

    # KPI extras
    extra = None
    if cat == 'ott':
        tee = [s for s in cur_shots if s['type'] == 'ott']
        fw = sum(1 for s in tee if s['result'] == 'fairway')
        travel = [s['travel'] for s in tee if s.get('travel') and s['result'] != 'penalty']
        extra = [('Fairways', f'{round(fw / len(tee) * 100)}%' if tee else '—', f'{fw}/{len(tee)} tee shots'),
                 ('Avg tee shot', f"{round(sum(travel) / len(travel))}y" if travel else '—', 'estimated')]
    elif cat == 'putt':
        holed = [s for s in cur_shots if s['holed']]
        extra = [('Putts / round', f"{sum(1 for _, d in cur for s in d['shots'] if s['type'] in ('putt', 'gimme')) / len(cur):.1f}"
                  if cur else '—', f'last {len(cur)} rounds'),
                 ('One-putts', str(len(holed)), 'holed first putt')]
    else:
        dists = [s['dist'] for s in cur_shots if s['dist']]
        extra = [('Avg distance', f"{round(sum(dists) / len(dists))}y" if dists else '—', 'to the flag'),
                 ('Shots', str(n), f'last {len(cur)} rounds')]

    return render_template(
        'analytics/category.html',
        cat=cat, cfg=cfg, pages=PAGES, labels=CATEGORY_LABELS,
        per=per, n=n, delta=(per - pper) if (per is not None and pper is not None and pn >= 15) else None,
        per_round=round(sum(per_round_totals) / len(per_round_totals), 2) if per_round_totals else None,
        rounds_n=len(cur), heat=heat, cols=[r.date_played.strftime('%d/%m') for r, _ in cols],
        insight=insight, trend=trend, tables=tables, heat_rows=heat_rows_detail,
        wind_rows=wind_rows, extra=extra, lie=lie, wind=wind, windy_kph=WINDY_KPH,
    )


@analytics_bp.route('/off-the-tee')
@login_required
def off_the_tee():
    return _category_page('ott')


@analytics_bp.route('/approach')
@login_required
def approach():
    return _category_page('app')


@analytics_bp.route('/around-the-green')
@login_required
def around_green():
    return _category_page('atg')


@analytics_bp.route('/putting')
@login_required
def putting():
    return _category_page('putt')

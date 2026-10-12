from flask import Blueprint, render_template, abort, make_response, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.utils.access import is_pro
from app.models.report import Report
from app.models.round import Round
from app.utils.strokes_gained import normalize_to_18, _parse_yards
from app.utils.round_stats import build_course_hole_map, compute_all_stats, CURRENT_ALGO_VERSION
from app.utils.shot_sg import CATEGORIES, CATEGORY_LABELS
from app.utils import sg_breakdown as bd
from app.utils import sg_evidence as ev
from app.utils.clubs import club_label
from app.utils.round_history import shots_for_round, history, per_shot_averages
from app.utils.personal_bests import check_recent_personal_best
from app.services.weather_service import get_round_weather
from app.services.calendar_service import get_calendar_context
from app.services.claude_service import generate_narrative, generate_context_summary

import logging
logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)

# Bump whenever the coaching prompt changes significantly: any cached narrative
# with a lower version is regenerated on the next report view.
NARRATIVE_VERSION = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_label(diff) -> str:
    """Return 'E', '+3', '-1' etc. from score-vs-par integer."""
    if diff is None:
        return '—'
    if diff == 0:
        return 'E'
    return f'+{diff}' if diff > 0 else str(diff)


def _hole_score_class(diff: int) -> str:
    if diff <= -2:
        return 'eagle'
    if diff == -1:
        return 'birdie'
    if diff == 0:
        return 'par'
    if diff == 1:
        return 'bogey'
    return 'double'


def _build_holes_data(holes, course_hole_map: dict) -> list:
    """Per-hole context list used by the scorecard."""
    result = []
    for h in holes:
        ch = course_hole_map.get(h.hole_number)
        diff = h.score - h.par
        result.append({
            'hole_number':         h.hole_number,
            'par':                 h.par,
            'yardage':             ch.yardage if ch else None,
            'stroke_index':        ch.stroke_index if ch else None,
            'score':               h.score,
            'score_vs_par':        diff,
            'score_class':         _hole_score_class(diff),
            'score_label':         h.score_label,
            'tee_shot':            h.tee_shot,
            'gir':                 h.gir,
            'putts':               h.putts,
            'first_putt_distance': h.first_putt_distance,
            'approach_distance':   h.approach_distance,
            'scramble_distance':   h.scramble_distance,
            'penalties':           h.penalties,
        })
    return result


def _split_totals(holes_data: list) -> dict:
    """Front 9 / back 9 / total summary rows."""
    def _sum(subset):
        s = {
            'score': sum(h['score'] for h in subset),
            'par':   sum(h['par'] for h in subset),
            'putts': sum(h['putts'] or 0 for h in subset),
            'gir':   sum(1 for h in subset if h['gir']),
        }
        s['score_vs_par'] = s['score'] - s['par']
        s['score_label'] = _score_label(s['score_vs_par'])
        return s
    front = [h for h in holes_data if h['hole_number'] <= 9]
    back = [h for h in holes_data if h['hole_number'] >= 10]
    return {
        'front': _sum(front) if front else None,
        'back':  _sum(back) if back else None,
        'total': _sum(holes_data),
    }


def _scramble_stats(holes_data: list) -> dict:
    """Scramble (par-or-better save rate) from GIR misses."""
    misses = [h for h in holes_data if not h['gir']]
    if not misses:
        return {'attempts': 0, 'saves': 0, 'save_pct': None}
    saves = sum(1 for h in misses if h['score_vs_par'] <= 0)
    return {'attempts': len(misses), 'saves': saves, 'save_pct': round(saves / len(misses) * 100)}


def _build_historical_context(round_, prev_rounds: list) -> dict:
    """
    Historical baseline data for the coaching narrative prompt.

    Round-level SG averages are on an 18-hole basis so rounds of different
    lengths compare fairly; they are always labelled as such in the prompt.
    """
    round_count = len(prev_rounds) + 1
    ctx = {'round_count': round_count}

    for cat in ('sg_off_tee', 'sg_approach', 'sg_atg', 'sg_putting'):
        vals = [normalize_to_18(getattr(r, cat), r.holes_played)
                for r in prev_rounds if getattr(r, cat) is not None]
        ctx[f'avg_{cat}'] = round(sum(vals) / len(vals), 2) if len(vals) >= 5 else None
        ctx[f'{cat}_count'] = len(vals)

    putts = [r.total_putts for r in prev_rounds if r.total_putts is not None]
    if len(putts) >= 3:
        ctx['avg_total_putts'] = round(sum(putts) / len(putts), 1)
    gir = [r.gir_count / r.holes_played for r in prev_rounds if r.gir_count is not None and r.holes_played]
    if len(gir) >= 3:
        ctx['avg_gir_pct'] = round(sum(gir) / len(gir) * 100, 1)

    if round_count < 20 or not prev_rounds:
        return ctx

    scored = [r for r in prev_rounds if r.total_score is not None]
    svp = [v for v in (r.score_vs_par() for r in scored) if v is not None]
    sgt = [normalize_to_18(r.sg_total, r.holes_played) for r in scored if r.sg_total is not None]
    ctx['avg_score_vs_par'] = round(sum(svp) / len(svp), 1) if svp else None
    ctx['avg_sg_total'] = round(sum(sgt) / len(sgt), 2) if sgt else None
    ctx['avg_putts'] = round(sum(putts) / len(putts), 1) if putts else None
    ctx['recent_scores'] = [
        {'date': r.date_played.strftime('%d %b %Y'),
         'course': r.course.name if r.course else 'Unknown',
         'score_vs_par': r.score_vs_par(),
         'sg_total': normalize_to_18(r.sg_total, r.holes_played)}
        for r in prev_rounds[:5] if r.total_score is not None
    ]
    ctx['recent_differentials'] = [round(r.hc_differential, 1) for r in prev_rounds[:5]
                                   if r.hc_differential is not None]
    return ctx


def _fmt(v, d=2):
    if v is None:
        return '—'
    return ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v):.{d}f}'


def _share_line(rows, total, unit, cat_label):
    """'100–115 yds: −1.92 over 4 shots, 64% of the strokes lost on approach.'"""
    neg = [r for r in rows if r['sg'] < 0]
    if not neg:
        return None
    lost = sum(r['sg'] for r in neg)
    worst = min(neg, key=lambda r: r['sg'])
    noun = 'putt' if unit == 'ft' else 'shot'
    where = f"{worst['label']} {unit}".strip()
    line = f"{where}: {_fmt(worst['sg'])} over {worst['n']} {noun}{'s' if worst['n'] != 1 else ''}"
    if len(neg) > 1:
        line += f", {round(worst['sg'] / lost * 100)}% of the strokes lost on {cat_label}"
    pos = [r for r in rows if r['sg'] > 0]
    if pos:
        best = max(pos, key=lambda r: r['sg'])
        line += f". Best: {(best['label'] + ' ' + unit).strip()} at {_fmt(best['per'])} per {noun}"
    return line + '.'


def _shot_text(s):
    """One-line description of a shot for the hole-by-hole log."""
    t = s['type']
    if t == 'ott':
        res = {'fairway': 'Fairway', 'left': 'Left rough', 'right': 'Right rough', 'bunker': 'Bunker',
               'trees': 'Trees', 'penalty': 'Penalty', 'unknown': 'Tee shot'}.get(s['result'], 'Tee shot')
        return f"{int(s['dist'])} yd hole · {res}" if s['dist'] else res
    if t == 'app':
        parts = [f"{int(s['dist'])} yds" if s['dist'] else 'Approach', (s['lie'] or '').title()]
        if s['is_layup']:
            parts.append('Lay-up')
        if s['recovery']:
            parts.append('Recovery')
        if s['miss']:
            parts.append('Missed ' + s['miss'].replace(',', '/'))
        return ' · '.join(p for p in parts if p)
    if t == 'atg':
        return ' · '.join(p for p in [f"{int(s['dist'])} yds" if s['dist'] else 'Chip', (s['lie'] or '').title()] if p)
    if t == 'putt':
        return f"{int(s['ft'])} ft" if s['ft'] else 'Putt (no distance)'
    if t == 'gimme':
        return f"Conceded · {int(s['ft'])} ft"
    return t


_TYPE_LABEL = {'ott': 'Tee', 'app': 'App', 'atg': 'Chip', 'putt': 'Putt', 'gimme': 'Gimme'}


def _hole_rows(round_data, holes_data):
    out = []
    for hd in holes_data:
        res = round_data['holes'].get(hd['hole_number'])
        if not res:
            continue
        shots = []
        for s in res['shots']:
            shots.append({
                'type': _TYPE_LABEL.get(s['type'], s['type']),
                'club': club_label(s['club']) if s['club'] else '',
                'text': _shot_text(s),
                'sg': s['sg'],
                'merged': s['merged'],
                'n_strokes': s['n_strokes'],
                'penalty': s['penalty'],
            })
        out.append({**hd, 'sg': round(res['sg_total'], 2), 'complete': res['complete'], 'shots': shots})
    return out


def _waterfall(round_data, cats_allowed):
    """
    Expected-score walk for fully measured holes:
    Tour expects X → strokes lost per category → your score on those holes.
    """
    measured = round_data['measured']
    if not measured['holes']:
        return None
    per_cat = {c: 0.0 for c in CATEGORIES}
    for res in round_data['holes'].values():
        if not res['complete']:
            continue
        for s in res['shots']:
            if s['sg'] is not None:
                per_cat[s['cat']] += s['sg']
    exp, score = measured['expected'], measured['score']
    steps, run = [], exp
    for c in CATEGORIES:
        if c not in cats_allowed:
            continue
        lost = -per_cat[c]
        steps.append({'cat': c, 'label': CATEGORY_LABELS[c], 'value': round(lost, 2),
                      'start': run, 'end': run + lost})
        run += lost
    lo = min([exp, score] + [min(s['start'], s['end']) for s in steps])
    hi = max([exp, score] + [max(s['start'], s['end']) for s in steps])
    lo, hi = int(lo) - 1, int(hi) + 2
    span = max(hi - lo, 1)
    pct = lambda v: round((v - lo) / span * 100, 2)
    for s in steps:
        a, b = sorted((s['start'], s['end']))
        s['left'] = pct(a)
        s['width'] = max(round(pct(b) - pct(a), 2), 0.6)
        s['link'] = pct(s['end'])
    ticks = list(range(lo, hi + 1, max(1, span // 4)))
    return {
        'expected': round(exp, 1), 'score': score, 'steps': steps,
        'exp_pct': pct(exp), 'score_pct': pct(score),
        'ticks': [{'v': t, 'pct': pct(t)} for t in ticks],
        'holes': measured['holes'], 'holes_total': measured['holes_total'],
        'complete': measured['holes'] == measured['holes_total'],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@reports_bp.route('/<int:round_id>')
@login_required
def view_report(round_id):
    """
    Live round report assembled from per-shot strokes gained.

    Legacy reports are refreshed on view: stale stored stats (algo_version
    behind CURRENT_ALGO_VERSION) are recomputed, and a cached narrative from
    an older prompt version is regenerated.
    """
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    report = round_.report
    if not report:
        report = Report(round_id=round_.id, email_status='pending')
        db.session.add(report)
        db.session.flush()

    holes = round_.holes.order_by('hole_number').all()
    if not holes:
        abort(404)

    # ── Legacy refresh ────────────────────────────────────────────────────
    if round_.status == 'complete' and (round_.algo_version or 0) < CURRENT_ALGO_VERSION:
        try:
            compute_all_stats(round_)
            report.narrative_text = None
            db.session.flush()
        except Exception as e:
            logger.exception('[view_report] stale recompute failed for round %s: %s', round_.id, e)

    user_is_pro = is_pro(current_user)
    course_hole_map = build_course_hole_map(round_)
    holes_data = _build_holes_data(holes, course_hole_map)
    split = _split_totals(holes_data)
    holes_played = round_.holes_played or len(holes)

    # ── Per-shot SG for this round and the previous 10 ───────────────────
    round_data = shots_for_round(round_)
    shots = round_data['shots']
    prev_rounds = (Round.query
                   .filter(Round.user_id == current_user.id, Round.status == 'complete', Round.id != round_.id)
                   .order_by(Round.date_played.desc()).all())
    _, hist_datas, hist_shots = history(current_user.id, exclude_round_id=round_.id, limit=10,
                                        before=round_.date_played)
    hist_avgs = per_shot_averages(hist_shots)

    sd_by_cat = ev.category_sd(hist_shots + shots)

    # Free tier: only Off the Tee detail is included in the page at all.
    cats_allowed = CATEGORIES if user_is_pro else ('ott',)
    vis_shots = [s for s in shots if s['cat'] in cats_allowed]
    vis_hist = [s for s in hist_shots if s['cat'] in cats_allowed]

    totals = round_data['totals']
    counts = round_data['counts']
    cats = []
    for c in CATEGORIES:
        allowed = c in cats_allowed
        n = counts[c]
        cats.append({
            'cat': c, 'label': CATEGORY_LABELS[c], 'allowed': allowed,
            'total': totals[c] if allowed else None,
            'n': n if allowed else None,
            'per': round(totals[c] / n, 3) if (allowed and n) else None,
            'avg': hist_avgs[c]['per'] if allowed else None,
        })
    for cat in cats:
        if cat['allowed']:
            cat['rel'] = ev.reliability(cat['per'], cat['n'] or 0, sd_by_cat[cat['cat']])
            prev_vals = []
            for _, d in hist_datas:
                k = d['counts'][cat['cat']]
                if k:
                    prev_vals.append(d['totals'][cat['cat']] / k)
            cat['pattern'] = ev.pattern(cat['per'], prev_vals) if cat['per'] is not None else None
    cat_total_n = sum(c['n'] or 0 for c in cats if c['allowed'])
    cat_total_sg = round(sum(c['total'] or 0 for c in cats if c['allowed']), 2)
    sg_total = round_data['sg_total'] if user_is_pro else None
    shots_measured = sum(counts.values())

    # Evidence: how much data sits behind each number, and is it a pattern?
    dims = ('app_dist', 'app_lie', 'app_club', 'ott_club', 'ott_result', 'ott_len',
            'atg_dist', 'atg_lie', 'putt_dist', 'club_all')
    hist_vals = {dim: ev.per_round_values(hist_datas, dim) for dim in dims}
    breakdown = {dim: ev.annotate(bd.rows(vis_shots, dim, vis_hist), sd_by_cat, hist_vals) for dim in dims}
    leaks, strengths = bd.leaks_and_strengths(vis_shots, vis_hist)
    ev.annotate(leaks, sd_by_cat, hist_vals)
    ev.annotate(strengths, sd_by_cat, hist_vals)
    pattern_rounds = [(round_, round_data)] + hist_datas
    if user_is_pro:
        recur_weak, recur_strong = ev.recurring_patterns(pattern_rounds, sd_by_cat)
    else:
        recur_weak, recur_strong = [], []

    insights = {
        'app': _share_line(breakdown['app_dist'], totals['app'], 'yds', 'approach') if user_is_pro else None,
        'atg': _share_line(breakdown['atg_dist'], totals['atg'], 'yds', 'the short game') if user_is_pro else None,
        'putt': _share_line(breakdown['putt_dist'], totals['putt'], 'ft', 'the greens') if user_is_pro else None,
        'ott': _share_line(breakdown['ott_club'], totals['ott'], '', 'tee shots')
               if len(breakdown['ott_club']) > 1 else None,
    }

    hole_rows = _hole_rows(round_data, holes_data)
    if not user_is_pro:
        for hr in hole_rows:
            hr['sg'] = None
            for s in hr['shots']:
                if s['type'] != 'Tee':
                    s['sg'] = None
    hole_sgs = [h['sg'] for h in hole_rows if h['sg'] is not None]
    hole_scale = max([abs(v) for v in hole_sgs] + [1.0])
    # Hole chart geometry: zero line placed in proportion to the biggest gain
    # and biggest loss, so the chart uses its full height and 0 is labelled.
    max_pos = max([v for v in hole_sgs if v > 0] + [0.25])
    max_neg = max([-v for v in hole_sgs if v < 0] + [0.25])
    hchart = {'h': 140, 'zero': round(140 * max_pos / (max_pos + max_neg), 1),
              'max_pos': round(max_pos, 1), 'max_neg': round(max_neg, 1),
              'scale': 140 / (max_pos + max_neg)}
    waterfall = _waterfall(round_data, cats_allowed) if user_is_pro else None

    # Tee shot distances by club (estimated: hole length minus distance left)
    tee_shots = [s for s in shots if s['type'] == 'ott' and s.get('travel') and s['result'] != 'penalty']
    avg_tee_travel = round(sum(s['travel'] for s in tee_shots) / len(tee_shots)) if tee_shots else None

    scramble = _scramble_stats(holes_data)
    gir_pct = round(round_.gir_count / len(holes_data) * 100) if (holes_data and round_.gir_count is not None) else None
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else None

    # ── Context, weather, coaching text ─────────────────────────────────
    weather = get_round_weather(round_)
    calendar_ctx = get_calendar_context(round_.date_played)
    historical_ctx = _build_historical_context(round_, prev_rounds)
    historical_ctx['per_shot_avgs'] = hist_avgs

    sg_data = {
        'sg_off_tee':  totals['ott'],
        'sg_approach': totals['app'] if user_is_pro else None,
        'sg_atg':      totals['atg'] if user_is_pro else None,
        'sg_putting':  {'total': totals['putt'] if user_is_pro else None},
        'sg_total':    sg_total,
    }

    summary_text = narrative = None
    if user_is_pro:
        try:
            summary_text = report.summary_text
            if not summary_text:
                summary_text = generate_context_summary(round_, weather, calendar_ctx)
                report.summary_text = summary_text
            if (report.narrative_version or 0) < NARRATIVE_VERSION:
                report.narrative_text = None
            narrative = report.narrative_text
            if not narrative:
                narrative = generate_narrative(round_, {
                    'holes_played': holes_played,
                    'totals': totals, 'counts': counts, 'sg_total': round_data['sg_total'],
                    'leaks': leaks, 'strengths': strengths, 'waterfall': waterfall,
                }, historical_ctx)
                report.narrative_text = narrative
                if narrative:
                    report.narrative_version = NARRATIVE_VERSION
        except Exception as e:
            logger.exception('[view_report] AI content generation failed: %s', e)
            narrative = report.narrative_text or None

    db.session.commit()

    score_vs_par = round_.score_vs_par()
    par = sum(h['par'] for h in holes_data)
    course_name = round_.course.name if round_.course else 'Unknown Course'
    pb_banner = check_recent_personal_best(round_, prev_rounds)

    return render_template(
        'reports/report.html',
        user_is_pro=user_is_pro,
        round=round_, user=current_user,
        course_name=course_name, par=par,
        score_vs_par=score_vs_par, score_vs_par_label=_score_label(score_vs_par),
        holes_data=holes_data, split=split, holes_played=holes_played,
        cats=cats, cat_by={c['cat']: c for c in cats},
        sg_total=sg_total, sg_pace18=normalize_to_18(sg_total, holes_played) if 9 <= holes_played < 18 else None,
        shots_measured=shots_measured,
        waterfall=waterfall, leaks=leaks, strengths=strengths,
        bd=breakdown, insights=insights,
        hole_rows=hole_rows, hole_scale=hole_scale, hchart=hchart,
        cat_total_n=cat_total_n, cat_total_sg=cat_total_sg,
        recur_weak=recur_weak, recur_strong=recur_strong, pattern_rounds_n=len(pattern_rounds),
        avg_tee_travel=avg_tee_travel,
        scramble=scramble, gir_pct=gir_pct, fw_pct=fw_pct,
        hist_rounds=len(hist_datas),
        weather=weather, summary_text=summary_text, narrative=narrative,
        pb_banner=pb_banner, sg_data=sg_data,
    )


@reports_bp.route('/<int:round_id>/html')
@login_required
def view_report_html(round_id):
    """Serve the legacy generated HTML blob (email preview); else the live report."""
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    report = round_.report
    if not report or not report.html_content:
        return redirect(url_for('reports.view_report', round_id=round_id))
    response = make_response(report.html_content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

"""
Plain-text data context for the coaching narrative and the coach chat.

Everything here is factual data the models can quote directly: the full
shot-by-shot log (distance, lie, club, SG for every shot), SG breakdowns,
per-round summaries with estimated driving distances, and club stats.
"""

from app.utils.clubs import club_label, club_name
from app.utils.shot_sg import CATEGORIES, CATEGORY_LABELS
from app.utils import sg_breakdown as bd
from app.utils.round_history import shots_for_round, history, round_summary


def _f(v, d=2):
    return '—' if v is None else f'{v:+.{d}f}'


def _shot_desc(s, n_in_hole):
    t = s['type']
    club = f" [{club_label(s['club'])}]" if s['club'] else ''
    if t == 'ott':
        res = s['result']
        d = f"{int(s['dist'])}yd hole" if s['dist'] else 'hole length unknown'
        travel = f", est. {s['travel']}yds travelled" if s.get('travel') else ''
        desc = f"Tee shot{club} on {d} → {res}{travel}"
    elif t == 'app':
        start = f"{int(s['dist'])}yds to flag" if s['dist'] else 'distance not logged'
        extra = []
        if s['is_layup']:
            extra.append('lay-up')
        if s['recovery']:
            extra.append('recovery')
        if s['miss']:
            extra.append('missed ' + s['miss'].replace(',', '/'))
        travel = f", est. {s['travel']}yds travelled" if s.get('travel') else ''
        desc = f"Approach{club} from {start}, {s['lie']} lie" + (f" ({', '.join(extra)})" if extra else '') + travel
    elif t == 'atg':
        start = f"{int(s['dist'])}yds" if s['dist'] else 'distance not logged'
        desc = f"Short-game shot{club} from {start}, {s['lie']}"
    elif t == 'putt':
        desc = f"Putt from {int(s['ft'])}ft" if s['ft'] else 'Putt (distance not logged)'
        if s['holed'] and s['n_strokes'] == 1:
            desc += ' — holed'
    elif t == 'gimme':
        desc = f"Conceded putt at {int(s['ft'])}ft"
    else:
        desc = t
    if s['penalty']:
        desc += f" (+{s['penalty']} penalty stroke{'s' if s['penalty'] > 1 else ''})"
    if s['merged']:
        sg = 'valued with previous shot'
    elif s['sg'] is None:
        sg = 'SG n/a (missing distance)'
    else:
        sg = f"SG {s['sg']:+.2f}" + (f" for {s['n_strokes']} strokes" if s['n_strokes'] > 1 else '')
    return f"{desc} | {sg}"


def shot_log_text(round_, data) -> str:
    """Every hole, every shot, numbered in order (shot 1 = tee shot)."""
    lines = []
    for hn in sorted(data['holes']):
        res = data['holes'][hn]
        svp = (res['score'] or 0) - res['par']
        yd = next((s['hole_yardage'] for s in res['shots'] if s.get('hole_yardage')), None)
        lines.append(f"H{hn} par {res['par']}{f' {yd}yds' if yd else ''}: score {res['score']} "
                     f"({'+' if svp > 0 else ''}{svp}), hole SG {res['sg_total']:+.2f}"
                     f"{'' if res['complete'] else ' (partly measured)'}")
        putt_no = 0
        for i, s in enumerate(res['shots'], 1):
            label = ''
            if s['cat'] == 'putt':
                putt_no += 1
                label = f" (putt {putt_no})"
            lines.append(f"    shot {i}{label}: {_shot_desc(s, len(res['shots']))}")
    return '\n'.join(lines)


def _rows_text(title, rows, unit=''):
    if not rows:
        return ''
    out = [title]
    for r in rows:
        extra = []
        if r.get('avg') is not None:
            extra.append(f"previous 10 rounds {r['avg']:+.3f}/shot")
        if r.get('holed') is not None:
            extra.append(f"{r['holed']} holed")
        if r.get('avg_travel'):
            extra.append(f"avg est. {r['avg_travel']}yds")
        if r['clubs'] and r['dim'] not in ('app_club', 'ott_club', 'club_all'):
            extra.append('clubs ' + ', '.join(r['clubs']))
        out.append(f"  {r['label']}{unit}: {r['n']} shots, total {r['sg']:+.2f}, {r['per']:+.3f}/shot"
                   + (f" ({'; '.join(extra)})" if extra else ''))
    return '\n'.join(out)


def breakdown_text(shots, hist_shots=None) -> str:
    parts = [
        _rows_text('Approach SG by distance to flag (yds):', bd.rows(shots, 'app_dist', hist_shots), ' yds'),
        _rows_text('Approach SG by lie:', bd.rows(shots, 'app_lie', hist_shots)),
        _rows_text('Approach SG by club:', bd.rows(shots, 'app_club', hist_shots)),
        _rows_text('Tee shot SG by club:', bd.rows(shots, 'ott_club', hist_shots)),
        _rows_text('Tee shot SG by result:', bd.rows(shots, 'ott_result', hist_shots)),
        _rows_text('Tee shot SG by hole length (yds):', bd.rows(shots, 'ott_len', hist_shots)),
        _rows_text('Short game SG by distance (yds):', bd.rows(shots, 'atg_dist', hist_shots), ' yds'),
        _rows_text('Short game SG by lie:', bd.rows(shots, 'atg_lie', hist_shots)),
        _rows_text('Putting SG by first-putt distance (ft):', bd.rows(shots, 'putt_dist', hist_shots), ' ft'),
    ]
    return '\n'.join(p for p in parts if p)


def summary_line(s) -> str:
    vp = s['vs_par']
    vp = 'E' if vp == 0 else (f'+{vp}' if vp and vp > 0 else str(vp))
    sg = ', '.join(f"{CATEGORY_LABELS[c]} {s['sg'][c]:+.2f}" for c in CATEGORIES)
    drive = []
    if s['avg_driver_travel']:
        drive.append(f"avg driver {s['avg_driver_travel']}yds")
    if s['avg_tee_travel']:
        drive.append(f"avg tee shot {s['avg_tee_travel']}yds")
    if s['longest_tee_travel']:
        drive.append(f"longest {s['longest_tee_travel']}yds")
    return (f"{s['date']} {s['course']} ({s['holes']} holes): {s['score']} ({vp}), putts {s['putts']}, "
            f"fairways {s['fairways'] or '—'}, GIR {s['gir']}; SG total {s['sg_total']:+.2f} "
            f"over those {s['holes']} holes ({sg})" + (f"; {', '.join(drive)}" if drive else ''))


def club_stats_text(shots) -> str:
    rows = bd.rows(shots, 'club_all')
    if not rows:
        return ''
    lines = ['Club stats:']
    for r in rows:
        travel = [s['travel'] for s in bd.aggregate(shots, 'club_all').get(r['key'], {}).get('shots', []) if s.get('travel')]
        avg_t = f", avg est. {round(sum(travel) / len(travel))}yds travelled" if travel else ''
        lines.append(f"  {club_name(r['key'])}: {r['n']} shots, {r['per']:+.3f} SG/shot{avg_t}")
    return '\n'.join(lines)


def round_context(round_, n_previous=5) -> str:
    """Full data context for one round plus a comparison set of previous rounds."""
    data = shots_for_round(round_)
    _, hist, hist_shots = history(round_.user_id, exclude_round_id=round_.id, limit=10, before=round_.date_played)
    this = round_summary(round_, data)
    prev_lines = [summary_line(round_summary(r, d)) for r, d in hist[:n_previous]]
    totals = data['totals']
    counts = data['counts']
    sg_lines = '\n'.join(
        f"  {CATEGORY_LABELS[c]}: {totals[c]:+.2f} over {counts[c]} valued shots"
        f" ({(totals[c] / counts[c]) if counts[c] else 0:+.3f}/shot)" for c in CATEGORIES)
    m = data['measured']
    return f"""THIS ROUND — {summary_line(this)}

STROKES GAINED vs PGA Tour for the {round_.holes_played} holes actually played (NOT scaled to 18 holes):
{sg_lines}
  Total: {data['sg_total']:+.2f}
Fully measured holes: {m['holes']} of {m['holes_total']}. On those holes a Tour pro would expect {m['expected']:.1f} strokes; the golfer took {m['score']}.

SHOT-BY-SHOT LOG (distances are to the flag at the START of each shot; 'est. travelled' = start distance minus distance left)
{shot_log_text(round_, data)}

BREAKDOWNS FOR THIS ROUND (with the golfer's previous-10-round average per shot where available)
{breakdown_text(data['shots'], hist_shots)}

{club_stats_text(data['shots'])}

PREVIOUS ROUNDS (most recent first)
{chr(10).join(prev_lines) if prev_lines else '(none)'}

{club_stats_text(hist_shots).replace('Club stats:', 'Club stats over the previous 10 rounds:')}"""


def profile_context(user, limit=20, logs=5) -> str:
    """Whole-history context for the general coach chat."""
    _, hist, hist_shots = history(user.id, limit=limit)
    lines = [summary_line(round_summary(r, d)) for r, d in hist]
    logs_txt = []
    for r, d in hist[:logs]:
        logs_txt.append(f"--- {r.date_played.strftime('%d %b %Y')} {r.course.name if r.course else ''} ---\n"
                        f"{shot_log_text(r, d)}")
    return f"""ROUNDS ON FILE (most recent first, SG for holes actually played)
{chr(10).join(lines) if lines else '(no completed rounds yet)'}

BREAKDOWNS ACROSS THESE ROUNDS
{breakdown_text(hist_shots)}

{club_stats_text(hist_shots)}

SHOT-BY-SHOT LOGS FOR THE {min(logs, len(hist))} MOST RECENT ROUNDS
{chr(10).join(logs_txt)}"""

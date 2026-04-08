"""
Claude API service for Magnolia Analytics.

Two entry points:

  generate_report(round_)
    Called immediately after a round is completed (from rounds.py).
    Creates/updates the Report record and generates html_content for email
    delivery. Uses a lightweight placeholder if no API key is set.

  generate_narrative(round_, sg_data, historical_ctx)
    Called lazily on first report page view (from reports.py).
    Generates a multi-paragraph plain-text coaching narrative and caches it in
    Report.narrative_text. On failure, writes a graceful fallback string so
    the page always renders cleanly.
"""

import os
import time
from datetime import datetime
from flask import current_app
from app import db
from app.models.report import Report

_MODEL = 'claude-sonnet-4-20250514'

# ---------------------------------------------------------------------------
# Internal helpers — report generation (email / legacy HTML blob)
# ---------------------------------------------------------------------------

def _build_report_prompt(round_) -> str:
    """Prompt for the legacy full-HTML email report — aggregated stats only."""
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'

    score_vs_par = round_.score_vs_par()
    score_label = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else str(score_vs_par or 'E')
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    holes_played = round_.holes_played or 18
    gir_pct = round(round_.gir_count / holes_played * 100) if round_.gir_count is not None else 0

    sg_off_tee = round_.sg_off_tee or 0
    sg_approach = round_.sg_approach or 0
    sg_atg = round_.sg_atg or 0
    sg_putting = round_.sg_putting or 0
    sg_total = round_.sg_total or 0

    return f"""You are the performance analysis engine for Magnolia Analytics, a premium golf tracking platform.

ROUND SUMMARY
-------------
Golfer: {user.full_name} (Handicap {user.handicap_index})
Course: {course_name}
Date: {round_.date_played.strftime('%d %B %Y')}
Score: {round_.total_score} ({score_label} par)
Putts: {round_.total_putts}
FIR: {round_.fairways_hit}/{round_.fairways_available} ({fw_pct}%)
GIR: {round_.gir_count}/{holes_played} ({gir_pct}%)
Penalties: {round_.penalties}

STROKES GAINED
--------------
Off Tee:      {sg_off_tee:+.2f}
Approach:     {sg_approach:+.2f}
Around Green: {sg_atg:+.2f}
Putting:      {sg_putting:+.2f}
Total:        {sg_total:+.2f}

TASK
----
Write a concise HTML round summary. Output only a <div> fragment (no DOCTYPE, no <html>/<body> wrapper).
Use inline styles only. Dark green (#1a2e1a) for headings, gold (#c9a84c) for accents.
Include: score headline, four stat cards (score vs par, FIR, GIR, putts), strokes gained bar summary, one coaching paragraph (2–3 sentences, data-grounded).
Keep total output under 800 words of HTML.
Begin immediately with <div>."""


def _placeholder_html(round_) -> str:
    """Lightweight placeholder HTML for email when no API key is set."""
    score_vs_par = round_.score_vs_par()
    score_label = (
        f'+{score_vs_par}' if score_vs_par and score_vs_par > 0
        else (str(score_vs_par) if score_vs_par is not None else 'E')
    )
    course_name = round_.course.name if round_.course else 'Unknown Course'
    date_str = round_.date_played.strftime('%d %B %Y')
    user = round_.golfer
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    gir_pct = round(round_.gir_count / 18 * 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Round Report — {date_str}</title>
<style>
  body {{ font-family: 'DM Sans', Arial, sans-serif; background: #f5f0e8; color: #1a1a1a; margin: 0; padding: 0; }}
  .header {{ background: #1a2e1a; padding: 2.5rem 3rem; color: #fdfcf8; }}
  .header h1 {{ font-size: 1.8rem; margin: 0 0 0.3rem; }}
  .header .score {{ font-size: 4rem; color: #e8c97a; font-weight: 700; line-height: 1; }}
  .body {{ padding: 2rem 3rem; max-width: 760px; margin: 0 auto; }}
  .grid {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 1rem; margin: 1.5rem 0; }}
  .card {{ background: #fff; border-left: 3px solid #5a9e5a; padding: 1.2rem; border-radius: 3px; }}
  .card .val {{ font-size: 2rem; font-weight: 700; color: #1a2e1a; }}
  .card .lbl {{ font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.15em; color: #4a4a4a; margin-top: 0.3rem; }}
  .note {{ background: #1a2e1a; color: rgba(255,255,255,0.7); padding: 1.5rem 2rem; border-radius: 3px; margin-top: 1.5rem; font-size: 0.9rem; line-height: 1.7; }}
  .note strong {{ color: #e8c97a; }}
  .footer {{ background: #1a2e1a; color: rgba(255,255,255,0.3); text-align: center; padding: 1rem; font-size: 0.65rem; letter-spacing: 0.15em; margin-top: 2rem; }}
</style>
</head>
<body>
<div class="header">
  <div style="font-size:0.6rem;letter-spacing:0.3em;color:#c9a84c;text-transform:uppercase;margin-bottom:0.8rem">Magnolia Analytics · Round Report</div>
  <h1>Round at <em style="color:#e8c97a">{course_name}</em></h1>
  <div class="score">{round_.total_score}</div>
  <div style="font-size:0.7rem;color:rgba(255,255,255,0.4);letter-spacing:0.15em;margin-top:0.3rem">{score_label} PAR · {date_str} · {user.full_name}</div>
</div>
<div class="body">
  <div class="grid">
    <div class="card" style="border-left-color:#c9a84c">
      <div class="val" style="color:#c9a84c">{score_label}</div>
      <div class="lbl">Score vs Par</div>
    </div>
    <div class="card">
      <div class="val">{round_.fairways_hit}/{round_.fairways_available}</div>
      <div class="lbl">Fairways Hit ({fw_pct}%)</div>
    </div>
    <div class="card">
      <div class="val">{round_.gir_count}/18</div>
      <div class="lbl">GIR ({gir_pct}%)</div>
    </div>
    <div class="card">
      <div class="val">{round_.total_putts}</div>
      <div class="lbl">Total Putts</div>
    </div>
  </div>
  <div class="note">
    <strong>Your round data has been saved.</strong><br>
    Add your Anthropic API key to activate the full personalised coaching report — strokes gained breakdown, putting analysis, narrative, and practice priorities.
  </div>
</div>
<div class="footer">Magnolia Analytics · Track every shot. Understand every round.</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API — round completion (email / legacy)
# ---------------------------------------------------------------------------

def generate_report(round_) -> Report:
    """
    Create or update the Report record for a completed round.
    Generates html_content for email delivery.
    Called from rounds.py immediately after round submission.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    html_content = None
    prompt_tokens = 0
    completion_tokens = 0
    model_used = 'placeholder'

    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt_text = _build_report_prompt(round_)
            current_app.logger.info(
                '[claude] generate_report start prompt=%d chars model=%s',
                len(prompt_text), _MODEL
            )
            t0 = time.time()
            msg = client.messages.create(
                model=_MODEL,
                max_tokens=1500,
                messages=[{'role': 'user', 'content': prompt_text}]
            )
            elapsed = time.time() - t0
            current_app.logger.info(
                '[claude] generate_report done elapsed=%.1fs input_tokens=%d output_tokens=%d',
                elapsed, msg.usage.input_tokens, msg.usage.output_tokens
            )
            html_content = msg.content[0].text
            prompt_tokens = msg.usage.input_tokens
            completion_tokens = msg.usage.output_tokens
            model_used = _MODEL
        except Exception as e:
            current_app.logger.exception('[claude] generate_report api error: %s', e)
            html_content = None
            model_used = f'placeholder (api error: {str(e)[:80]})'

    if not html_content:
        html_content = _placeholder_html(round_)

    is_new = round_.report is None
    report = round_.report or Report(round_id=round_.id)
    report.html_content = html_content
    report.prompt_tokens = prompt_tokens
    report.completion_tokens = completion_tokens
    report.model_used = model_used
    report.generated_at = datetime.utcnow()
    if is_new:
        report.email_status = 'pending'
    # Don't reset email_status for existing reports — preserves 'sent' on re-edit

    db.session.add(report)
    db.session.commit()

    return report


# ---------------------------------------------------------------------------
# Public API — narrative (live report page, lazy-loaded on first view)
# ---------------------------------------------------------------------------

_NARRATIVE_FALLBACK = (
    "Your round data has been saved and your stats are live above. "
    "To activate the personalised coaching narrative, add your Anthropic API key "
    "as the ANTHROPIC_API_KEY environment variable and reload this page."
)


def _build_narrative_prompt(round_, sg_data: dict, historical_ctx: dict) -> str:
    """
    Build the comprehensive coaching narrative prompt.

    historical_ctx keys:
      round_count              — int, total completed rounds including this one
      avg_score_vs_par         — float or None  (only if round_count >= 20)
      avg_sg_total             — float or None
      avg_putts                — float or None
      avg_gir_pct              — float or None
      recent_scores            — list of {date, course, score_vs_par, sg_total}
      recent_differentials     — list of floats
    """
    holes = round_.holes.all()
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'

    # Hole summary
    # IMPORTANT: All distance values (ApprDist, 2ndShotDist) represent the
    # distance the player was FROM THE HOLE at the start of that shot —
    # NOT how far the ball travelled. Example: holing out from 180 yards means
    # ApprDist=180 (starting distance to hole), not the shot carry distance.
    hole_lines = []
    for h in holes:
        svp = h.score - h.par
        label = {-2: 'Eagle', -1: 'Birdie', 0: 'Par', 1: 'Bogey',
                 2: 'Double', 3: 'Triple'}.get(svp, f'+{svp}')
        hole_lines.append(
            f"  H{h.hole_number:02d} Par{h.par}: {h.score} ({label}) | "
            f"Tee:{h.tee_shot or '–'} GIR:{'Y' if h.gir else 'N'} "
            f"Putts:{h.putts} FPD:{h.first_putt_distance or '?'}ft "
            f"ApprDist:{h.approach_distance or '?'}yds(dist-to-hole) "
            f"Miss:{h.approach_miss or '–'} Lie:{h.lie_type or '–'} "
            f"2ndDist:{h.second_shot_distance or '–'}yds(dist-to-hole) Pen:{h.penalties}"
        )

    # SG values — sg_putting is a dict with 'total' key
    sg_putting   = sg_data.get('sg_putting', {})
    sg_off_tee   = sg_data.get('sg_off_tee', 0) or 0
    sg_approach  = sg_data.get('sg_approach', 0) or 0
    sg_atg       = sg_data.get('sg_atg', 0) or 0
    sg_put_total = (sg_putting.get('total', 0) if isinstance(sg_putting, dict) else sg_putting) or 0
    sg_total     = sg_data.get('sg_total', 0) or 0

    score_vs_par  = round_.score_vs_par()
    score_label   = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else str(score_vs_par or 'E')
    fw_pct        = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    holes_played  = round_.holes_played or len(holes)
    gir_pct       = round(round_.gir_count / holes_played * 100) if holes_played else 0

    round_count = historical_ctx.get('round_count', 1)

    # Historical baseline section — only included when >= 20 rounds
    historical_section = ''
    if round_count >= 20:
        avg_svp   = historical_ctx.get('avg_score_vs_par')
        avg_sg    = historical_ctx.get('avg_sg_total')
        avg_putt  = historical_ctx.get('avg_putts')
        avg_gir   = historical_ctx.get('avg_gir_pct')
        rec_diffs = historical_ctx.get('recent_differentials', [])
        rec_scores = historical_ctx.get('recent_scores', [])

        def _svp(v):
            if v is None: return '?'
            return f'+{v:.1f}' if v > 0 else f'{v:.1f}'

        rec_lines = '\n'.join(
            f"  {r['date']} — {r['course']}: {_svp(r.get('score_vs_par'))} par"
            + (f", SG {r['sg_total']:+.2f}" if r.get('sg_total') is not None else '')
            for r in rec_scores
        ) or '  (none)'

        historical_section = f"""
HISTORICAL BASELINE  ({round_count} completed rounds)
------------------------------------------------------
Avg score vs par:        {_svp(avg_svp)}
Avg SG total:            {f'{avg_sg:+.2f}' if avg_sg is not None else '—'}
Avg putts per round:     {avg_putt if avg_putt is not None else '—'}
Avg GIR rate:            {f'{avg_gir:.1f}%' if avg_gir is not None else '—'}
Recent HC differentials: {', '.join(str(d) for d in rec_diffs) if rec_diffs else '—'}

Last 5 rounds:
{rec_lines}
"""

    # Sample-size conditional instructions
    if round_count < 20:
        sample_guidance = f"""SAMPLE SIZE: {round_count} round(s) recorded — history is limited.
- Do not draw any conclusions about handicap trend; the sample is too small
- Do not compare score to handicap index in a meaningful way; omit it entirely
- Focus entirely on shot patterns, directional tendencies, and immediately actionable observations
- Acknowledge once, briefly, that observations are early-stage — do not repeat this caveat"""
    else:
        sample_guidance = f"""SAMPLE SIZE: {round_count} rounds recorded — full historical analysis is valid.
- Compare key stats from this round to the player's historical averages in the section above
- State whether this round is above, below, or in line with their established baseline
- Handicap trend (improving / plateauing / declining) is valid to mention, based on recent differentials
- Score vs handicap is one data point only — do not lead with it; SG and shot patterns take priority"""

    return f"""You are the coaching analyst for Magnolia Analytics, a performance tracking platform for amateur golfers.

ROUND SUMMARY
-------------
Golfer:    {user.full_name} (HC Index {user.handicap_index})
Course:    {course_name}
Date:      {round_.date_played.strftime('%d %B %Y')}
Score:     {round_.total_score} ({score_label} vs par)
Putts:     {round_.total_putts}
FIR:       {round_.fairways_hit}/{round_.fairways_available} ({fw_pct}%)
GIR:       {round_.gir_count}/{holes_played} ({gir_pct}%)
Penalties: {round_.penalties}

STROKES GAINED  (0 = scratch handicap baseline)
------------------------------------------------
SG Off Tee:      {sg_off_tee:+.2f}
SG Approach:     {sg_approach:+.2f}
SG Around Green: {sg_atg:+.2f}
SG Putting:      {sg_put_total:+.2f}
SG Total:        {sg_total:+.2f}

HOLE-BY-HOLE (all distances = distance FROM THE HOLE at start of shot, not ball travel distance)
-------------------------------------------------------------------------------------------------
Key: Tee=tee shot | GIR=green in regulation | FPD=first putt distance |
ApprDist=approach dist-to-hole | Miss=approach miss direction(s) | Lie=lie type at miss |
2ndDist=2nd shot dist-to-hole (par 5s) | Pen=penalty strokes
{chr(10).join(hole_lines)}
{historical_section}
{sample_guidance}

ANALYTICAL INSTRUCTIONS — follow all sections:

1. SG ANALYSIS
- Lead with whichever SG category had the largest impact this round (most positive or most negative)
- For each SG figure state whether it is above, at, or below scratch (0 = scratch level)
- If any category lacks sufficient data, acknowledge the gap — do not fabricate insight
- Back up every SG claim with specific hole evidence from the data above

2. MISS PATTERN ANALYSIS
- Systematically examine the Miss and Lie columns for directional bias
- Cross-reference miss direction with lie type: the same miss repeatedly landing in the same lie type is a named pattern
- Two or more identical misses = a recurring pattern worth highlighting; a single miss = note it, do not over-weight it
- Check whether miss tendencies differ by par type (par 3 vs par 4 vs par 5) and name it if they do

3. PAR 5 PERFORMANCE (only if the round contains par 5s)
- Assess whether par 5s were scoring opportunities or weaknesses based on actual scores
- Use the 2nd column where populated to infer lay-up vs attacking strategy
- Cross-reference GIR and score: reaching the green but not making birdie is a missed opportunity

4. CONSISTENCY AND ROUND FLOW
- Note whether bogeys and birdies were clustered or spread across the round
- For 18-hole rounds: comment on front vs back 9 split if they differ materially
- Identify any blow-up holes (double bogey or worse) and trace their cause from the hole data
- Assess variance: controlled scoring (pars and single bogeys) vs boom/bust

5. PRACTICE RECOMMENDATIONS (end of narrative, exactly 2–3)
- Rank by impact: biggest SG drain or most frequent miss pattern goes first
- Be specific: cite hole numbers, shot counts, or distance bands from the data
- If the data is insufficient for a specific recommendation, say so; do not substitute generic advice
- Write as a coach speaking directly to the player, not as a data summary

TONE RULES
- Knowledgeable, direct, honest — encouraging only when the data genuinely warrants it
- No filler praise ("great round", "well done on your GIR") unless this round is objectively strong by the numbers
- Never repeat the same observation across paragraphs
- Vary sentence structure; avoid chains of "your X was Y" constructions
- Write as if you watched the round, not as if you scanned a scorecard
- Do not reference weather, temperature, wind, or external conditions unless the user has explicitly noted them in the round data
- Do not compare score to handicap as a primary metric; use strokes gained as the primary analytical lens
- If fewer than 20 rounds of history exist, focus analysis on the current round's shot data only; do not draw handicap trend conclusions
- Write in direct, plain sentences; do not use hedging language or qualify every observation with uncertainty

OUTPUT
Write 4–5 paragraphs of plain text, separated by blank lines. No markdown, no HTML, no bullet points, no section headers.

Para 1 — Round character and SG overview: what defined this round and how did each SG category perform vs scratch baseline?
Para 2 — Shot pattern and miss analysis: directional tendencies, lie context, any par-type differences
Para 3 — Par 5 performance (if applicable) and round consistency / flow
Para 4 — Historical context: {'compare to established baseline and comment on trend' if round_count >= 20 else 'one sentence acknowledging early-stage observations; do not pad'}
Para 5 — 2–3 specific, ranked practice recommendations

Begin immediately."""


def generate_context_summary(round_, weather, calendar_ctx: dict) -> str:
    """
    Generate a 2-3 sentence context summary for the top of the round report.

    Covers conditions, season/date context, and what the score means given
    the golfer's handicap. Cached in Report.summary_text on first view.
    Caller must commit the DB session.

    Returns the summary string (or a safe fallback on any failure).
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return ''   # empty string → card is hidden in template

    user        = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'
    score_vs_par = round_.score_vs_par()
    score_label  = (
        f'+{score_vs_par}' if score_vs_par and score_vs_par > 0
        else ('E' if score_vs_par == 0 else str(score_vs_par))
    )

    weather_str = 'Weather data not available for this round.'
    if weather:
        parts = [f"{weather['condition']}", f"{weather['temp_c']}°C",
                 f"wind {weather['wind_kph']} km/h"]
        if weather.get('precip_mm', 0) > 0:
            parts.append(f"{weather['precip_mm']}mm rain")
        weather_str = ', '.join(parts)

    ctx_parts = []
    if calendar_ctx.get('golf_event'):
        ctx_parts.append(calendar_ctx['golf_event'])
    if calendar_ctx.get('bank_holiday'):
        ctx_parts.append(calendar_ctx['bank_holiday'])
    if calendar_ctx.get('notable'):
        ctx_parts.append(calendar_ctx['notable'])
    calendar_str = '; '.join(ctx_parts) if ctx_parts else 'No notable calendar context'

    prompt = f"""You are writing a brief round context for a golfer's performance report.

Write exactly 2-3 sentences of context. Use second person ("Your round at...").

Round data:
Course: {course_name}
Date: {round_.date_played.strftime('%d %B %Y')}
Score: {score_label} vs par ({round_.total_score} gross)
Handicap Index: {user.handicap_index}
Season: {calendar_ctx.get('season', 'Unknown')}
Calendar: {calendar_str}
Conditions: {weather_str}

Rules:
- Exactly 2-3 sentences. No lists, no headers, no markdown.
- Second person throughout.
- If weather is available, comment specifically on how it affected play (temperature, wind).
- Reference the season, course, and how the score sits relative to the golfer's handicap.
- Tone: warm and direct, like a knowledgeable friend after the round. No clichés.
- Do not mention any software, platforms, or that this text was generated.

Output only the sentences. Begin immediately."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        summary = msg.content[0].text.strip()

        report = round_.report
        if report:
            report.summary_text = summary
            report.model_used = _MODEL
            report.prompt_tokens     = (report.prompt_tokens or 0) + msg.usage.input_tokens
            report.completion_tokens = (report.completion_tokens or 0) + msg.usage.output_tokens
            report.generated_at = datetime.utcnow()

        return summary

    except Exception as e:
        return ''   # empty string → card hidden; don't expose error in UI


def generate_narrative(round_, sg_data: dict, historical_ctx: dict) -> str:
    """
    Generate and cache a coaching narrative for the round.

    Called on first report page view. Result is saved to Report.narrative_text
    so subsequent views are instant. Caller must commit the DB session.

    historical_ctx: assembled by reports._build_historical_context — contains
    round count, historical averages, and recent form (when >= 20 rounds exist).

    Returns the narrative string (either from Claude or the fallback).
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')

    if not api_key:
        return _NARRATIVE_FALLBACK

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=900,
            messages=[{
                'role': 'user',
                'content': _build_narrative_prompt(round_, sg_data, historical_ctx)
            }]
        )
        narrative = msg.content[0].text.strip()

        # Update report metadata
        report = round_.report
        if report:
            report.narrative_text = narrative
            report.model_used = _MODEL
            report.prompt_tokens = (report.prompt_tokens or 0) + msg.usage.input_tokens
            report.completion_tokens = (report.completion_tokens or 0) + msg.usage.output_tokens
            report.generated_at = datetime.utcnow()
            # Caller commits

        return narrative

    except Exception as e:
        fallback = (
            f"Your round data has been saved. "
            f"The personalised coaching narrative could not be generated at this time "
            f"(error: {str(e)[:60]}). Please reload the page to try again."
        )
        return fallback

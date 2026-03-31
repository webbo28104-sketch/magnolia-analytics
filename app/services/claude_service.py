"""
Claude API service for Magnolia Analytics.

Two entry points:

  generate_report(round_)
    Called immediately after a round is completed (from rounds.py).
    Creates/updates the Report record and generates html_content for email
    delivery. Uses a lightweight placeholder if no API key is set.

  generate_narrative(round_, sg_data, weather, calendar_ctx)
    Called lazily on first report page view (from reports.py).
    Generates a 3-paragraph plain-text coaching narrative and caches it in
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


def _build_narrative_prompt(round_, sg_data: dict, weather, calendar_ctx: dict) -> str:
    """
    Build the prompt for the 3-paragraph narrative.
    Passes all assembled stats so Claude can write specific, data-led coaching.
    """
    holes = round_.holes.all()
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'

    # Hole summary
    hole_lines = []
    for h in holes:
        svp = h.score - h.par
        label = {-2:'Eagle',-1:'Birdie',0:'Par',1:'Bogey',2:'Double',3:'Triple'}.get(svp, f'+{svp}')
        hole_lines.append(
            f"  H{h.hole_number:02d} Par{h.par}: {h.score} ({label}) | "
            f"Tee:{h.tee_shot or'–'} GIR:{'Y' if h.gir else'N'} "
            f"Putts:{h.putts} FPD:{h.first_putt_distance or'?'}ft "
            f"ApprDist:{h.approach_distance or'?'}yds Pen:{h.penalties}"
        )

    # SG summary
    sg_putting = sg_data.get('sg_putting', {})
    sg_lines = (
        f"  SG Off Tee:        {sg_data.get('sg_off_tee', 0):+.2f}\n"
        f"  SG Approach:       {sg_data.get('sg_approach', 0):+.2f}\n"
        f"  SG Around Green:   {sg_data.get('sg_atg', 0):+.2f}\n"
        f"  SG Putting:        {sg_putting.get('total', 0):+.2f}"
    )

    # Context
    score_vs_par = round_.score_vs_par()
    score_label = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else str(score_vs_par or 'E')
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    gir_pct = round(round_.gir_count / 18 * 100)

    weather_str = 'Not available'
    if weather:
        weather_str = (
            f"{weather['condition']}, {weather['temp_c']}°C, "
            f"wind {weather['wind_kph']} km/h, precip {weather['precip_mm']} mm"
        )

    calendar_str = ' | '.join(
        v for v in [
            calendar_ctx.get('golf_event'),
            calendar_ctx.get('bank_holiday'),
            calendar_ctx.get('notable'),
            calendar_ctx.get('season'),
        ] if v
    ) or 'No notable context'

    return f"""You are the coaching analyst for Magnolia Analytics, a premium amateur golf tracking platform.

ROUND SUMMARY
-------------
Golfer:  {user.full_name}  (Handicap {user.handicap_index})
Course:  {course_name}
Date:    {round_.date_played.strftime('%d %B %Y')}
Score:   {round_.total_score} ({score_label} par)
Putts:   {round_.total_putts}
FIR:     {round_.fairways_hit}/{round_.fairways_available} ({fw_pct}%)
GIR:     {round_.gir_count}/18 ({gir_pct}%)
Penalties: {round_.penalties}

STROKES GAINED (estimated)
--------------------------
{sg_lines}

HOLE-BY-HOLE
------------
{chr(10).join(hole_lines)}

CONDITIONS
----------
Weather:  {weather_str}
Calendar: {calendar_str}

TASK
----
Write a coaching narrative of exactly 3 paragraphs (plain text, no markdown, no HTML tags).

Paragraph 1 — What worked: Be specific about the strongest parts of this round. Reference actual hole numbers and shot types. Note any standout stats.
Paragraph 2 — What cost shots: Identify the specific patterns that hurt the score most. Be honest and direct. Reference hole numbers.
Paragraph 3 — One clear priority: Name the single highest-leverage area to work on before the next round and give one concrete practice suggestion.

Rules:
- Plain text only. No bullet points, no headers, no markdown, no HTML.
- Reference specific hole numbers.
- Never be generic. Every sentence must be grounded in the actual data above.
- Tone: a knowledgeable private coach who respects the golfer's intelligence.
- Total length: 150–220 words across the 3 paragraphs.

Output only the 3 paragraphs, separated by a blank line. Begin immediately."""


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


def generate_narrative(round_, sg_data: dict, weather, calendar_ctx: dict) -> str:
    """
    Generate and cache a 3-paragraph coaching narrative for the round.

    Called on first report page view. Result is saved to Report.narrative_text
    so subsequent views are instant. Caller must commit the DB session.

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
            max_tokens=512,
            messages=[{
                'role': 'user',
                'content': _build_narrative_prompt(round_, sg_data, weather, calendar_ctx)
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

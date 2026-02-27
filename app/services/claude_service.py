"""
Claude API service — generates branded HTML performance reports.
Placeholder implementation: replace with live Anthropic SDK call
when your API key is ready.
"""
import os
from datetime import datetime
from app import db
from app.models.report import Report


def _build_prompt(round_) -> str:
    """Construct the report prompt from round + hole data."""
    holes = round_.holes.all()
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'

    hole_data = []
    for h in holes:
        hole_data.append(
            f"Hole {h.hole_number} (Par {h.par}): Score {h.score} | "
            f"Tee: {h.tee_shot or 'N/A'} | GIR: {'Yes' if h.gir else 'No'} | "
            f"Putts: {h.putts} | First putt: {h.first_putt_distance or 'N/A'}ft | "
            f"Penalties: {h.penalties}"
        )

    hole_summary = '\n'.join(hole_data)

    prompt = f"""You are a world-class golf performance analyst for Magnolia Analytics, a premium golf tracking platform.

Golfer: {user.full_name}
Handicap Index: {user.handicap_index}
Course: {course_name}
Date: {round_.date_played}
Total Score: {round_.total_score}
Total Putts: {round_.total_putts}
Fairways Hit: {round_.fairways_hit}/{round_.fairways_available}
Greens in Regulation: {round_.gir_count}/18
Penalties: {round_.penalties}

Hole-by-hole data:
{hole_summary}

Generate a comprehensive, premium-quality golf performance report in valid HTML. The report should include:

1. A compelling round headline with score and key achievement
2. Strokes gained analysis by category (off tee, approach, around green, putting)
3. Putting breakdown by distance band (0-6ft, 6-10ft, 10-15ft, 15-30ft, 30ft+) with make percentages
4. Narrative coaching insights — what worked well and what to focus on in practice
5. Comparison to season averages (if data available)
6. One clear identified weak point with actionable advice
7. Season context and trajectory

Tone: Premium, authoritative, encouraging but honest. Like a private golf coach reviewing footage.
Style: Use the brand colours dark green (#1B4332) and gold (#C9A84C). Clean, data-driven prose.
Format: Valid HTML fragment (no <html>/<body> tags) ready to embed in an email template.
"""
    return prompt


def generate_report(round_) -> Report:
    """
    Generate a Claude-powered performance report for the given round.

    Currently returns a placeholder HTML report.
    Replace the placeholder block below with the live Anthropic SDK call.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')

    # ------------------------------------------------------------------ #
    # LIVE IMPLEMENTATION — uncomment when API key is available            #
    # ------------------------------------------------------------------ #
    # import anthropic
    # client = anthropic.Anthropic(api_key=api_key)
    # message = client.messages.create(
    #     model='claude-opus-4-5-20251101',
    #     max_tokens=4096,
    #     messages=[{'role': 'user', 'content': _build_prompt(round_)}]
    # )
    # html_content = message.content[0].text
    # prompt_tokens = message.usage.input_tokens
    # completion_tokens = message.usage.output_tokens
    # model_used = 'claude-opus-4-5-20251101'
    # ------------------------------------------------------------------ #

    # PLACEHOLDER
    html_content = f"""
    <div style="font-family: 'Playfair Display', serif; color: #1B4332;">
      <h2 style="color: #C9A84C;">Round Report — {round_.date_played}</h2>
      <p>Your Magnolia Analytics report will appear here once your Claude API key is configured.</p>
      <p><strong>Score:</strong> {round_.total_score} &nbsp;|&nbsp;
         <strong>Putts:</strong> {round_.total_putts} &nbsp;|&nbsp;
         <strong>GIR:</strong> {round_.gir_count}/18</p>
    </div>
    """
    prompt_tokens = 0
    completion_tokens = 0
    model_used = 'placeholder'

    # Upsert report record
    report = round_.report or Report(round_id=round_.id)
    report.html_content = html_content
    report.prompt_tokens = prompt_tokens
    report.completion_tokens = completion_tokens
    report.model_used = model_used
    report.generated_at = datetime.utcnow()
    report.email_status = 'pending'

    db.session.add(report)
    db.session.commit()

    return report

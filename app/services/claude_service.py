"""
Claude API service — generates branded HTML performance reports.
When ANTHROPIC_API_KEY is set, calls Claude live.
Otherwise returns a high-quality styled placeholder report.
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
        approach_info = ''
        if not h.gir and h.approach_miss:
            approach_info = f' | Miss: {h.approach_miss}'
        if h.scramble_distance:
            approach_info += f' | Scramble: {h.scramble_distance}'
        sand_info = ''
        if h.sand_save_attempt:
            sand_info = f' | Sand save: {"Yes" if h.sand_save_made else "No"}'
        hole_data.append(
            f"Hole {h.hole_number} (Par {h.par}): Score {h.score} | "
            f"Tee: {h.tee_shot or 'N/A'} | GIR: {'Yes' if h.gir else 'No'}{approach_info} | "
            f"Putts: {h.putts} | First putt: {h.first_putt_distance or 'N/A'}ft | "
            f"Penalties: {h.penalties}{sand_info}"
        )

    hole_summary = '\n'.join(hole_data)
    score_vs_par = round_.score_vs_par()
    score_label = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else str(score_vs_par or 'E')
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    gir_pct = round((round_.gir_count or 0) / max(round_.holes_played or 18, 1) * 100)

    prompt = f"""You are the performance analysis engine for Magnolia Analytics — a premium golf tracking platform used by serious amateur golfers.

GOLFER DATA
-----------
Name: {user.full_name}
Handicap Index: {user.handicap_index}
Course: {course_name}
Date: {round_.date_played.strftime('%d %B %Y')}
Total Score: {round_.total_score} ({score_label} par)
Total Putts: {round_.total_putts}
Fairways Hit: {round_.fairways_hit}/{round_.fairways_available} ({fw_pct}%)
Greens in Regulation: {round_.gir_count}/18 ({gir_pct}%)
Penalties: {round_.penalties}

Hole-by-hole breakdown:
{hole_summary}

TASK
----
Generate a complete, standalone HTML performance report. Output ONLY the HTML — no markdown, no code fences, no commentary. Start with <!DOCTYPE html>.

DESIGN SPEC — follow exactly:
- Fonts: Playfair Display (headings/large numbers), DM Mono (labels/data), DM Sans (body). Load from Google Fonts.
- CSS variables: --green-dark: #1a2e1a; --green-mid: #2d4a2d; --green-light: #3d6b3d; --green-accent: #5a9e5a; --gold: #c9a84c; --gold-light: #e8c97a; --cream: #f5f0e8; --cream-dark: #e8e0d0; --white: #fdfcf8; --red: #c0392b; --text-dark: #1a1a1a; --text-mid: #4a4a4a;
- Dark green header (#1a2e1a) with course name in Playfair Display italic (gold-light), large score in gold (~6rem Playfair Display)
- stat-card: white bg, 4px left border (green-accent / gold / red), Playfair Display value (~2.2rem), DM Mono label
- Strokes gained: centred-zero bar chart (positive = green-accent, negative = red). DM Mono labels.
- Putting make% bars: good = green-accent, warn = gold, bad = red
- Narrative card: dark green bg, gold italic headline, rgba(255,255,255,0.65) body text
- Season comparison table: this round = gold, season avg = text-mid
- Weakness card: rgba(192,57,43,0.06) bg, red border, red DM Mono label
- 3-column key takeaways at bottom
- Footer: dark green, brand name in gold, "Track every shot. Understand every round."
- Back link to /dashboard in DM Mono

CONTENT REQUIREMENTS:
1. Header: golfer name, course, date, score vs par label, large gross score
2. Four stat cards: Score vs Par | Fairways Hit (%) | GIR (%) | Total Putts
3. Strokes gained — estimate from data: Off the Tee (fairway %, penalty analysis), Approach (GIR %, approach miss direction), Around the Greens (scramble %, sand saves), Putting (putts per hole, first putt distances)
4. Putting make% by distance band using first_putt_distance data (group: 0-6ft, 6-10ft, 10-20ft, 20ft+)
5. Narrative coaching: 3 paragraphs. Specific, honest. Reference actual holes. What genuinely worked, what cost shots, one clear priority
6. Season context table: This Round vs Season Avg (use current round values as placeholders for both since this may be the first round)
7. Weakness card: single most impactful focus area for next practice session
8. Three key takeaway cards

TONE: Premium, analytical, like a private golf coach reviewing footage. Never generic. Reference specific hole numbers.

Output only the HTML. Begin immediately with <!DOCTYPE html>.
"""
    return prompt


def _placeholder_report(round_) -> str:
    """High-quality placeholder report matching the Magnolia design system."""
    score_vs_par = round_.score_vs_par()
    score_label = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else (str(score_vs_par) if score_vs_par is not None else 'E')
    course_name = round_.course.name if round_.course else 'Unknown Course'
    fw_pct = round(round_.fairways_hit / round_.fairways_available * 100) if round_.fairways_available else 0
    gir_pct = round((round_.gir_count or 0) / max(round_.holes_played or 18, 1) * 100)
    date_str = round_.date_played.strftime('%d %B %Y')
    user = round_.golfer
    putts_per_hole = round((round_.total_putts or 0) / max(round_.holes_played or 18, 1), 1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Magnolia Analytics — Round Report · {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --green-dark: #1a2e1a; --green-mid: #2d4a2d; --green-light: #3d6b3d;
    --green-accent: #5a9e5a; --gold: #c9a84c; --gold-light: #e8c97a;
    --cream: #f5f0e8; --cream-dark: #e8e0d0; --white: #fdfcf8;
    --red: #c0392b; --text-dark: #1a1a1a; --text-mid: #4a4a4a;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--cream); color: var(--text-dark); font-family: 'DM Sans', sans-serif; min-height: 100vh; }}

  .header {{ background: var(--green-dark); padding: 3rem 4rem 2.5rem; position: relative; overflow: hidden; }}
  .header::before {{ content: '{course_name.upper()[:20]}'; position: absolute; right: 3rem; top: 50%; transform: translateY(-50%) rotate(-8deg); font-family: 'Playfair Display', serif; font-size: 4rem; font-style: italic; color: rgba(201,168,76,0.05); white-space: nowrap; pointer-events: none; }}
  .magnolia-mark {{ font-family: 'DM Mono', monospace; font-size: 0.6rem; letter-spacing: 0.3em; color: var(--gold); text-transform: uppercase; margin-bottom: 1rem; opacity: 0.7; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .header h1 {{ font-family: 'Playfair Display', serif; font-size: 2.4rem; color: var(--white); line-height: 1.1; }}
  .header h1 em {{ color: var(--gold-light); font-style: italic; }}
  .header-score {{ text-align: right; }}
  .big-score {{ font-family: 'Playfair Display', serif; font-size: 6rem; color: var(--gold-light); font-weight: 700; line-height: 1; }}
  .big-score-label {{ font-family: 'DM Mono', monospace; font-size: 0.6rem; color: rgba(255,255,255,0.3); letter-spacing: 0.2em; text-transform: uppercase; text-align: right; margin-top: 0.3rem; }}
  .header-meta-row {{ display: flex; gap: 2rem; margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid rgba(255,255,255,0.07); flex-wrap: wrap; }}
  .header-meta-item {{ display: flex; flex-direction: column; gap: 0.2rem; }}
  .header-meta-val {{ font-family: 'DM Sans', sans-serif; font-size: 0.95rem; color: var(--white); font-weight: 500; }}
  .header-meta-label {{ font-family: 'DM Mono', monospace; font-size: 0.55rem; color: rgba(255,255,255,0.3); letter-spacing: 0.2em; text-transform: uppercase; }}

  .main {{ padding: 3rem 4rem; max-width: 1000px; margin: 0 auto; }}
  .section-label {{ font-family: 'DM Mono', monospace; font-size: 0.6rem; letter-spacing: 0.3em; text-transform: uppercase; color: var(--green-accent); margin-bottom: 1.2rem; }}
  .divider {{ height: 1px; background: var(--cream-dark); margin: 2.5rem 0; }}

  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.2rem; margin-bottom: 3rem; }}
  .stat-card {{ background: var(--white); border-radius: 4px; padding: 1.4rem; border-left: 3px solid var(--green-accent); }}
  .stat-card.gold {{ border-left-color: var(--gold); }}
  .stat-card.red {{ border-left-color: var(--red); }}
  .stat-card-label {{ font-family: 'DM Mono', monospace; font-size: 0.58rem; letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-mid); margin-bottom: 0.7rem; }}
  .stat-card-value {{ font-family: 'Playfair Display', serif; font-size: 2.2rem; color: var(--green-dark); font-weight: 700; line-height: 1; }}
  .stat-card.gold .stat-card-value {{ color: var(--gold); }}
  .stat-card.red .stat-card-value {{ color: var(--red); }}
  .stat-card-sub {{ font-family: 'DM Mono', monospace; font-size: 0.62rem; color: var(--text-mid); margin-top: 0.5rem; line-height: 1.4; }}

  .narrative-card {{ background: var(--green-dark); border-radius: 4px; padding: 2rem; margin-bottom: 3rem; }}
  .narrative-title {{ font-family: 'Playfair Display', serif; font-size: 1.3rem; color: var(--gold-light); margin-bottom: 1rem; font-style: italic; }}
  .narrative-text {{ font-family: 'DM Sans', sans-serif; font-size: 0.9rem; color: rgba(255,255,255,0.65); line-height: 1.8; }}
  .narrative-text + .narrative-text {{ margin-top: 1rem; }}
  .narrative-text strong {{ color: var(--white); }}
  .api-note {{ display: inline-block; background: rgba(201,168,76,0.15); color: var(--gold-light); font-family: 'DM Mono', monospace; font-size: 0.65rem; padding: 0.3rem 0.7rem; border-radius: 2px; margin-top: 1.2rem; letter-spacing: 0.05em; }}

  .footer {{ background: var(--green-dark); padding: 1.5rem 4rem; display: flex; justify-content: space-between; align-items: center; margin-top: 1rem; }}
  .footer-brand {{ font-family: 'Playfair Display', serif; font-size: 1rem; color: var(--gold); }}
  .footer-meta {{ font-family: 'DM Mono', monospace; font-size: 0.6rem; color: rgba(255,255,255,0.25); letter-spacing: 0.15em; }}
  .back-link {{ display: block; text-align: center; padding: 1.5rem; font-family: 'DM Mono', monospace; font-size: 0.7rem; letter-spacing: 0.2em; color: var(--green-accent); text-decoration: none; text-transform: uppercase; }}
  .back-link:hover {{ color: var(--gold); }}

  @media (max-width: 700px) {{
    .header, .main {{ padding: 2rem; }}
    .grid-4 {{ grid-template-columns: 1fr 1fr; }}
    .big-score {{ font-size: 4rem; }}
    .header h1 {{ font-size: 1.6rem; }}
    .footer {{ padding: 1.5rem 2rem; flex-direction: column; gap: 0.5rem; text-align: center; }}
  }}
</style>
</head>
<body>

<header class="header">
  <div class="magnolia-mark">Magnolia Analytics · Round Report</div>
  <div class="header-top">
    <div>
      <h1>Round at<br><em>{course_name}</em></h1>
    </div>
    <div class="header-score">
      <div class="big-score">{round_.total_score}</div>
      <div class="big-score-label">{score_label} Par</div>
    </div>
  </div>
  <div class="header-meta-row">
    <div class="header-meta-item">
      <span class="header-meta-val">{date_str}</span>
      <span class="header-meta-label">Date Played</span>
    </div>
    <div class="header-meta-item">
      <span class="header-meta-val">{user.full_name}</span>
      <span class="header-meta-label">Golfer</span>
    </div>
    <div class="header-meta-item">
      <span class="header-meta-val">{user.handicap_index}</span>
      <span class="header-meta-label">Handicap Index</span>
    </div>
    <div class="header-meta-item">
      <span class="header-meta-val">{round_.holes_played} Holes</span>
      <span class="header-meta-label">Format</span>
    </div>
  </div>
</header>

<div class="main">
  <div class="section-label">Round Summary</div>
  <div class="grid-4">
    <div class="stat-card gold">
      <div class="stat-card-label">Score vs Par</div>
      <div class="stat-card-value">{score_label}</div>
      <div class="stat-card-sub">{round_.total_score} gross</div>
    </div>
    <div class="stat-card">
      <div class="stat-card-label">Fairways Hit</div>
      <div class="stat-card-value">{round_.fairways_hit}/{round_.fairways_available}</div>
      <div class="stat-card-sub">{fw_pct}% of available</div>
    </div>
    <div class="stat-card">
      <div class="stat-card-label">Greens in Reg</div>
      <div class="stat-card-value">{round_.gir_count}/18</div>
      <div class="stat-card-sub">{gir_pct}% GIR rate</div>
    </div>
    <div class="stat-card">
      <div class="stat-card-label">Total Putts</div>
      <div class="stat-card-value">{round_.total_putts}</div>
      <div class="stat-card-sub">{putts_per_hole} avg per hole</div>
    </div>
  </div>

  <div class="divider"></div>

  <div class="narrative-card">
    <div class="narrative-title">Your full report is one API key away.</div>
    <p class="narrative-text">
      Your stats for <strong>{date_str} at {course_name}</strong> have been saved. The numbers above are pulled directly from your hole-by-hole data — real figures, nothing estimated.
    </p>
    <p class="narrative-text" style="margin-top: 1rem;">
      Once your Anthropic API key is configured, this placeholder is replaced with a full coaching report: strokes gained breakdown across all four areas of the game, putting make percentages by distance, a narrative analysis of the round, season comparison, and a single clear priority for your next practice session.
    </p>
    <span class="api-note">Add ANTHROPIC_API_KEY to your .env file to activate personalised reports</span>
  </div>
</div>

<a href="/dashboard" class="back-link">← Back to Dashboard</a>

<footer class="footer">
  <span class="footer-brand">Magnolia Analytics</span>
  <span class="footer-meta">Track every shot. Understand every round.</span>
</footer>

</body>
</html>"""


def generate_report(round_) -> Report:
    """
    Generate a branded performance report for the given round.

    If ANTHROPIC_API_KEY is set in the environment, calls Claude to generate
    a full personalised HTML report. Otherwise returns a styled placeholder.
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
            message = client.messages.create(
                model='claude-opus-4-5-20251101',
                max_tokens=8192,
                messages=[{'role': 'user', 'content': _build_prompt(round_)}]
            )
            html_content = message.content[0].text
            prompt_tokens = message.usage.input_tokens
            completion_tokens = message.usage.output_tokens
            model_used = 'claude-opus-4-5-20251101'
        except Exception as e:
            html_content = None
            model_used = f'placeholder (error: {str(e)[:60]})'

    if not html_content:
        html_content = _placeholder_report(round_)

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

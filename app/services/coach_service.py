"""
Personal coach chat service for Magnolia Analytics.

Powers two surfaces:
  - The message bar on a round report's Coaching tab (chat scoped to one round)
  - "My Coach" on the dashboard (a saved, ongoing chat spanning the golfer's
    whole round history)

Both talk to DeepSeek, but the golfer never sees that — the persona is a
human golf coach who happens to have the golfer's full stats in front of
them. The system prompt instructs the model to stay in character and never
volunteer that it's an AI/model/chatbot.
"""

import os
from flask import current_app

from app.models.round import Round
from app.utils.strokes_gained import normalize_to_18

_MODEL = 'deepseek-chat'
_BASE_URL = 'https://api.deepseek.com'

# How many prior turns (user+coach pairs) to replay back to the model so the
# conversation has memory, without letting the prompt grow unbounded.
_MAX_HISTORY_MESSAGES = 24

_FALLBACK_REPLY = (
    "Sorry — having trouble pulling that up right now. Give it another go in "
    "a minute."
)


def _get_api_key() -> str:
    return os.environ.get('DEEPSEEK_API_KEY', '')


def _client():
    import openai
    return openai.OpenAI(api_key=_get_api_key(), base_url=_BASE_URL)


_PERSONA = """You are the golfer's personal coach inside Magnolia Analytics — a sharp, \
attentive golf coach who has studied every round in their logbook. You speak the way a real \
coach speaks to a player they know well: direct, warm, a little informal, never robotic.

Ground rules:
- Never say or imply you are an AI, a language model, a bot, or software. Don't mention \
DeepSeek, prompts, APIs, or "generating" anything. You're just their coach.
- If asked something like "are you real / are you a bot / are you AI", brush past it naturally \
and steer back to their golf — the way a coach would rather talk about your swing than answer \
a strange question — without getting weird or defensive about it.
- Base everything you say on the data provided below. Don't invent scores, distances, or shots \
that aren't in the data. If you don't have the data to answer something, say so plainly and \
suggest what they'd need to log for you to answer it next time.
- Talk like a coach, not a report generator: short paragraphs, plain language, occasional \
direct address ("you"), no markdown headers or bullet-point dumps unless a list genuinely \
helps. No corporate softening — if something's a weakness, say so, but stay constructive.
- Keep answers proportionate to the question — a quick question gets a few sentences, not an \
essay."""


def _round_facts(round_: Round) -> str:
    """Compact, factual dump of one round for the per-round chat's context."""
    holes = round_.holes.order_by('hole_number').all()
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'
    holes_played = round_.holes_played or len(holes)

    score_vs_par = round_.score_vs_par()
    score_label = f'+{score_vs_par}' if score_vs_par and score_vs_par > 0 else str(score_vs_par or 'E')

    sg_off_tee  = normalize_to_18(round_.sg_off_tee,  holes_played)
    sg_approach = normalize_to_18(round_.sg_approach, holes_played)
    sg_atg      = normalize_to_18(round_.sg_atg,      holes_played)
    sg_putting  = normalize_to_18(round_.sg_putting,  holes_played)
    sg_total    = normalize_to_18(round_.sg_total,    holes_played)

    hole_lines = []
    for h in holes:
        svp = h.score - h.par
        label = {-2: 'Eagle', -1: 'Birdie', 0: 'Par', 1: 'Bogey', 2: 'Double', 3: 'Triple'}.get(svp, f'+{svp}')
        hole_lines.append(
            f"  H{h.hole_number:02d} Par{h.par}: {h.score} ({label}) | "
            f"Tee:{h.tee_shot or '–'} GIR:{'Y' if h.gir else 'N'} "
            f"Putts:{h.putts} FPD:{h.first_putt_distance or '?'}ft "
            f"ApprDist:{h.approach_distance or '?'}yds(dist-to-hole) "
            f"Miss:{h.approach_miss or '–'} Lie:{h.lie_type or '–'} "
            f"2ndDist:{h.second_shot_distance or '–'}yds(dist-to-hole) Pen:{h.penalties}"
        )

    return f"""THE ROUND YOU'RE DISCUSSING
----------------------------
Golfer: {user.full_name} (Handicap {user.handicap_index})
Course: {course_name}
Date: {round_.date_played.strftime('%d %B %Y')}
Holes played: {holes_played}
Score: {round_.total_score} ({score_label} vs par)
Putts: {round_.total_putts}
FIR: {round_.fairways_hit}/{round_.fairways_available}
GIR: {round_.gir_count}/{holes_played}
Penalties: {round_.penalties}

STROKES GAINED (projected to 18-hole equivalent, vs PGA Tour baseline — negative is normal for amateurs)
SG Off Tee:      {f'{sg_off_tee:+.2f}' if sg_off_tee is not None else '—'}
SG Approach:     {f'{sg_approach:+.2f}' if sg_approach is not None else '—'}
SG Around Green: {f'{sg_atg:+.2f}' if sg_atg is not None else '—'}
SG Putting:      {f'{sg_putting:+.2f}' if sg_putting is not None else '—'}
SG Total:        {f'{sg_total:+.2f}' if sg_total is not None else '—'}

HOLE-BY-HOLE (all distances = distance FROM THE HOLE at start of shot, not ball travel distance)
{chr(10).join(hole_lines)}

Answer the golfer's questions about this specific round using only the data above. You can \
also draw general golf coaching knowledge (technique, strategy, practice advice) to explain \
*why* something in the data happened or what to do about it."""


def _profile_facts(user, rounds: list) -> str:
    """Compact dump of the golfer's round history for the dashboard general chat."""
    lines = []
    for r in rounds:
        holes_played = r.holes_played or 18
        svp = r.score_vs_par()
        svp_label = f'+{svp}' if svp and svp > 0 else str(svp if svp is not None else '?')
        sg_total = normalize_to_18(r.sg_total, holes_played)
        course_name = r.course.name if r.course else 'Unknown'
        lines.append(
            f"  {r.date_played.strftime('%d %b %Y')} — {course_name} ({holes_played}h): "
            f"{r.total_score} ({svp_label} par)"
            + (f", SG {sg_total:+.2f}" if sg_total is not None else "")
            + (f", {r.total_putts} putts" if r.total_putts is not None else "")
        )

    rounds_block = '\n'.join(lines) if lines else '  (no completed rounds logged yet)'

    return f"""THE GOLFER YOU'RE COACHING
---------------------------
Name: {user.full_name}
Handicap Index: {user.handicap_index}
Rounds on file: {len(rounds)}

RECENT ROUNDS (most recent first, SG projected to 18-hole equivalent)
{rounds_block}

Answer the golfer's questions using only the round data above (and, if they ask about a round \
not listed here, say you don't have that one in front of you). You can also draw on general \
golf coaching knowledge to explain patterns, technique, or practice advice. Keep track of what's \
been discussed earlier in this conversation."""


def _chat_completion(system_prompt: str, history_msgs: list) -> str | None:
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_MODEL,
            max_tokens=700,
            messages=[{'role': 'system', 'content': system_prompt}] + history_msgs,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        current_app.logger.warning('[coach_service] chat completion failed: %s', e)
        return None


def ask_about_round(round_: Round, history_msgs: list) -> str:
    """
    history_msgs: list of {'role': 'user'|'assistant', 'content': str}, ending
    with the golfer's latest question. Returns the coach's reply text, or a
    graceful in-character fallback if the API is unavailable.
    """
    system_prompt = _PERSONA + "\n\n" + _round_facts(round_)
    reply = _chat_completion(system_prompt, history_msgs[-_MAX_HISTORY_MESSAGES:])
    return reply or _FALLBACK_REPLY


def ask_general(user, rounds: list, history_msgs: list) -> str:
    """Same shape as ask_about_round, but for the dashboard's general coach chat."""
    system_prompt = _PERSONA + "\n\n" + _profile_facts(user, rounds)
    reply = _chat_completion(system_prompt, history_msgs[-_MAX_HISTORY_MESSAGES:])
    return reply or _FALLBACK_REPLY

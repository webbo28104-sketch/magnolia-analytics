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
from app.services.round_context import round_context, profile_context

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
    """Full data for one round: shot-by-shot log, breakdowns, previous rounds."""
    user = round_.golfer
    course_name = round_.course.name if round_.course else 'Unknown Course'
    return f"""THE GOLFER: {user.full_name} (Handicap Index {user.handicap_index})
THE ROUND YOU'RE DISCUSSING: {course_name}, {round_.date_played.strftime('%d %B %Y')}, {round_.tee_set or ''} tees

{round_context(round_)}

You have every logged shot of this round above, plus the golfer's previous rounds. Answer questions about any shot, hole, distance, club or comparison directly from this data — e.g. "how far was my second putt on 7" is the putt 2 line under H7. Strokes gained is measured against the PGA Tour average, so negative numbers are normal for amateurs; judge performance against the golfer's own previous rounds. Only say you don't have something if it genuinely isn't in the data (for example a distance they didn't log), and say exactly what's missing. You can also draw on general golf coaching knowledge to explain why something happened or what to practise."""


def _profile_facts(user, rounds: list) -> str:
    """Whole-history data for the dashboard general chat."""
    return f"""THE GOLFER YOU'RE COACHING
---------------------------
Name: {user.full_name}
Handicap Index: {user.handicap_index}
Rounds on file: {len(rounds)}

{profile_context(user)}

Answer from the data above: round summaries, breakdowns, club stats and full shot logs for the most recent rounds. Strokes gained is vs the PGA Tour average, so judge the golfer against their own history. If they ask about a round or shot that isn't in the data, say so plainly. Keep track of what's been discussed earlier in this conversation."""


def _chat_completion(system_prompt: str, history_msgs: list) -> str | None:
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_MODEL,
            max_tokens=900,
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

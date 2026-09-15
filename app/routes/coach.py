"""
Coach chat routes.

Two surfaces, one backend:
  - /coach/round/<round_id>/...  — the message bar embedded in a round
    report's Coaching tab. One chat per round, auto-created on first message.
  - /coach/chats...              — the dashboard's "My Coach" page: a list
    of saved, general chats not tied to any one round.

Both are Pro-only (matches the rest of the coaching/analysis surface).
"""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models.round import Round
from app.models.coach_chat import CoachChat, CoachMessage
from app.utils.access import is_pro
from app.services.coach_service import ask_about_round, ask_general

coach_bp = Blueprint('coach', __name__)


def _pro_gate_json():
    if not is_pro(current_user):
        return jsonify({'error': 'Ask Your Coach is a Magnolia Pro feature.'}), 403
    return None


def _pro_gate_page():
    if not is_pro(current_user):
        flash('Ask Your Coach is a Magnolia Pro feature.', 'info')
        return redirect(url_for('main.upgrade'))
    return None


def _history_payload(chat: CoachChat) -> list:
    return [{'role': m.role, 'content': m.content} for m in chat.messages]


def _to_llm_roles(history: list) -> list:
    """CoachMessage.role is 'user'/'coach' for display; DeepSeek wants 'assistant'."""
    return [{'role': ('assistant' if m['role'] == 'coach' else 'user'), 'content': m['content']}
            for m in history]


# ---------------------------------------------------------------------------
# Round-scoped chat (Coaching tab message bar)
# ---------------------------------------------------------------------------

@coach_bp.route('/round/<int:round_id>/messages')
@login_required
def round_messages(round_id):
    gate = _pro_gate_json()
    if gate:
        return gate
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()
    chat = CoachChat.query.filter_by(round_id=round_.id, user_id=current_user.id).first()
    return jsonify({'messages': _history_payload(chat) if chat else []})


@coach_bp.route('/round/<int:round_id>/ask', methods=['POST'])
@login_required
def round_ask(round_id):
    gate = _pro_gate_json()
    if gate:
        return gate
    round_ = Round.query.filter_by(id=round_id, user_id=current_user.id).first_or_404()

    data = request.get_json(silent=True) or {}
    text = (data.get('message') or '').strip()
    if not text:
        return jsonify({'error': 'Message is empty.'}), 400
    if len(text) > 2000:
        return jsonify({'error': 'Message is too long.'}), 400

    chat = CoachChat.query.filter_by(round_id=round_.id, user_id=current_user.id).first()
    if not chat:
        chat = CoachChat(user_id=current_user.id, round_id=round_.id,
                          title=f'{round_.course.name if round_.course else "Round"} — {round_.date_played.strftime("%d %b %Y")}')
        db.session.add(chat)
        db.session.flush()

    db.session.add(CoachMessage(chat_id=chat.id, role='user', content=text))
    db.session.commit()

    history = _to_llm_roles(_history_payload(chat))
    reply = ask_about_round(round_, history)

    db.session.add(CoachMessage(chat_id=chat.id, role='coach', content=reply))
    chat.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'reply': reply})


# ---------------------------------------------------------------------------
# General dashboard chat ("My Coach")
# ---------------------------------------------------------------------------

@coach_bp.route('/')
@login_required
def index():
    gate = _pro_gate_page()
    if gate:
        return gate
    chats = (CoachChat.query
             .filter_by(user_id=current_user.id, round_id=None)
             .order_by(CoachChat.updated_at.desc())
             .all())
    open_id = request.args.get('chat', type=int)
    if open_id and not any(c.id == open_id for c in chats):
        open_id = None
    if not open_id and chats:
        open_id = chats[0].id
    return render_template('coach/index.html', chats=chats, open_chat_id=open_id)


@coach_bp.route('/chats', methods=['POST'])
@login_required
def create_chat():
    gate = _pro_gate_json()
    if gate:
        return gate
    chat = CoachChat(user_id=current_user.id, round_id=None, title=None)
    db.session.add(chat)
    db.session.commit()
    return jsonify({'id': chat.id})


@coach_bp.route('/chats/<int:chat_id>/messages')
@login_required
def chat_messages(chat_id):
    gate = _pro_gate_json()
    if gate:
        return gate
    chat = CoachChat.query.filter_by(id=chat_id, user_id=current_user.id, round_id=None).first_or_404()
    return jsonify({'title': chat.title, 'messages': _history_payload(chat)})


@coach_bp.route('/chats/<int:chat_id>/messages', methods=['POST'])
@login_required
def chat_ask(chat_id):
    gate = _pro_gate_json()
    if gate:
        return gate
    chat = CoachChat.query.filter_by(id=chat_id, user_id=current_user.id, round_id=None).first_or_404()

    data = request.get_json(silent=True) or {}
    text = (data.get('message') or '').strip()
    if not text:
        return jsonify({'error': 'Message is empty.'}), 400
    if len(text) > 2000:
        return jsonify({'error': 'Message is too long.'}), 400

    is_first_message = chat.messages.count() == 0

    db.session.add(CoachMessage(chat_id=chat.id, role='user', content=text))
    if is_first_message:
        chat.title = text[:60] + ('…' if len(text) > 60 else '')
    db.session.commit()

    rounds = (Round.query
              .filter_by(user_id=current_user.id, status='complete')
              .order_by(Round.date_played.desc())
              .limit(30)
              .all())

    history = _to_llm_roles(_history_payload(chat))
    reply = ask_general(current_user, rounds, history)

    db.session.add(CoachMessage(chat_id=chat.id, role='coach', content=reply))
    chat.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'reply': reply, 'title': chat.title})


@coach_bp.route('/chats/<int:chat_id>', methods=['DELETE'])
@login_required
def delete_chat(chat_id):
    gate = _pro_gate_json()
    if gate:
        return gate
    chat = CoachChat.query.filter_by(id=chat_id, user_id=current_user.id, round_id=None).first_or_404()
    db.session.delete(chat)
    db.session.commit()
    return jsonify({'ok': True})

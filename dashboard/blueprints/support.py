"""
support.py — Route trang hỗ trợ + API gửi/nâng cấp yêu cầu hỗ trợ.
"""

import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import asyncio

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

import database as db
from dashboard.extensions import limiter
from dashboard.support_service import manual_escalate_thread, process_user_support_message_async

bp = Blueprint("support", __name__)


@bp.route("/support")
def support_page():
    """Trang Hỗ Trợ 24/7 (Yêu cầu đăng nhập, chat với Zeryn AI và chuyển tiếp nhân viên)."""
    if "user" not in session:
        return redirect(url_for("public.login"))
    user = dict(session["user"])
    user_id = str(user.get("id"))
    user_name = user.get("username", "User")
    user_avatar = session.get("avatar") or (f"https://cdn.discordapp.com/avatars/{user_id}/{user.get('avatar')}.png" if user.get("avatar") else "https://cdn.discordapp.com/embed/avatars/0.png")
    user["avatar_url"] = user_avatar

    thread = db.get_or_create_support_thread(user_id, user_name, user_avatar)
    messages = db.get_support_messages(thread["thread_id"], after_id=0, limit=50)
    db.mark_support_thread_read(thread["thread_id"], by_admin=False)

    return render_template(
        "support.html",
        user=user,
        avatar=user_avatar,
        thread=thread,
        messages=messages,
        current_ui_lang=session.get("ui_lang", "vi")
    )

@bp.route("/api/support/messages")
def api_support_messages():
    """API Incremental Polling tin nhắn hỗ trợ (chống IDOR bằng cách kiểm tra user_id)."""
    if "user" not in session:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    user_id = str(session["user"].get("id"))
    thread_id = request.args.get("thread_id", "").strip()
    after_id = int(request.args.get("after_id", 0) or 0)

    thread = db.get_support_thread(thread_id, user_id=user_id)
    if not thread:
        return jsonify({"ok": False, "error": "thread_not_found"}), 404

    messages = db.get_support_messages(thread_id, after_id=after_id, limit=50)
    db.mark_support_thread_read(thread_id, by_admin=False)
    return jsonify({"ok": True, "messages": messages, "status": thread.get("status")})

@bp.route("/api/support/send", methods=["POST"])
@limiter.limit("5/minute")
@limiter.limit("60/hour")
def api_support_send():
    """API gửi tin nhắn từ người dùng, lưu DB ngay và đẩy tác vụ AI ngầm (non-blocking)."""
    if "user" not in session:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    user_id = str(session["user"].get("id"))
    user_name = session["user"].get("username", "User")
    data = request.get_json(silent=True) or request.form
    thread_id = data.get("thread_id", "").strip()
    content = data.get("content", "").strip()

    if not thread_id or not content:
        return jsonify({"ok": False, "error": "invalid_payload"}), 400

    thread = db.get_support_thread(thread_id, user_id=user_id)
    if not thread:
        return jsonify({"ok": False, "error": "thread_not_found"}), 404

    # 1. Lưu tin nhắn người dùng tức thì (<5ms commit)
    msg = db.add_support_message(
        thread_id=thread_id,
        sender_type="user",
        sender_id=user_id,
        sender_name=user_name,
        content=content
    )

    # 2. Đẩy vào background worker xử lý AI và Discord escalation alert (không block)
    from dashboard.support_service import process_user_support_message_async
    process_user_support_message_async(thread_id, user_id, user_name, content)

    return jsonify({"ok": True, "message_id": msg.get("id")})

@bp.route("/api/support/escalate", methods=["POST"])
@limiter.limit("5/hour")
def api_support_escalate():
    """API kích hoạt chuyển tiếp tới nhân viên hỗ trợ khi người dùng bấm nút."""
    if "user" not in session:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    user_id = str(session["user"].get("id"))
    user_name = session["user"].get("username", "User")
    data = request.get_json(silent=True) or request.form
    thread_id = data.get("thread_id", "").strip()

    thread = db.get_support_thread(thread_id, user_id=user_id)
    if not thread:
        return jsonify({"ok": False, "error": "thread_not_found"}), 404

    from dashboard.support_service import manual_escalate_thread
    alerted = manual_escalate_thread(thread_id, user_id, user_name, thread.get("last_message", ""))
    return jsonify({"ok": True, "alerted": alerted})

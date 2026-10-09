"""
public.py — Route công khai: landing page, OAuth Discord, pháp lý, health, docs.
"""

import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import json
import secrets
import time as _time
from datetime import datetime, timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import config
from i18n import i18n as i18n_manager
from dashboard.auth import (
    exchange_code,
    get_avatar_url,
    get_manageable_guilds,
    get_oauth2_url,
    get_user,
    revoke_access_token,
    store_access_token,
)
from dashboard.extensions import limiter

bp = Blueprint("public", __name__)


@bp.route("/")
def index():
    return render_template("landing.html")

@bp.route("/invite")
def invite():
    client_id = config.CLIENT_ID
    url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"
    return redirect(url)

@bp.route("/tos")
def tos():
    return render_template("tos.html")

@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")

@bp.route("/login")
@limiter.limit("20/minute")
def login():
    if "user" in session:
        return redirect(url_for("guild.home"))
    # Sinh state chống Login CSRF — phải khớp khi Discord redirect về /callback
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return render_template("login.html", oauth_url=get_oauth2_url(state=state))

@bp.route("/callback")
@limiter.limit("30/minute")
def callback():
    # P0.2: bắt buộc kiểm tra state chống CSRF cho OAuth flow
    expected_state = session.pop("oauth_state", None)
    returned_state = request.args.get("state")
    if not expected_state or not returned_state or not secrets.compare_digest(
        str(expected_state), str(returned_state)
    ):
        flash("⛔ Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.", "error")
        return redirect(url_for("public.login"))

    code = request.args.get("code")
    if not code:
        flash("Đăng nhập thất bại — không nhận được code.", "error")
        return redirect(url_for("public.login"))
    try:
        token_data   = exchange_code(code)
        access_token = token_data["access_token"]
        user         = get_user(access_token)
        guilds       = get_manageable_guilds(access_token)
        session.permanent = True  # áp dụng PERMANENT_SESSION_LIFETIME
        session["user"]         = user
        # Cookie chỉ mang con trỏ ngẫu nhiên; access token thật nằm trong vault của
        # tiến trình dashboard (Flask ký chứ không mã hóa session).
        session["oauth_token_id"] = store_access_token(access_token)
        session["guilds"]       = guilds
        session["guilds_fetched_at"] = _time.time()
        session["avatar"]       = get_avatar_url(user)
    except Exception as e:
        flash(f"Đăng nhập thất bại: {e}", "error")
        return redirect(url_for("public.login"))
    return redirect(url_for("guild.home"))

@bp.route("/logout")
def logout():
    # Trước đây chỉ xóa session phía mình — token đã lộ (copy cookie, máy dùng chung)
    # vẫn dùng được tới khi Discord hết hạn.
    revoke_access_token()
    session.clear()
    return redirect(url_for("public.login"))

@bp.route("/ui/language/<lang_code>")
def set_ui_language(lang_code: str):
    """
    Đổi ngôn ngữ giao diện web (session-based).
    Độc lập với ngôn ngữ bot trong guild (DB) — thay đổi cái này không ảnh hưởng cái kia.
    """
    if lang_code in i18n_manager.get_supported_languages():
        session["ui_lang"] = lang_code
    return redirect(request.referrer or url_for("guild.home"))

HEALTH_MAX_STALE_SECONDS = 180  # bot gửi heartbeat mỗi 60s; 3 nhịp lỗi = coi như chết


def _health_is_fresh(data: dict) -> bool:
    """`online: true` chỉ có nghĩa nếu heartbeat còn mới.

    Bot từng chỉ ghi health.json khi mất/kết nối lại, nên một tiến trình bị treo (event
    loop block) vẫn để nguyên trạng thái online và /health trả 200 vĩnh viễn — watchdog
    vì thế không bao giờ restart. Bot sống ghi lại mỗi 60 giây.
    """
    stamp = data.get("last_change")
    if not stamp:
        return False
    try:
        raw = str(stamp).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (_time.time() - dt.timestamp()) <= HEALTH_MAX_STALE_SECONDS


@bp.route("/health")
def health():
    # `_V2_DIR` là repo root (xem preamble) — KHÔNG tính theo __file__ của blueprint,
    # vì file này nằm sâu thêm một cấp (dashboard/blueprints/).
    health_file = os.path.join(_V2_DIR, "data", "health.json")
    data = {"online": False, "pid": None, "last_ready": None, "last_change": None}
    try:
        with open(health_file, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass  # bot chưa ghi file / file hỏng → offline
    fresh = _health_is_fresh(data)
    online = bool(data.get("online")) and fresh
    if data.get("online") and not fresh:
        data["stale"] = True
        data["reason"] = f"heartbeat older than {HEALTH_MAX_STALE_SECONDS}s"
    data["online"] = online
    status_code = 200 if online else 503
    return jsonify(data), status_code

@bp.route("/docs")
def docs_page():
    """Trang Tài Liệu Hướng Dẫn & Danh Mục 110 Lệnh (Public, Đa ngôn ngữ, Preview tương tác)."""
    from dashboard.commands_catalog import get_localized_commands_data
    ui_lang = session.get("ui_lang", "vi")
    localized_data = get_localized_commands_data(ui_lang)
    total = sum(len(c["commands"]) for c in localized_data)
    return render_template(
        "docs.html",
        commands_data=localized_data,
        total_count=total,
        current_ui_lang=ui_lang
    )

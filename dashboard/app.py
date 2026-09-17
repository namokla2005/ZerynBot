"""
app.py — Flask dashboard for Discord Bot v2.
"""
import sys, os, subprocess, shutil, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 encoding on stdout/stderr for Flask (prevents cp1252 UnicodeEncodeError on Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import secrets
import time as _time
from datetime import timedelta
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify
from datetime import datetime, timezone
import json
import config
import database as db
import requests
from i18n import t, tr, i18n as i18n_manager
from dashboard.auth import (
    get_oauth2_url, exchange_code, get_user, get_manageable_guilds, get_avatar_url,
    channel_belongs_to_guild, is_safe_http_url,
)
from dashboard.api import api

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = config.FLASK_SECRET_KEY
app.register_blueprint(api)

# ─── Session / Cookie hardening (P1.7) ─────────────────────────────────────────
app.config.update(
    SESSION_COOKIE_HTTPONLY=config.SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE=config.SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_LIFETIME_DAYS),
)

# Đọc IP thật khi chạy sau reverse proxy (chỉ bật khi chắc chắn có proxy)
if config.BEHIND_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ─── Rate limiting cho các endpoint nhạy cảm (P1.6) ────────────────────────────
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        storage_uri=config.RATELIMIT_STORAGE_URI,
        default_limits=[],          # không giới hạn chung; chỉ limit route nhạy cảm
        swallow_errors=True,        # lỗi storage không làm chết dashboard
    )
except ImportError:  # flask-limiter chưa cài → chạy không giới hạn (khuyến nghị cài đặt)
    class _NoopLimiter:
        def limit(self, *a, **k):
            def _decorator(f):
                return f
            return _decorator
    limiter = _NoopLimiter()

# ─── CSRF protection tự quản (P0.5) ────────────────────────────────────────────
# Token per-session, kiểm tra trên mọi request thay đổi dữ liệu khi đã đăng nhập.
_CSRF_SESSION_KEY = "_csrf_token"
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token() -> str:
    """Lấy (hoặc tạo) CSRF token của session hiện tại — dùng trong templates."""
    tok = session.get(_CSRF_SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = tok
    return tok


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def _csrf_protect():
    if request.method not in _CSRF_METHODS:
        return None
    # Chỉ áp dụng cho request của người ĐÃ đăng nhập (mọi mutation route hiện hữu
    # đều yêu cầu login; request anonymous sẽ bị login_required chặn như cũ).
    if "user" not in session:
        return None

    sent = request.headers.get("X-CSRF-Token")
    if not sent:
        sent = request.form.get("_csrf_token")
    if not sent and request.is_json:
        body = request.get_json(silent=True) or {}
        sent = body.get("_csrf_token")

    if not sent or not secrets.compare_digest(str(sent), str(session.get(_CSRF_SESSION_KEY, ""))):
        wants_json = (
            request.path.startswith(("/api/", "/admin/"))
            or request.is_json
            or request.accept_mimetypes.best == "application/json"
        )
        if wants_json:
            return jsonify({"ok": False, "error": "CSRF token không hợp lệ hoặc bị thiếu."}), 403
        flash("⛔ Phiên làm việc đã hết hạn hoặc yêu cầu không hợp lệ (CSRF). Vui lòng thử lại.", "error")
        return redirect(request.referrer or url_for("home"))
    return None


@app.context_processor
def inject_i18n():
    """Inject translation helpers và danh sách ngôn ngữ vào mọi Jinja2 template."""
    page_lang = session.get("ui_lang", "vi")  # ui_lang: ngôn ngữ giao diện web (per-user)
    return {
        "t":                  lambda key, **kw: t(key, lang=page_lang, **kw),
        "tr":                 tr,
        "available_languages": i18n_manager.get_supported_languages(),
        "current_ui_lang":    page_lang,
    }


# ─── Auth helpers ──────────────────────────────────────────────────────────────

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def _refresh_guilds_if_stale() -> None:
    """P1.9: Tải lại danh sách guild + quyền từ Discord nếu session quá cũ.
    Chặn trường hợp user bị thu hồi quyền MANAGE_GUILD nhưng session vẫn còn hiệu lực.
    Lỗi mạng → giữ dữ liệu cũ (khả dụng); token hết hạn (401) → đăng xuất.
    """
    from dashboard import auth as _auth
    now = _time.time()
    fetched_at = session.get("guilds_fetched_at", 0) or 0
    if now - fetched_at < _auth.SESSION_GUILD_TTL:
        return
    token = session.get("access_token")
    if not token:
        return
    try:
        guilds = get_manageable_guilds(token)
        session["guilds"] = guilds
        session["guilds_fetched_at"] = now
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status == 401:
            session.clear()  # token Discord đã thu hồi → bắt đăng nhập lại
        # lỗi khác (mạng/5xx) → giữ nguyên session cũ
    except Exception:
        pass


def guild_access_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        _refresh_guilds_if_stale()
        if "user" not in session:  # token Discord hết hạn trong lúc refresh
            return redirect(url_for("login"))
        guild_id = kwargs.get("guild_id", "")
        guild_info = _get_guild_from_session(guild_id)
        if not guild_info or not guild_info.get("bot_in_guild"):
            flash("Bạn không có quyền truy cập server này.", "error")
            return redirect(url_for("home"))
            
        # Check custom bot admin roles
        from database import get_guild_settings
        from dashboard import auth
        settings = get_guild_settings(guild_id)
        admin_roles_str = settings.get("bot_admin_roles", "[]")
        
        import json
        try:
            admin_roles = json.loads(admin_roles_str)
        except Exception:
            admin_roles = []
            
        if admin_roles and not guild_info.get("owner"):
            # Fetch member roles using bot token
            user_id = session["user"]["id"]
            member_roles = auth.get_member_roles(guild_id, user_id)
            has_role = any(r in admin_roles for r in member_roles)
            if not has_role:
                flash("Bạn cần có Role được cấp phép (Bot Admin) để quản lý Bot.", "error")
                return redirect(url_for("home"))
                
        return f(*args, **kwargs)
    return decorated

def _get_guild_from_session(guild_id: str) -> dict:
    guilds = session.get("guilds", [])
    return next((g for g in guilds if g["id"] == guild_id), {})


def _safe_channel(guild_id: str, channel_id):
    """
    P0.4: Trả về channel_id nếu nó THỰC SỰ thuộc guild, ngược lại trả về None
    (chặn cài cắm kênh của server khác vào settings qua form craft tay).
    Nếu không xác thực được (Discord API lỗi mạng) → giữ nguyên giá trị để không
    vô tình xóa cấu hình hợp lệ; lớp gửi tin (api.py) vẫn kiểm tra fail-closed.
    """
    if not channel_id:
        return None
    from dashboard import auth as _auth
    ids = _auth.get_guild_channel_ids(str(guild_id))
    if ids is None:
        return channel_id  # không kiểm chứng được → bỏ qua (send-time vẫn chặn)
    return str(channel_id) if str(channel_id) in ids else None

# ─── Routes: Auth ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/invite")
def invite():
    client_id = config.CLIENT_ID
    url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"
    return redirect(url)

@app.route("/tos")
def tos():
    return render_template("tos.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/login")
@limiter.limit("20/minute")
def login():
    if "user" in session:
        return redirect(url_for("home"))
    # Sinh state chống Login CSRF — phải khớp khi Discord redirect về /callback
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return render_template("login.html", oauth_url=get_oauth2_url(state=state))

@app.route("/callback")
@limiter.limit("30/minute")
def callback():
    # P0.2: bắt buộc kiểm tra state chống CSRF cho OAuth flow
    expected_state = session.pop("oauth_state", None)
    returned_state = request.args.get("state")
    if not expected_state or not returned_state or not secrets.compare_digest(
        str(expected_state), str(returned_state)
    ):
        flash("⛔ Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.", "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    if not code:
        flash("Đăng nhập thất bại — không nhận được code.", "error")
        return redirect(url_for("login"))
    try:
        token_data   = exchange_code(code)
        access_token = token_data["access_token"]
        user         = get_user(access_token)
        guilds       = get_manageable_guilds(access_token)
        session.permanent = True  # áp dụng PERMANENT_SESSION_LIFETIME
        session["user"]         = user
        session["access_token"] = access_token
        session["guilds"]       = guilds
        session["guilds_fetched_at"] = _time.time()
        session["avatar"]       = get_avatar_url(user)
    except Exception as e:
        flash(f"Đăng nhập thất bại: {e}", "error")
        return redirect(url_for("login"))
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/ui/language/<lang_code>")
def set_ui_language(lang_code: str):
    """
    Đổi ngôn ngữ giao diện web (session-based).
    Độc lập với ngôn ngữ bot trong guild (DB) — thay đổi cái này không ảnh hưởng cái kia.
    """
    if lang_code in i18n_manager.get_supported_languages():
        session["ui_lang"] = lang_code
    return redirect(request.referrer or url_for("home"))


# ─── Health-check (Lớp 2: watchdog curl endpoint này để biết bot khỏe) ─────────
# Route PUBLIC (không login). Đọc data/health.json do bot ghi.
# Trả 200 khi online:true, 503 khi online:false → curl -sf chỉ OK khi bot khỏe.

@app.route("/health")
def health():
    health_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "health.json",
    )
    data = {"online": False, "pid": None, "last_ready": None, "last_change": None}
    try:
        with open(health_file, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass  # bot chưa ghi file / file hỏng → offline
    status_code = 200 if data.get("online") else 503
    return jsonify(data), status_code

# ─── Routes: Dashboard ─────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def home():
    try:
        from dashboard.auth import get_manageable_guilds
        guilds = get_manageable_guilds(session["access_token"])
        session["guilds"] = guilds
    except Exception as e:
        print(f"Error refreshing guilds on load: {e}")
        guilds = session.get("guilds", [])

    return render_template("home.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guilds=guilds,
        owner_id=str(config.BOT_OWNER_ID),
    )

@app.route("/dashboard/<guild_id>")
@guild_access_required
def server_overview(guild_id: str):
    guild_info = _get_guild_from_session(guild_id)
    meta       = db.get_guild_meta(guild_id) or {}
    modules    = db.get_guild_modules(guild_id)
    raw_stats  = db.get_guild_stats(guild_id, days=7)
    
    # Process stats for charting
    # stats format: {event_type: "message", event_label: "total", date_hour: "2026-07-19 14:00:00", count: 5}
    # We will just pass raw_stats as JSON and let frontend process it for flexibility.
    import json
    
    # Fetch channel names for top channels map
    channels = db.get_guild_channels(guild_id)
    channel_map = {str(c['channel_id']): c['channel_name'] for c in channels}
    recent_events = db.get_recent_guild_events(guild_id, limit=15)
    
    return render_template("server.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guild_id=guild_id,
        guild=guild_info,
        meta=meta,
        modules=modules,
        guild_settings=db.get_guild_settings(guild_id),
        active_page="overview",
        raw_stats_json=json.dumps(raw_stats),
        channel_map_json=json.dumps(channel_map),
        recent_events=recent_events,
    )


@app.route("/api/guild/<guild_id>/recent_events")
@guild_access_required
def api_guild_recent_events(guild_id: str):
    """API lấy tối đa 15 Recent Events gần nhất của server (định dạng JSON)."""
    events = db.get_recent_guild_events(guild_id, limit=15)
    return jsonify({"ok": True, "events": events})

# ─── Context helpers ───────────────────────────────────────────────────────────

def _server_ctx(guild_id: str, active_page: str, **extra) -> dict:
    """Build common template context for server pages."""
    ctx = {
        "user":        session["user"],
        "avatar":      session.get("avatar"),
        "guild_id":    guild_id,
        "guild":       _get_guild_from_session(guild_id),
        "modules":     db.get_guild_modules(guild_id),
        "active_page": active_page,
    }
    ctx.update(extra)
    return ctx

@app.route("/dashboard/<guild_id>/welcome", methods=["GET", "POST"])
@guild_access_required
def server_welcome(guild_id: str):
    if request.method == "POST":
        form = request.form
        fields = {
            "welcome_channel_id":  _safe_channel(guild_id, form.get("welcome_channel_id") or None),
            "welcome_message":     form.get("welcome_message", ""),
            "welcome_use_embed":   1 if form.get("welcome_use_embed") else 0,
            "welcome_embed_color": form.get("welcome_embed_color", "#57F287"),
            "welcome_embed_title": form.get("welcome_embed_title", ""),
            "welcome_bg_url":      form.get("welcome_bg_url", ""),
            "goodbye_channel_id":  _safe_channel(guild_id, form.get("goodbye_channel_id") or None),
            "goodbye_message":     form.get("goodbye_message", ""),
            "goodbye_use_embed":   1 if form.get("goodbye_use_embed") else 0,
            "goodbye_embed_color": form.get("goodbye_embed_color", "#ED4245"),
            "goodbye_embed_title": form.get("goodbye_embed_title", ""),
            "goodbye_bg_url":      form.get("goodbye_bg_url", ""),
        }
        db.upsert_guild(guild_id, **fields)
        flash("✅ Đã lưu cài đặt Welcome & Goodbye!", "success")
        return redirect(url_for("server_welcome", guild_id=guild_id))

    return render_template("welcome.html", **_server_ctx(
        guild_id, "welcome",
        settings=db.get_guild_settings(guild_id),
        channels=db.get_guild_channels(guild_id),
        meta=db.get_guild_meta(guild_id) or {},
    ))

@app.route("/dashboard/<guild_id>/autoroles", methods=["GET", "POST"])
@guild_access_required
def server_autoroles(guild_id: str):
    if request.method == "POST":
        form = request.form
        autoroles_user = form.getlist("autoroles_user")
        autoroles_bot = form.getlist("autoroles_bot")
        
        import json
        fields = {
            "autoroles_enabled": 1 if form.get("autoroles_enabled") else 0,
            "autoroles_user": json.dumps(autoroles_user),
            "autoroles_bot": json.dumps(autoroles_bot)
        }
        db.upsert_guild(guild_id, **fields)
        db.set_module(guild_id, "autoroles", bool(fields["autoroles_enabled"]))
        
        flash("✅ Đã lưu cài đặt Auto Roles!", "success")
        return redirect(url_for("server_autoroles", guild_id=guild_id))

    settings = db.get_guild_settings(guild_id)
    roles = db.get_guild_roles(guild_id)
    
    import json
    try:
        saved_user_roles = json.loads(settings.get("autoroles_user", "[]"))
        saved_bot_roles = json.loads(settings.get("autoroles_bot", "[]"))
    except Exception:
        saved_user_roles = []
        saved_bot_roles = []

    return render_template(
        "server_autoroles.html", 
        **_server_ctx(guild_id, active_page="autoroles"),
        settings=settings,
        roles=roles,
        saved_user_roles=saved_user_roles,
        saved_bot_roles=saved_bot_roles,
        meta=db.get_guild_meta(guild_id) or {}
    )

@app.route("/dashboard/<guild_id>/leveling", methods=["GET", "POST"])
@guild_access_required
def server_leveling(guild_id: str):
    if request.method == "POST":
        form = request.form
        
        # Save Leveling Settings
        settings = {
            "message_xp_min": int(form.get("message_xp_min", 15)),
            "message_xp_max": int(form.get("message_xp_max", 25)),
            "voice_xp": int(form.get("voice_xp", 10)),
            "announce_channel_id": _safe_channel(guild_id, form.get("announce_channel_id", "")),
            "announce_message": form.get("announce_message", "🎉 Chúc mừng {user} đã đạt cấp **{level}**!"),
            "stack_rewards": int(form.get("stack_rewards", 0))
        }
        db.set_leveling_settings(guild_id, settings)
        
        # Save Level Roles
        roles = {}
        for key, value in form.items():
            if key.startswith("level_role_") and value:
                level_str = key.replace("level_role_", "")
                roles[level_str] = value
                
        db.set_level_roles(guild_id, roles)
        
        flash("✅ Đã lưu cài đặt Leveling & XP!", "success")
        return redirect(url_for("server_leveling", guild_id=guild_id))
        
    settings = db.get_leveling_settings(guild_id)
    level_roles = db.get_level_roles(guild_id)
    channels = db.get_guild_channels(guild_id)
    roles = db.get_guild_roles(guild_id)
    
    return render_template(
        "server_leveling.html",
        **_server_ctx(guild_id, active_page="leveling"),
        settings=settings,
        level_roles=level_roles,
        channels=channels,
        roles=roles,
        meta=db.get_guild_meta(guild_id) or {}
    )

@app.route("/dashboard/<guild_id>/logger", methods=["GET", "POST"])
@guild_access_required
def server_logger(guild_id: str):
    if request.method == "POST":
        form = request.form
        settings = {
            "log_channel_id": _safe_channel(guild_id, form.get("log_channel_id") or None),
            "log_message_edit": 1 if "log_message_edit" in form else 0,
            "log_message_delete": 1 if "log_message_delete" in form else 0,
            "log_member_join_leave": 1 if "log_member_join_leave" in form else 0,
            "log_member_kick_ban": 1 if "log_member_kick_ban" in form else 0,
            "log_member_role_change": 1 if "log_member_role_change" in form else 0,
            "log_channel_change": 1 if "log_channel_change" in form else 0,
            "log_role_change": 1 if "log_role_change" in form else 0,
            "log_automod": 1 if "log_automod" in form else 0,
            "log_ticket": 1 if "log_ticket" in form else 0,
        }
        db.set_logger_settings(guild_id, settings)
        flash("✅ Đã lưu cài đặt Logging / Audit Log!", "success")
        return redirect(url_for("server_logger", guild_id=guild_id))

    settings = db.get_logger_settings(guild_id)
    channels = db.get_guild_channels(guild_id)
    return render_template(
        "server_logger.html",
        **_server_ctx(guild_id, active_page="logger"),
        settings=settings,
        channels=channels,
        meta=db.get_guild_meta(guild_id) or {}
    )

@app.route("/dashboard/<guild_id>/automod", methods=["GET", "POST"])
@guild_access_required
def server_automod(guild_id: str):
    if request.method == "POST":
        form = request.form
        
        import json
        bad_words = [w.strip() for w in form.get("bad_words", "").split(",") if w.strip()]
        blacklist_links = [l.strip() for l in form.get("blacklist_links", "").split(",") if l.strip()]
        whitelist_links = [l.strip() for l in form.get("whitelist_links", "").split(",") if l.strip()]
        immune_roles = form.getlist("immune_roles")
        spam_allowed_channels = form.getlist("spam_allowed_channels")
        
        fields = {
            "spam_enabled": 1 if form.get("spam_enabled") else 0,
            "bad_words_enabled": 1 if form.get("bad_words_enabled") else 0,
            "links_enabled": 1 if form.get("links_enabled") else 0,
            "anti_invite_enabled": 1 if form.get("anti_invite_enabled") else 0,
            "anti_caps_enabled": 1 if form.get("anti_caps_enabled") else 0,
            "anti_mentions_enabled": 1 if form.get("anti_mentions_enabled") else 0,
            "max_mentions": int(form.get("max_mentions", 5) or 5),
            "timeout_duration_minutes": int(form.get("timeout_duration_minutes", 5) or 5),
            "bad_words": json.dumps(bad_words),
            "blacklist_links": json.dumps(blacklist_links),
            "whitelist_links": json.dumps(whitelist_links),
            "immune_roles": immune_roles,
            "spam_allowed_channels": spam_allowed_channels,
            "notify_role_id": form.get("notify_role_id") or None,
            "log_channel_id": _safe_channel(guild_id, form.get("log_channel_id") or None),
            # Anti-Raid / Anti-Nuke
            "anti_raid_enabled": 1 if form.get("anti_raid_enabled") else 0,
            "raid_join_per_window": int(form.get("raid_join_per_window", 5) or 5),
            "raid_action": form.get("raid_action", "lockdown"),
            "anti_nuke_enabled": 1 if form.get("anti_nuke_enabled") else 0,
            "nuke_actions": form.getlist("nuke_actions"),
        }
        db.upsert_automod_settings(guild_id, **fields)
        # Enable module if any feature is enabled
        is_module_active = (fields["spam_enabled"] or fields["bad_words_enabled"] or 
                            fields["links_enabled"] or fields["anti_invite_enabled"] or 
                            fields["anti_caps_enabled"] or fields["anti_mentions_enabled"] or
                            fields["anti_raid_enabled"] or fields["anti_nuke_enabled"])
        db.set_module(guild_id, "automods", bool(is_module_active))
        
        flash("✅ Đã lưu cài đặt Automods!", "success")
        return redirect(url_for("server_automod", guild_id=guild_id))

    settings = db.get_automod_settings(guild_id)
    roles = db.get_guild_roles(guild_id)
    channels = db.get_guild_channels(guild_id)
    
    # Format lists back to comma-separated strings for the textarea
    bad_words_str = ", ".join(settings.get("bad_words", []))
    blacklist_links_str = ", ".join(settings.get("blacklist_links", []))
    whitelist_links_str = ", ".join(settings.get("whitelist_links", []))

    return render_template(
        "server_automod.html",
        **_server_ctx(guild_id, active_page="automod"),
        settings=settings,
        roles=roles,
        channels=channels,
        bad_words_str=bad_words_str,
        blacklist_links_str=blacklist_links_str,
        whitelist_links_str=whitelist_links_str,
        meta=db.get_guild_meta(guild_id) or {}
    )


@app.route("/dashboard/<guild_id>/verify", methods=["GET", "POST"])
@guild_access_required
def server_verify(guild_id: str):
    if request.method == "POST":
        form = request.form
        enabled = 1 if form.get("enabled") else 0
        fields = {
            "enabled": enabled,
            "hide_channels": 1 if form.get("hide_channels") else 0,
            "channel_id": _safe_channel(guild_id, form.get("channel_id") or None),
            "verified_role_id": form.get("verified_role_id") or None,
            "pending_role_id": form.get("pending_role_id") or None,
            "log_channel_id": _safe_channel(guild_id, form.get("log_channel_id") or None),
            "verify_text": form.get("verify_text", "").strip(),
            "button_label": form.get("button_label", "").strip() or "Tôi đã đọc nội quy & Xác thực",
        }
        db.upsert_verify_settings(guild_id, **fields)
        db.set_module(guild_id, "verify", bool(enabled))
        flash("✅ Đã lưu cài đặt Verify Gate!", "success")
        return redirect(url_for("server_verify", guild_id=guild_id))

    settings = db.get_verify_settings(guild_id)
    roles = db.get_guild_roles(guild_id)
    channels = db.get_guild_channels(guild_id)

    return render_template(
        "server_verify.html",
        **_server_ctx(guild_id, active_page="verify"),
        settings=settings,
        roles=roles,
        channels=channels,
        meta=db.get_guild_meta(guild_id) or {}
    )


@app.route("/dashboard/<guild_id>/moderation", methods=["GET", "POST"])
@guild_access_required
def server_moderation(guild_id: str):
    if request.method == "POST":
        form = request.form
        log_channel_id = _safe_channel(guild_id, form.get("log_channel_id") or None)
        # We can update logger settings or bot settings
        logger_s = db.get_logger_settings(guild_id)
        logger_s["log_channel_id"] = log_channel_id
        db.set_logger_settings(guild_id, logger_s)
        flash("✅ Đã lưu cấu hình Điều hành!", "success")
        return redirect(url_for("server_moderation", guild_id=guild_id))

    channels = db.get_guild_channels(guild_id)
    roles = db.get_guild_roles(guild_id)
    logger_s = db.get_logger_settings(guild_id)
    warn_count = db.get_mod_warnings_count_sync(guild_id)

    return render_template(
        "server_moderation.html",
        **_server_ctx(guild_id, active_page="moderation"),
        channels=channels,
        roles=roles,
        logger_settings=logger_s,
        warn_count=warn_count,
        meta=db.get_guild_meta(guild_id) or {},
    )


@app.route("/dashboard/<guild_id>/birthday", methods=["GET", "POST"])
@guild_access_required
def server_birthday(guild_id: str):
    if request.method == "POST":
        form = request.form
        fields = {
            "channel_id": _safe_channel(guild_id, form.get("channel_id") or None),
            "role_id": form.get("role_id") or None,
            "message_template": form.get("message_template", "").strip() or None,
            "gift_coins": int(form.get("gift_coins", 500)),
            "gift_xp": int(form.get("gift_xp", 200)),
        }
        db.upsert_birthday_settings_sync(guild_id, **fields)
        flash("✅ Đã lưu cấu hình Sinh nhật!", "success")
        return redirect(url_for("server_birthday", guild_id=guild_id))

    channels = db.get_guild_channels(guild_id)
    roles = db.get_guild_roles(guild_id)
    bday_settings = db.get_birthday_settings_sync(guild_id)
    now_month = datetime.now(timezone.utc).month
    bday_count = db.get_birthdays_this_month_count(guild_id, now_month)

    return render_template(
        "server_birthday.html",
        **_server_ctx(guild_id, active_page="birthday"),
        channels=channels,
        roles=roles,
        birthday_settings=bday_settings,
        bday_count=bday_count,
        meta=db.get_guild_meta(guild_id) or {},
    )


@app.route("/dashboard/<guild_id>/embeds")
@guild_access_required
def server_embeds(guild_id: str):
    return render_template("embeds.html", **_server_ctx(
        guild_id, "embeds",
        embeds=db.get_saved_embeds(guild_id),
        channels=db.get_guild_channels(guild_id),
        now=datetime.now(timezone.utc).strftime("%H:%M"),
    ))


@app.route("/dashboard/<guild_id>/modules", methods=["GET", "POST"])
@guild_access_required
def server_modules(guild_id: str):
    if request.method == "POST":
        # Save bot admin roles
        bot_admin_roles = request.form.getlist("bot_admin_roles")
        import json
        db.upsert_guild(guild_id, bot_admin_roles=json.dumps(bot_admin_roles))
        
        flash("✅ Đã cập nhật Modules & Quyền quản trị!", "success")
        return redirect(url_for("server_modules", guild_id=guild_id))

    guild_settings = db.get_guild_settings(guild_id)
    import json
    try:
        saved_admin_roles = json.loads(guild_settings.get("bot_admin_roles", "[]") or "[]")
    except Exception:
        saved_admin_roles = []
        
    roles = db.get_guild_roles(guild_id)

    return render_template(
        "modules.html", 
        **_server_ctx(guild_id, "modules"),
        saved_admin_roles=saved_admin_roles,
        roles=roles
    )


# ─── Commands data registry ────────────────────────────────────────────────────

from commands_data import _COMMANDS_DATA

@app.route("/dashboard/<guild_id>/commands")
@guild_access_required
def server_commands(guild_id: str):
    from dashboard.commands_catalog import get_localized_commands_data
    ui_lang = session.get("ui_lang", "vi")
    localized_data = get_localized_commands_data(ui_lang)
    total = sum(len(c["commands"]) for c in localized_data)
    return render_template("commands.html", **_server_ctx(
        guild_id, "commands",
        commands_data=localized_data,
        total_count=total,
    ))



@app.route("/dashboard/<guild_id>/music")
@guild_access_required
def server_music(guild_id: str):
    import shutil
    try:
        import davey
        has_davey = True
    except ImportError:
        has_davey = False

    has_ffmpeg = shutil.which("ffmpeg") is not None
    playlists = db.get_playlists(guild_id)
    
    grouped_playlists = {}
    for pl in playlists:
        c_id = pl.get("creator_id") or "Unknown"
        c_name = pl.get("creator_name") or "Hệ thống"
        if c_id not in grouped_playlists:
            grouped_playlists[c_id] = {"name": c_name, "playlists": []}
        grouped_playlists[c_id]["playlists"].append(pl)

    return render_template("music.html", **_server_ctx(
        guild_id, "music",
        has_davey=has_davey,
        has_ffmpeg=has_ffmpeg,
        grouped_playlists=grouped_playlists,
    ))


@app.route("/dashboard/<guild_id>/tickets")
@guild_access_required
def server_tickets(guild_id: str):
    panels = db.get_ticket_panels(guild_id) or []
    text_channels = db.get_guild_channels(guild_id) or []
    categories = db.get_guild_categories(guild_id) or []
    
    # Fetch roles dynamically using bot token with fallback
    roles = []
    try:
        if config.TOKEN:
            resp = requests.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/roles",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5
            )
            if resp.status_code == 200:
                roles = [r for r in resp.json() if r.get("name") != "@everyone"]
    except Exception as e:
        print(f"Error fetching roles for tickets: {e}")

    if not roles:
        roles = db.get_guild_roles(guild_id) or []

    return render_template("tickets.html", **_server_ctx(
        guild_id, "tickets",
        panels=panels,
        text_channels=text_channels,
        categories=categories,
        roles=roles,
    ))


@app.route("/dashboard/<guild_id>/reactionroles")
@guild_access_required
def server_reactionroles(guild_id: str):
    panels = db.get_reaction_roles_panels(guild_id)
    text_channels = db.get_guild_channels(guild_id) or []
    
    # Fetch roles dynamically using bot token
    roles = []
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/roles",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=5
        )
        if resp.status_code == 200:
            roles = [r for r in resp.json() if r["name"] != "@everyone"]
    except Exception as e:
        print(f"Error fetching roles: {e}")

    return render_template("reactionroles.html", **_server_ctx(
        guild_id, "reactionroles",
        panels=panels,
        text_channels=text_channels,
        roles=roles,
    ))


def fetch_track_info_simple(query: str) -> dict:
    import re

    # P1.8: chống SSRF — URL do người dùng nhập phải là http(s) công khai hợp lệ.
    # Query thường (không phải URL) sẽ đi qua youtube search bên dưới.
    if query.startswith(("http://", "https://")) and not is_safe_http_url(query):
        return {
            "title": "URL không hợp lệ (bị chặn bảo mật)",
            "url": "",
            "duration": -1,
            "webpage_url": "",
            "thumbnail": "",
            "uploader": "—",
        }

    video_id = None
    webpage_url = None

    try:
        if query.startswith(("http://", "https://")):
            webpage_url = query
            match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", webpage_url)
            if match:
                video_id = match.group(1)
        else:
            import urllib.parse as _urlparse
            resp = requests.get(f"https://www.youtube.com/results?search_query={_urlparse.quote_plus(query)}", timeout=5)
            match = re.search(r"\"videoId\":\"([0-9A-Za-z_-]{11})\"", resp.text)
            if match:
                video_id = match.group(1)
                webpage_url = f"https://www.youtube.com/watch?v={video_id}"
                
        if not video_id or not webpage_url:
            return {
                "title": "Video YouTube" if query.startswith("http") else query[:50] + "...",
                "url": "", # Set rỗng để tránh lỗi database
                "duration": -1,
                "webpage_url": webpage_url or query,
                "thumbnail": "",
                "uploader": "Unknown"
            }
            
        resp = requests.get(f"https://www.youtube.com/oembed?url={webpage_url}&format=json", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "title": data.get("title", "Unknown"),
                "url": "", # Set rỗng để khi phát nhạc (_play_track) bot tự đi tìm stream URL
                "duration": -1,
                "webpage_url": webpage_url,
                "thumbnail": data.get("thumbnail_url", ""),
                "uploader": data.get("author_name", "—")
            }
    except Exception as e:
        print(f"Web fetch track error: {e}")

    return {
        "title": "Video YouTube" if query.startswith("http") else query[:50] + "...",
        "url": "",
        "duration": -1,
        "webpage_url": webpage_url or query,
        "thumbnail": "",
        "uploader": "Unknown"
    }


@app.route("/dashboard/<guild_id>/music/playlist/create", methods=["POST"])
@guild_access_required
def create_playlist_route(guild_id: str):
    name = request.form.get("playlist_name", "").strip()
    if not name:
        flash("❌ Tên playlist không được để trống!", "error")
    else:
        user = session.get("user", {})
        creator_id = user.get("id", "")
        creator_name = user.get("global_name") or user.get("username", "Unknown")
        db.create_playlist(guild_id, name, creator_id, creator_name)
        flash(f"✅ Đã tạo playlist '{name}'!", "success")
    return redirect(url_for("server_music", guild_id=guild_id))


@app.route("/dashboard/<guild_id>/music/playlist/<int:playlist_id>/delete", methods=["POST"])
@guild_access_required
def delete_playlist_route(guild_id: str, playlist_id: int):
    playlist = db.get_playlist(playlist_id)
    user = session.get("user", {})
    if playlist and playlist.get("guild_id") == guild_id:
        if playlist.get("creator_id") and playlist.get("creator_id") != user.get("id"):
            flash("❌ Bạn không có quyền xóa playlist của người khác!", "error")
        else:
            db.delete_playlist(playlist_id, guild_id)
            flash(f"✅ Đã xóa playlist '{playlist.get('name')}'!", "success")
    else:
        flash("❌ Không tìm thấy playlist!", "error")
    return redirect(url_for("server_music", guild_id=guild_id))


@app.route("/dashboard/<guild_id>/music/playlist/<int:playlist_id>/add", methods=["POST"])
@guild_access_required
def add_track_route(guild_id: str, playlist_id: int):
    playlist = db.get_playlist(playlist_id)
    user = session.get("user", {})
    if not playlist or playlist.get("guild_id") != guild_id:
        flash("❌ Không tìm thấy playlist!", "error")
    elif playlist.get("creator_id") and playlist.get("creator_id") != user.get("id"):
        flash("❌ Bạn không có quyền thêm bài hát vào playlist của người khác!", "error")
        return redirect(url_for("server_music", guild_id=guild_id))
    
    query = request.form.get("track_query", "").strip()
    if not query:
        flash("❌ Vui lòng nhập link hoặc tên bài hát!", "error")
    else:
        track_info = fetch_track_info_simple(query)
        db.add_track_to_playlist(playlist_id, track_info)
        flash(f"✅ Đã thêm '{track_info['title']}' vào playlist!", "success")
    return redirect(url_for("server_music", guild_id=guild_id))


@app.route("/dashboard/<guild_id>/music/playlist/track/<int:track_id>/delete", methods=["POST"])
@guild_access_required
def delete_track_route(guild_id: str, track_id: int):
    # Kiểm ownership: track phải thuộc playlist của ĐÚNG guild này (chống xóa chéo server)
    playlist = db.get_playlist_of_track(track_id)
    user = session.get("user", {})
    if not playlist or str(playlist.get("guild_id")) != str(guild_id):
        flash("❌ Không tìm thấy bài hát trong server này!", "error")
        return redirect(url_for("server_music", guild_id=guild_id))
    if playlist.get("creator_id") and str(playlist.get("creator_id")) != str(user.get("id")):
        flash("❌ Bạn không có quyền xóa bài trong playlist của người khác!", "error")
        return redirect(url_for("server_music", guild_id=guild_id))
    db.delete_track_from_playlist(track_id)
    flash("✅ Đã xóa bài hát khỏi playlist!", "success")
    return redirect(url_for("server_music", guild_id=guild_id))




# ─── Routes: Economy & Shop ───────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/economy", methods=["GET", "POST"])
@guild_access_required
def server_economy(guild_id: str):
    if request.method == "POST":
        daily_amount = int(request.form.get("daily_amount", 100))
        streak_bonus = int(request.form.get("streak_bonus", 20))
        starting_balance = int(request.form.get("starting_balance", 50))
        currency_symbol = request.form.get("currency_symbol", "🪙").strip() or "🪙"
        currency_name = request.form.get("currency_name", "Coins").strip() or "Coins"
        
        db.update_economy_settings(guild_id, daily_amount, streak_bonus, starting_balance, currency_symbol, currency_name)
        flash("✅ Đã lưu cài đặt Economy thành công!", "success")
        return redirect(url_for("server_economy", guild_id=guild_id))

    eco_settings = db.get_economy_settings(guild_id)
    shop_items = db.get_economy_shop(guild_id)
    roles = db.get_guild_roles(guild_id)
    top_users = db.get_top_economy_users(guild_id, limit=1)
    richest_user = top_users[0] if top_users else None
    
    # Calculate total circulating currency
    all_users = db.get_top_economy_users(guild_id, limit=1000)
    total_circulating = sum(u.get("total", 0) for u in all_users)

    return render_template(
        "server_economy.html",
        **_server_ctx(guild_id, active_page="economy"),
        eco_settings=eco_settings,
        shop_items=shop_items,
        roles=roles,
        richest_user=richest_user,
        total_circulating=total_circulating
    )


@app.route("/dashboard/<guild_id>/economy/add_item", methods=["POST"])
@guild_access_required
def server_economy_add_item(guild_id: str):
    name = request.form.get("name", "").strip()
    role_id = request.form.get("role_id", "").strip()
    price = int(request.form.get("price", 100))
    stock = int(request.form.get("stock", -1))

    if not name or not role_id:
        flash("❌ Vui lòng nhập đầy đủ tên và chọn Role!", "error")
    else:
        db.add_economy_shop_item(guild_id, role_id, name, price, stock)
        flash(f"✅ Đã thêm '{name}' vào Cửa hàng Shop!", "success")
    return redirect(url_for("server_economy", guild_id=guild_id))


@app.route("/dashboard/<guild_id>/economy/delete_item/<int:item_id>", methods=["POST"])
@guild_access_required
def server_economy_delete_item(guild_id: str, item_id: int):
    db.delete_economy_shop_item(item_id, guild_id)
    flash("✅ Đã xóa vật phẩm khỏi Cửa hàng!", "success")
    return redirect(url_for("server_economy", guild_id=guild_id))


# ─── Routes: Temp Voice Hub ───────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/tempvoice", methods=["GET", "POST"])
@guild_access_required
def server_tempvoice(guild_id: str):
    if request.method == "POST":
        enabled = 1 if request.form.get("enabled") == "1" else 0
        hub_channel_id = _safe_channel(guild_id, request.form.get("hub_channel_id", "").strip())
        category_id = _safe_channel(guild_id, request.form.get("category_id", "").strip())
        name_template = request.form.get("name_template", "🔊 Phòng của {user}").strip() or "🔊 Phòng của {user}"
        default_limit = int(request.form.get("default_limit", 0))

        db.update_tempvoice_settings(guild_id, enabled, hub_channel_id, category_id, name_template, default_limit)
        # Update guild_modules toggle
        db.set_module_enabled(guild_id, "tempvoice", bool(enabled))
        flash("✅ Đã lưu cài đặt Temp Voice thành công!", "success")
        return redirect(url_for("server_tempvoice", guild_id=guild_id))

    tv_settings = db.get_tempvoice_settings(guild_id)
    active_channels = db.get_active_temp_channels(guild_id)
    
    voice_channels = db.get_guild_voice_channels(guild_id)
    categories = db.get_guild_categories(guild_id)

    return render_template(
        "server_tempvoice.html",
        **_server_ctx(guild_id, active_page="tempvoice"),
        tv_settings=tv_settings,
        active_channels=active_channels,
        voice_channels=voice_channels,
        categories=categories
    )


@app.route("/dashboard/<guild_id>/tempvoice/delete_channel/<channel_id>", methods=["POST"])
@guild_access_required
def server_tempvoice_delete_channel(guild_id: str, channel_id: str):
    import database as db_mod
    with sqlite3.connect(db_mod.DB_PATH) as conn:
        # Scope theo guild_id — chặn xóa phòng voice tạm của server khác
        conn.execute(
            "DELETE FROM tempvoice_active WHERE channel_id = ? AND guild_id = ?",
            (channel_id, guild_id),
        )
        conn.commit()
    flash("✅ Đã xóa phòng voice tạm thời!", "success")
    return redirect(url_for("server_tempvoice", guild_id=guild_id))


# ─── Routes: Custom Commands ───────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/customcommands", methods=["GET"])
@guild_access_required
def server_customcommands(guild_id: str):
    custom_cmds = db.get_custom_commands(guild_id)

    return render_template(
        "server_customcommands.html",
        **_server_ctx(guild_id, active_page="customcommands"),
        custom_cmds=custom_cmds
    )


@app.route("/dashboard/<guild_id>/customcommands/add", methods=["POST"])
@guild_access_required
def server_customcommands_add(guild_id: str):
    trigger = request.form.get("trigger", "").strip()
    match_type = request.form.get("match_type", "exact")
    response_text = request.form.get("response_text", "").strip()
    
    embed_title = request.form.get("embed_title", "").strip()
    embed_json = None
    if embed_title:
        embed_dict = {
            "title": embed_title,
            "color": request.form.get("embed_color", "#5865F2"),
            "description": request.form.get("embed_description", ""),
            "image_url": request.form.get("embed_image", ""),
            "footer_text": request.form.get("embed_footer", "")
        }
        embed_json = json.dumps(embed_dict, ensure_ascii=False)

    if not trigger:
        flash("❌ Từ khóa kích hoạt không được để trống!", "error")
    else:
        user = session.get("user", {})
        db.add_custom_command(guild_id, trigger, match_type, response_text, embed_json, creator_id=user.get("id", ""))
        flash(f"✅ Đã tạo lệnh '{trigger}' thành công!", "success")

    return redirect(url_for("server_customcommands", guild_id=guild_id))


@app.route("/dashboard/<guild_id>/customcommands/delete/<int:cmd_id>", methods=["POST"])
@guild_access_required
def server_customcommands_delete(guild_id: str, cmd_id: int):
    db.delete_custom_command(cmd_id, guild_id)
    flash("✅ Đã xóa lệnh tùy biến!", "success")
    return redirect(url_for("server_customcommands", guild_id=guild_id))


# ─── Routes: AI Assistant ──────────────────────────────────────────────────────

@app.route("/dashboard/<guild_id>/ai", methods=["GET", "POST"])
@guild_access_required
def server_ai(guild_id: str):
    if request.method == "POST":
        enabled = 1 if request.form.get("enabled") == "1" else 0
        ai_channel_id = _safe_channel(guild_id, request.form.get("ai_channel_id", "").strip())
        personality_preset = request.form.get("personality_preset", "friendly")
        custom_prompt = request.form.get("custom_prompt", "").strip()
        allow_ask = 1 if request.form.get("allow_ask") == "1" else 0
        allow_summarize = 1 if request.form.get("allow_summarize") == "1" else 0
        rate_limit = int(request.form.get("rate_limit", 5))

        old_s = db.get_ai_settings(guild_id)
        db.update_ai_settings(guild_id, enabled, ai_channel_id, personality_preset, custom_prompt, allow_ask, allow_summarize, rate_limit, old_s.get("api_key", ""))
        db.set_module_enabled(guild_id, "ai", bool(enabled))
        flash("✅ Đã lưu cấu hình AI Assistant thành công!", "success")
        return redirect(url_for("server_ai", guild_id=guild_id))

    ai_settings = db.get_ai_settings(guild_id)
    channels = db.get_guild_channels(guild_id)
    text_channels = [c for c in channels if c.get("channel_type") == 0]

    return render_template(
        "server_ai.html",
        **_server_ctx(guild_id, active_page="ai"),
        ai_settings=ai_settings,
        text_channels=text_channels
    )


# ─── Bot Owner / Admin Panel ───────────────────────────────────────────────────

def owner_required(f):
    """Decorator: chỉ Bot Owner mới được truy cập."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        user_id = str(session["user"].get("id", ""))
        owner_id = str(config.BOT_OWNER_ID)
        if not owner_id or owner_id == "0" or user_id != owner_id:
            flash("⛔ Bạn không có quyền truy cập khu vực này.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated


def stepup_required(f):
    """Decorator: yêu cầu xác thực mật khẩu cấp cao (Step-Up Auth) trong vòng 15 phút."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_pass = getattr(config, "ADMIN_PASSWORD", None)
        if admin_pass:
            until = session.get("stepup_auth_until", 0)
            if _time.time() > until:
                return jsonify({
                    "ok": False,
                    "error": "stepup_required",
                    "message": "🔒 Yêu cầu xác thực mật khẩu quản trị cấp cao để thực hiện thao tác này."
                }), 401
        return f(*args, **kwargs)
    return decorated


def _get_all_bot_guilds_detailed() -> list:
    """Lấy danh sách tất cả server bot đang có mặt, kèm thông tin chi tiết."""
    try:
        resp = requests.get(
            f"{config.DISCORD_API_BASE}/users/@me/guilds",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=10,
        )
        if not resp.ok:
            return []
        guilds = resp.json()
    except Exception as e:
        print(f"[Admin] Error fetching bot guilds: {e}")
        return []

    # Bổ sung thông tin icon_url
    result = []
    for g in guilds:
        g["icon_url"] = (
            f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
            if g.get("icon") else None
        )
        # Lấy member count từ guild_meta cache trong DB
        meta = db.get_guild_meta(g["id"]) or {}
        g["member_count"] = meta.get("member_count", 0)
        g["cached_name"]  = meta.get("guild_name") or g.get("name", "Unknown")
        result.append(g)
    return result


_last_cpu_times = None

def get_system_hardware_stats() -> dict:
    """Đọc thông số RAM, Uptime và trạng thái hệ thống cho Termux Linux và Windows."""
    import re
    stats = {
        "ram_percent": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "uptime": "24/7 Active",
        "host_platform": "Tecno Pova 2 • Termux ARM64" if os.name != "nt" else "Windows Host",
        "status": "healthy"
    }
    
    # 1. RAM Telemetry
    try:
        if os.path.exists("/proc/meminfo"):
            meminfo = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        if v.isdigit():
                            meminfo[k] = int(v)
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0) + meminfo.get("Buffers", 0) + meminfo.get("Cached", 0))
            if total_kb > 0:
                used_kb = total_kb - avail_kb
                stats["ram_total_gb"] = round(total_kb / (1024 * 1024), 2)
                stats["ram_used_gb"] = round(used_kb / (1024 * 1024), 2)
                stats["ram_percent"] = round((used_kb / total_kb) * 100, 1)
        elif os.name == "nt":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_b = stat.ullTotalPhys
                avail_b = stat.ullAvailPhys
                used_b = total_b - avail_b
                stats["ram_total_gb"] = round(total_b / (1024**3), 2)
                stats["ram_used_gb"] = round(used_b / (1024**3), 2)
                stats["ram_percent"] = round(float(stat.dwMemoryLoad), 1)
    except Exception as e:
        print(f"[Telemetry] Error reading RAM: {e}")

    # 2. Uptime Telemetry
    try:
        if os.name != "nt":
            res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=2)
            out = res.stdout.strip()
            if "up " in out:
                m = re.search(r"up\s+([^,]+,\s*[^,]+)", out)
                if m:
                    stats["uptime"] = m.group(1).replace("days", "ngày").replace("day", "ngày").strip()
                else:
                    part = out.split("up ")[1].split(",")[0].strip()
                    stats["uptime"] = part.replace("days", "ngày").replace("day", "ngày")
    except Exception as e:
        print(f"[Telemetry] Error reading Uptime: {e}")

    return stats


@app.route("/admin")
@owner_required
def admin_panel():
    guilds    = _get_all_bot_guilds_detailed()
    blacklist = db.get_blacklist()
    blacklist_ids = {b["guild_id"] for b in blacklist}
    global_ai_key = db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
    global_ai_model = db.get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
    telemetry = get_system_hardware_stats()
    activity_logs = db.get_system_activity_logs(limit=50, days_ttl=7)
    return render_template(
        "admin.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guilds=guilds,
        blacklist=blacklist,
        blacklist_ids=blacklist_ids,
        total_servers=len(guilds),
        total_blacklist=len(blacklist),
        global_ai_key=global_ai_key,
        global_ai_model=global_ai_model,
        telemetry=telemetry,
        activity_logs=activity_logs,
    )


@app.route("/api/admin/telemetry")
@owner_required
def api_admin_telemetry():
    """Trả về thông số % CPU, % RAM và dung lượng RAM hiện tại."""
    stats = get_system_hardware_stats()
    return jsonify({"ok": True, **stats})


@app.route("/api/admin/activity_logs")
@owner_required
def api_admin_activity_logs():
    """Trả về tối đa 50 log hoạt động gần nhất trong vòng 7 ngày (tự động xóa log > 7 ngày)."""
    logs = db.get_system_activity_logs(limit=50, days_ttl=7)
    return jsonify({"ok": True, "logs": logs})


@app.route("/admin/ai_key", methods=["POST"])
@owner_required
def admin_save_ai_key():
    key = request.form.get("global_ai_key", "").strip()
    model = request.form.get("global_ai_model", "").strip()
    custom_model = request.form.get("custom_ai_model", "").strip()
    if model == "custom" and custom_model:
        model = custom_model

    db.set_global_setting("gemini_api_key", key)
    if model:
        db.set_global_setting("global_ai_model", model)
    flash("✅ Đã lưu cấu hình AI API Key & Model toàn cục thành công!", "success")
    return redirect(url_for("admin_panel") + "#ai_settings")


@app.route("/api/admin/test_ai_key", methods=["POST"])
@limiter.limit("20/minute")
@owner_required
def api_admin_test_ai_key():
    import urllib.request, time
    data = request.get_json(silent=True) or {}
    key = data.get("api_key") or db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
    key = key.strip()
    target_model = data.get("model") or db.get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
    if not key:
        return jsonify({"ok": False, "status": "no_key", "message": "Chưa có API Key (Đang dùng Smart Local Responder)"})

    # 1. Groq Cloud (Key starts with gsk_)
    if key.startswith("gsk_"):
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        groq_payload = json.dumps({
            "model": target_model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10
        }).encode("utf-8")
        req = urllib.request.Request(
            groq_url,
            data=groq_payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                latency = int((time.time() - t0) * 1000)
                if resp.status == 200:
                    return jsonify({
                        "ok": True,
                        "status": "active",
                        "model": f"Groq Cloud ({target_model})",
                        "latency_ms": latency,
                        "message": f"Kết nối Groq Cloud siêu tốc thành công ({latency}ms) với model {target_model}"
                    })
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                err_msg = err_data.get("error", {}).get("message", f"HTTP {e.code}")
            except Exception:
                err_msg = f"HTTP {e.code}"
            return jsonify({"ok": False, "status": "invalid_key", "message": f"Lỗi Groq API ({err_msg})"})
        except Exception as e:
            return jsonify({"ok": False, "status": "error", "message": f"Lỗi kết nối Groq: {str(e)}"})

    # 2. OpenRouter (Key starts with sk-or-)
    if key.startswith("sk-or-"):
        or_url = "https://openrouter.ai/api/v1/chat/completions"
        or_payload = json.dumps({
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10
        }).encode("utf-8")
        req = urllib.request.Request(
            or_url,
            data=or_payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://zerynbot.id.vn"
            },
            method="POST"
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                latency = int((time.time() - t0) * 1000)
                if resp.status == 200:
                    return jsonify({
                        "ok": True,
                        "status": "active",
                        "model": "OpenRouter Free (Llama 3.3)",
                        "latency_ms": latency,
                        "message": f"Kết nối OpenRouter Free thành công ({latency}ms)"
                    })
        except Exception as e:
            return jsonify({"ok": False, "status": "invalid_key", "message": f"Lỗi kết nối OpenRouter: {str(e)}"})

    # 3. Validate key format hint
    if key.startswith("AQ."):
        return jsonify({
            "ok": False,
            "status": "wrong_key_type",
            "message": "Chuỗi bạn vừa dán bắt đầu bằng 'AQ.' (đây là Project Token, không phải API Key). Hãy lấy API Key Google (AIzaSy...) hoặc tạo nhanh key Groq (gsk_...) tại https://console.groq.com."
        })

    # 4. Test key with Google Gemini API
    models_to_test = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    payload = json.dumps({"contents": [{"parts": [{"text": "Hi"}]}]}).encode("utf-8")
    
    t0 = time.time()
    last_err_detail = ""
    for model in models_to_test:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                latency = int((time.time() - t0) * 1000)
                if resp.status == 200:
                    return jsonify({
                        "ok": True,
                        "status": "active",
                        "model": f"Google Gemini ({model})",
                        "latency_ms": latency,
                        "message": f"API Key hoạt động hoàn hảo với {model} ({latency}ms)"
                    })
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                last_err_detail = err_data.get("error", {}).get("message", f"HTTP {e.code}")
            except Exception:
                last_err_detail = f"HTTP {e.code}"
            continue
        except Exception as e:
            last_err_detail = str(e)
            continue

    if "API_KEY_INVALID" in last_err_detail or "400" in last_err_detail or "401" in last_err_detail or "UNAUTHENTICATED" in last_err_detail:
        msg = "API Key không hợp lệ. Bạn có thể lấy key Google (bắt đầu bằng AIzaSy...) tại https://aistudio.google.com hoặc tạo key Groq (bắt đầu bằng gsk_...) tại https://console.groq.com."
    else:
        msg = f"Lỗi Google API: {last_err_detail}"

    return jsonify({"ok": False, "status": "invalid_key", "message": msg})


@app.route("/admin/kick/<guild_id>", methods=["POST"])
@owner_required
def admin_kick_guild(guild_id: str):
    """Buộc bot rời khỏi server và thêm vào blacklist."""
    reason = request.form.get("reason", "Bị kick bởi Owner").strip() or "Bị kick bởi Owner"

    # Lấy tên server trước khi kick
    guild_name = request.form.get("guild_name", "Unknown")

    # Gọi Discord API để bot rời server
    try:
        resp = requests.delete(
            f"{config.DISCORD_API_BASE}/users/@me/guilds/{guild_id}",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=10,
        )
        if resp.status_code not in (200, 204):
            flash(f"❌ Discord API trả về lỗi: {resp.status_code} — {resp.text}", "error")
            return redirect(url_for("admin_panel"))
    except Exception as e:
        flash(f"❌ Không thể kết nối đến Discord API: {e}", "error")
        return redirect(url_for("admin_panel"))

    # Thêm vào blacklist
    db.add_to_blacklist(guild_id, guild_name, reason)
    flash(f"✅ Bot đã rời khỏi **{guild_name}** và server đã được thêm vào Blacklist!", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/unblacklist/<guild_id>", methods=["POST"])
@owner_required
def admin_unblacklist(guild_id: str):
    """Xóa server khỏi blacklist."""
    db.remove_from_blacklist(guild_id)
    flash("✅ Đã xóa server khỏi Blacklist!", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/invite/<guild_id>", methods=["POST"])
@owner_required
def admin_invite_guild(guild_id: str):
    """Tạo instant invite link cho một server để Owner có thể gia nhập."""
    try:
        cr = requests.get(
            f"{config.DISCORD_API_BASE}/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=8,
        )
        if not cr.ok:
            return jsonify({"ok": False, "error": f"Không thể lấy danh sách kênh (HTTP {cr.status_code})"}), 400
        channels = cr.json()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Lỗi kết nối Discord API: {e}"}), 500

    candidate_channels = [c for c in channels if c.get("type") in (0, 5, 2)]
    if not candidate_channels:
        return jsonify({"ok": False, "error": "Server không có kênh phù hợp để tạo link mời."}), 400

    # Ưu tiên text channels (type 0) trước
    candidate_channels.sort(key=lambda c: (0 if c.get("type") == 0 else 1, c.get("position", 999)))

    for ch in candidate_channels:
        ch_id = ch["id"]
        try:
            inv_resp = requests.post(
                f"{config.DISCORD_API_BASE}/channels/{ch_id}/invites",
                headers={
                    "Authorization": f"Bot {config.TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "max_age": 86400,
                    "max_uses": 0,
                    "unique": False
                },
                timeout=5
            )
            if inv_resp.status_code in (200, 201):
                inv_data = inv_resp.json()
                code = inv_data.get("code")
                if code:
                    return jsonify({
                        "ok": True,
                        "code": code,
                        "url": f"https://discord.gg/{code}",
                        "channel_name": ch.get("name", "kênh")
                    })
        except Exception:
            continue

    return jsonify({"ok": False, "error": "Bot không có quyền Create Invite (Tạo liên kết mời) ở bất kỳ kênh nào trong server này."}), 403



@app.route("/admin/broadcast", methods=["POST"])
@limiter.limit("10/minute")
@owner_required
def admin_broadcast():
    """Gửi thông báo broadcast đến các server đã chọn."""

    title   = request.form.get("broadcast_title", "📢 Thông báo từ Bot Owner").strip()
    message = request.form.get("broadcast_message", "").strip()
    color   = request.form.get("broadcast_color", "#5865F2").strip()
    targets = request.form.getlist("target_guilds")   # danh sách guild_id được chọn
    send_all = request.form.get("send_all") == "1"

    if not message:
        flash("❌ Nội dung thông báo không được để trống!", "error")
        return redirect(url_for("admin_panel"))

    # Chuyển hex color → int
    try:
        color_int = int(color.lstrip("#"), 16)
    except Exception:
        color_int = 0x5865F2

    # Lấy danh sách guild cần gửi
    all_guilds = _get_all_bot_guilds_detailed()
    blacklist_ids = {b["guild_id"] for b in db.get_blacklist()}

    if send_all:
        target_guilds = [g for g in all_guilds if g["id"] not in blacklist_ids]
    else:
        target_guilds = [g for g in all_guilds if g["id"] in targets and g["id"] not in blacklist_ids]

    if not target_guilds:
        flash("❌ Không có server nào để gửi thông báo!", "error")
        return redirect(url_for("admin_panel"))

    success_count = 0
    fail_count    = 0

    for guild in target_guilds:
        guild_id = guild["id"]
        # Lấy system channel hoặc kênh text đầu tiên bot có thể gửi
        channel_id = None

        # Thử lấy guild info từ Discord API để có system_channel_id
        try:
            gr = requests.get(
                f"{config.DISCORD_API_BASE}/guilds/{guild_id}",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5,
            )
            if gr.ok:
                gdata = gr.json()
                channel_id = gdata.get("system_channel_id")
        except Exception:
            pass

        # Nếu không có system channel, thử kênh text đầu tiên
        if not channel_id:
            try:
                cr = requests.get(
                    f"{config.DISCORD_API_BASE}/guilds/{guild_id}/channels",
                    headers={"Authorization": f"Bot {config.TOKEN}"},
                    timeout=5,
                )
                if cr.ok:
                    channels = cr.json()
                    text_channels = [c for c in channels if c.get("type") == 0]
                    if text_channels:
                        # Sắp xếp theo position
                        text_channels.sort(key=lambda c: c.get("position", 999))
                        channel_id = text_channels[0]["id"]
            except Exception:
                pass

        if not channel_id:
            fail_count += 1
            continue

        # Gửi embed
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": message,
                    "color": color_int,
                    "footer": {"text": "Thông báo từ Bot Owner"},
                }]
            }
            mr = requests.post(
                f"{config.DISCORD_API_BASE}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {config.TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=8,
            )
            if mr.status_code in (200, 201):
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    flash(
        f"📢 Đã gửi thông báo: ✅ {success_count} server thành công"
        + (f", ❌ {fail_count} thất bại." if fail_count else "."),
        "success" if success_count else "error",
    )
    return redirect(url_for("admin_panel"))


# ─── System / Terminal Control Routes ──────────────────────────────────────────

@app.route("/admin/system/stepup", methods=["POST"])
@limiter.limit("5/minute")
@owner_required
def admin_system_stepup():
    """Xác thực mật khẩu cấp cao (Step-Up Auth), mở khóa 15 phút."""
    data = request.get_json(silent=True) or request.form or {}
    password = data.get("password", "")
    admin_pass = getattr(config, "ADMIN_PASSWORD", None)

    if not admin_pass:
        session["stepup_auth_until"] = _time.time() + 900
        return jsonify({"ok": True, "message": "Step-Up auth granted (no password configured)"}), 200

    if secrets.compare_digest(str(password), str(admin_pass)):
        session["stepup_auth_until"] = _time.time() + 900
        return jsonify({"ok": True, "message": "✅ Xác thực thành công! Quyền quản trị mở trong 15 phút."}), 200

    return jsonify({"ok": False, "message": "❌ Mật khẩu quản trị không chính xác!"}), 403


@app.route("/admin/system/terminal", methods=["POST"])
@limiter.limit("30/minute")
@owner_required
@stepup_required
def admin_system_terminal():
    """Chạy lệnh shell terminal trực tiếp trên máy chủ host (Termux / Linux / Windows)."""
    data = request.get_json(silent=True) or request.form or {}
    command = data.get("command", "").strip()

    if not command:
        return jsonify({"ok": False, "output": "⚠️ Lệnh không được để trống!", "returncode": 1}), 200

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    current_cwd = session.get("term_cwd")
    if not current_cwd or not os.path.isdir(current_cwd):
        current_cwd = base_dir

    # Handle directory navigation (cd command)
    if command == "cd" or command.startswith("cd ") or command.startswith("cd\t"):
        target = command[2:].strip()
        if not target or target in ("~", "/"):
            new_dir = base_dir
        else:
            new_dir = os.path.abspath(os.path.join(current_cwd, target))

        if os.path.isdir(new_dir):
            session["term_cwd"] = new_dir
            return jsonify({
                "ok": True,
                "command": command,
                "output": f"📂 Đã chuyển thư mục làm việc sang: {new_dir}",
                "cwd": new_dir,
                "returncode": 0
            }), 200
        else:
            return jsonify({
                "ok": False,
                "command": command,
                "output": f"bash: cd: {target}: No such file or directory",
                "cwd": current_cwd,
                "returncode": 1
            }), 200

    # Block interactive TTY programs that hang or crash non-interactive HTTP subprocesses
    interactive_cmds = ("nano", "vim", "vi", "top", "htop", "less", "more", "gdb")
    cmd_words = command.split()
    first_cmd = cmd_words[0].lower() if cmd_words else ""
    if first_cmd in interactive_cmds or command.strip() == "python":
        target_file = cmd_words[1] if len(cmd_words) > 1 else ".env"
        return jsonify({
            "ok": False,
            "command": command,
            "output": f"⚠️ '{first_cmd}' là trình chỉnh sửa / chương trình tương tác TTY nên không thể chạy trực tiếp trong Web Console.\n💡 Gợi ý: Dùng lệnh 'cat {target_file}' để xem nội dung file trên màn hình terminal!",
            "cwd": current_cwd,
            "returncode": 1
        }), 200

    # Special background handling for long-running / restart commands from Web Console
    cmd_clean = command.strip().lower()
    if cmd_clean in ("restart", "reset", "python main.py --restart", "python3 main.py --restart", f"{sys.executable} main.py --restart".lower()):
        main_py = os.path.join(base_dir, "main.py")
        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(f"sleep 1 && python main.py --restart > {os.path.join(base_dir, 'data', 'bot.log')} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🔄 Đã gửi lệnh khởi động lại hệ thống thành công! Bot và Dashboard đang khởi động lại...",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    if cmd_clean in ("start", "python main.py", "python3 main.py", "python main.py --start", "python3 main.py --start"):
        main_py = os.path.join(base_dir, "main.py")
        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--start"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(f"python main.py --start > {os.path.join(base_dir, 'data', 'bot.log')} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🚀 Đã khởi động hệ thống trong nền! Gõ 'python main.py --status' sau 3 giây để kiểm tra.",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    if cmd_clean in ("bot", "python main.py --bot", "python3 main.py --bot"):
        bot_log = os.path.join(base_dir, "data", "bot.log")
        watchdog_script = os.path.join(base_dir, "scripts", "watchdog.sh")
        if os.name == "nt":
            subprocess.Popen([sys.executable, os.path.join(base_dir, "main.py"), "--bot"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            if os.path.exists(watchdog_script):
                subprocess.Popen(f"nohup bash {watchdog_script} > {bot_log} 2>&1 &", shell=True, cwd=base_dir)
            else:
                subprocess.Popen(f"nohup python main.py --bot > {bot_log} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🤖 Đã khởi động Bot Discord trong nền! Gõ 'python main.py --status' sau 3 giây để kiểm tra.",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    # Shortcut aliases
    if command.lower() in ("status", "info"):
        command = f"{sys.executable} main.py --status"
    elif command.lower() in ("pull", "update"):
        command = "git pull"

    # Determine shell executable (Termux/Linux requires explicit bash/sh path)
    exec_shell = None
    if os.name != "nt":
        exec_shell = shutil.which("bash") or shutil.which("sh") or "/data/data/com.termux/files/usr/bin/bash" or "/bin/sh"

    try:
        res = subprocess.run(
            command,
            shell=True,
            executable=exec_shell,
            capture_output=True,
            text=True,
            cwd=current_cwd,
            timeout=30,
            encoding="utf-8",
            errors="replace"
        )
        output = (res.stdout or "").replace("\r\n", "\n")
        if res.stderr:
            output += ("\n" if output else "") + res.stderr.replace("\r\n", "\n")
        if not output.strip():
            output = "(Lệnh đã thực thi thành công, không có output trả về)"

        return jsonify({
            "ok": True,
            "command": command,
            "output": output,
            "cwd": current_cwd,
            "returncode": res.returncode
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False,
            "command": command,
            "output": "⏱️ Lệnh thực thi quá thời hạn cho phép (Timeout 30s)!",
            "cwd": current_cwd,
            "returncode": -1
        }), 200
    except Exception as e:
        err_msg = str(e)
        return jsonify({
            "ok": False,
            "command": command,
            "output": f"❌ Lỗi thực thi lệnh: {err_msg}",
            "cwd": current_cwd,
            "returncode": -1
        }), 200


@app.route("/admin/system/git-pull", methods=["POST"])
@limiter.limit("5/minute")
@owner_required
@stepup_required
def admin_system_git_pull():
    """Cập nhật code mới nhất từ Git (git pull)."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exec_shell = None if os.name == "nt" else (shutil.which("bash") or shutil.which("sh"))
        res = subprocess.run(
            "git fetch origin main && git reset --hard origin/main",
            shell=True,
            executable=exec_shell,
            capture_output=True,
            text=True,
            cwd=base_dir,
            timeout=30,
            encoding="utf-8",
            errors="replace"
        )
        output = (res.stdout or "").replace("\r\n", "\n")
        if res.stderr:
            output += ("\n" if output else "") + res.stderr.replace("\r\n", "\n")

        return jsonify({
            "ok": True,
            "output": output or "Git pull thành công!",
            "returncode": res.returncode
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "output": f"❌ Lỗi thực thi git pull: {e}", "returncode": -1}), 200


@app.route("/admin/system/restart", methods=["POST"])
@limiter.limit("10/minute")
@owner_required
@stepup_required
def admin_system_restart():
    """Khởi động lại toàn bộ hệ thống Bot & Dashboard."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_py = os.path.join(base_dir, "main.py")

        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, start_new_session=True)

        return jsonify({
            "ok": True,
            "message": "🔄 Đã gửi lệnh khởi động lại hệ thống! Bot và Dashboard đang khởi động lại..."
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "message": f"❌ Lỗi khởi động lại: {e}"}), 200


if __name__ == "__main__":
    db.init_db()
    dash_host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    dash_port = int(os.environ.get("DASHBOARD_PORT", "5000"))
    app.run(host=dash_host, port=dash_port, debug=True)


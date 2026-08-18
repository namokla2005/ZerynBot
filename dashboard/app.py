"""
app.py — Flask dashboard for Discord Bot v2.
"""
import sys, os, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 encoding on stdout/stderr for Flask (prevents cp1252 UnicodeEncodeError on Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify
from datetime import datetime, timezone
import json
import config
import database as db
import requests
from i18n import t, tr, i18n as i18n_manager
from dashboard.auth import (
    get_oauth2_url, exchange_code, get_user, get_manageable_guilds, get_avatar_url
)
from dashboard.api import api

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = config.FLASK_SECRET_KEY
app.register_blueprint(api)


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

def guild_access_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
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
def login():
    if "user" in session:
        return redirect(url_for("home"))
    return render_template("login.html", oauth_url=get_oauth2_url())

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Đăng nhập thất bại — không nhận được code.", "error")
        return redirect(url_for("login"))
    try:
        token_data   = exchange_code(code)
        access_token = token_data["access_token"]
        user         = get_user(access_token)
        guilds       = get_manageable_guilds(access_token)
        session["user"]         = user
        session["access_token"] = access_token
        session["guilds"]       = guilds
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
        channel_map_json=json.dumps(channel_map)
    )

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
            "welcome_channel_id":  form.get("welcome_channel_id") or None,
            "welcome_message":     form.get("welcome_message", ""),
            "welcome_use_embed":   1 if form.get("welcome_use_embed") else 0,
            "welcome_embed_color": form.get("welcome_embed_color", "#57F287"),
            "welcome_embed_title": form.get("welcome_embed_title", ""),
            "welcome_bg_url":      form.get("welcome_bg_url", ""),
            "goodbye_channel_id":  form.get("goodbye_channel_id") or None,
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
            "announce_channel_id": form.get("announce_channel_id", ""),
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
            "log_channel_id": form.get("log_channel_id") or None,
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
            "log_channel_id": form.get("log_channel_id") or None
        }
        db.upsert_automod_settings(guild_id, **fields)
        # Enable module if any feature is enabled
        is_module_active = (fields["spam_enabled"] or fields["bad_words_enabled"] or 
                            fields["links_enabled"] or fields["anti_invite_enabled"] or 
                            fields["anti_caps_enabled"] or fields["anti_mentions_enabled"])
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


@app.route("/dashboard/<guild_id>/embeds")
@guild_access_required
def server_embeds(guild_id: str):
    return render_template("embeds.html", **_server_ctx(
        guild_id, "embeds",
        embeds=db.get_saved_embeds(guild_id),
        channels=db.get_guild_channels(guild_id),
        now=datetime.now().strftime("%H:%M"),
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

    settings = db.get_guild_settings(guild_id)
    import json
    try:
        saved_admin_roles = json.loads(settings.get("bot_admin_roles", "[]"))
    except:
        saved_admin_roles = []
        
    roles = db.get_guild_roles(guild_id)

    return render_template(
        "modules.html", 
        **_server_ctx(guild_id, "modules"),
        saved_admin_roles=saved_admin_roles,
        roles=roles
    )


# ─── Commands data registry ────────────────────────────────────────────────────

_COMMANDS_DATA = [
    {
        "category": "Tổng quát",
        "icon": "⚙️",
        "commands": [
            {
                "name": "help", "emoji": "📖",
                "desc": "Xem danh sách tất cả lệnh của bot",
                "usage": "/help", "example": "/help",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📖 Danh sách lệnh",
                    "desc": "**Tổng quát:** /help, /ping, /membercount<br>"
                            "**Info:** /serverinfo, /userinfo, /avatar<br>"
                            "**Music:** /play, /search, /stop, /loop..."
                }
            },
            {
                "name": "ping", "emoji": "🏓",
                "desc": "Kiểm tra độ trễ (latency) của bot",
                "usage": "/ping", "example": "/ping",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🏓 Pong!",
                    "desc": "**Độ trễ:** `42ms`<br>**API Discord:** `38ms`"
                }
            },
            {
                "name": "membercount", "emoji": "👥",
                "desc": "Xem tổng số thành viên trong server",
                "usage": "/membercount", "example": "/membercount",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "👥 Thành viên server",
                    "desc": "**Tổng cộng:** `142`<br>**Đang online:** `38`<br>**Bot:** `4`"
                }
            },
            {
                "name": "poll", "emoji": "📊",
                "desc": "Tạo một cuộc bình chọn nhanh",
                "usage": "/poll [câu hỏi]", "example": "/poll Tối nay ăn gì?",
                "args": [{"name": "question", "type": "Text", "required": True, "desc": "Câu hỏi bình chọn"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📊 Bình chọn",
                    "desc": "**Tối nay ăn gì?**<br><br>Thả cảm xúc bên dưới để bình chọn!"
                }
            },
            {
                "name": "roll", "emoji": "🎲",
                "desc": "Tung xúc xắc (ngẫu nhiên từ 1 đến số chỉ định)",
                "usage": "/roll [số]", "example": "/roll 100",
                "args": [{"name": "max_number", "type": "Number", "required": False, "desc": "Số lớn nhất (mặc định: 100)"}],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "🎲 Tung xúc xắc",
                    "desc": "Bạn đã tung ra số: **42** (1 - 100)"
                }
            },
            {
                "name": "choose", "emoji": "🤔",
                "desc": "Bot sẽ chọn ngẫu nhiên giúp bạn một phương án",
                "usage": "/choose [các lựa chọn]", "example": "/choose Ăn cơm, Ăn phở",
                "args": [{"name": "options", "type": "Text", "required": True, "desc": "Các phương án (cách nhau bởi dấu phẩy)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🤔 Lựa chọn ngẫu nhiên",
                    "desc": "Giữa các phương án: `Ăn cơm, Ăn phở`<br><br>🎯 Mình chọn: **Ăn phở**"
                }
            }
        ]
    },
    {
        "category": "Reaction Roles",
        "icon": "✨",
        "commands": [
            {
                "name": "reactionroles", "emoji": "✨",
                "desc": "Tính năng này không có lệnh Slash. Vui lòng sử dụng Web Dashboard để thiết lập Panel và Emoji.",
                "usage": "(Dashboard)", "example": "Dashboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "✨ Reaction Roles",
                    "desc": "Tính năng Reaction Roles hoàn toàn được quản lý tự động thông qua Dashboard của bot."
                }
            }
        ]
    },
    {
        "category": "Auto Roles",
        "icon": "🪪",
        "commands": [
            {
                "name": "autorole show", "emoji": "🪪",
                "desc": "Xem cấu hình Auto Roles hiện tại",
                "usage": "/autorole show", "example": "/autorole show",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "⚙️ Cấu hình Auto Roles",
                    "desc": "**Trạng thái:** ✅ Đã bật<br>**Roles cho Thành viên:** @Member<br>**Roles cho Bot:** @Bot"
                }
            }
        ]
    },
    {
        "category": "Automods",
        "icon": "🛡️",
        "commands": [
            {
                "name": "automods show", "emoji": "🛡️",
                "desc": "Xem cấu hình Automods hiện tại",
                "usage": "/automods show", "example": "/automods show",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🛡️ Automods — My Server",
                    "desc": "**Trạng thái:** 🟢 Đang Hoạt Động<br>*(Để tuỳ chỉnh chi tiết, vui lòng dùng Dashboard)*"
                }
            }
        ]
    },
    {
        "category": "Leveling",
        "icon": "🌟",
        "commands": [
            {
                "name": "rank", "emoji": "🌟",
                "desc": "Xem cấp độ và hạng của bạn hoặc người khác",
                "usage": "/rank [người_dùng]", "example": "/rank @Nam",
                "args": [{"name": "member", "type": "Mention", "required": False, "desc": "Người dùng cần xem (mặc định: bạn)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "Cấp độ của Nam",
                    "desc": "**Rank:** #1 | **Level:** 5\n**XP:** 450 / 550\n`[██████████░░░░░░░░░░]` 80%"
                }
            },
            {
                "name": "leaderboard", "emoji": "🏆",
                "desc": "Xem bảng xếp hạng cấp độ của server",
                "usage": "/leaderboard", "example": "/leaderboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🏆 Bảng xếp hạng",
                    "desc": "🥇 **#1** | @Nam • **Lvl 5** (450 XP)\n🥈 **#2** | @User • **Lvl 3** (200 XP)"
                }
            },
            {
                "name": "xp set", "emoji": "⚙️",
                "desc": "Thiết lập điểm kinh nghiệm cho một thành viên",
                "usage": "/xp set [người_dùng] [xp]", "example": "/xp set @Nam 1000",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Người dùng"},
                    {"name": "amount", "type": "Number", "required": True, "desc": "Số điểm XP mới"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đã đặt XP của @Nam thành **1000** (Cấp độ: **10**)."
                }
            },
            {
                "name": "xp reset", "emoji": "🗑️",
                "desc": "Xóa toàn bộ điểm kinh nghiệm của một thành viên",
                "usage": "/xp reset [người_dùng]", "example": "/xp reset @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Người dùng"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đã xóa toàn bộ XP của @Nam."
                }
            }
        ]
    },
    {
        "category": "Giveaways",
        "icon": "🎁",
        "commands": [
            {
                "name": "giveaway start", "emoji": "🎉",
                "desc": "Tạo một Giveaway mới",
                "usage": "/giveaway start [thời_gian] [người_thắng] [giải_thưởng]", "example": "/giveaway start 1h 2 Nitro Classic",
                "args": [
                    {"name": "duration", "type": "String", "required": True, "desc": "Thời gian (vd: 1m, 1h, 1d)"},
                    {"name": "winners", "type": "Number", "required": True, "desc": "Số người thắng"},
                    {"name": "prize", "type": "String", "required": True, "desc": "Phần thưởng"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎉 GIVEAWAY: Nitro Classic",
                    "desc": "Bấm vào nút **🎉 Tham gia** bên dưới để nhận cơ hội trúng giải nhé!\n\n**🎁 Phần thưởng:** Nitro Classic\n**🏆 Số người thắng:** 2\n**👥 Số người tham gia:** 15 người\n**⏰ Kết thúc:** trong 1 giờ"
                }
            },
            {
                "name": "giveaway reroll", "emoji": "🎲",
                "desc": "Chọn lại người thắng mới",
                "usage": "/giveaway reroll [message_id]", "example": "/giveaway reroll 1234567890",
                "args": [
                    {"name": "message_id", "type": "String", "required": True, "desc": "ID của tin nhắn Giveaway"}
                ],
                "preview": {
                    "type": "text", "content": "🎉 **REROLL**: Chúc mừng @Nam đã trúng giải **Nitro Classic**!"
                }
            },
            {
                "name": "giveaway end", "emoji": "🛑",
                "desc": "Kết thúc sớm một Giveaway",
                "usage": "/giveaway end [message_id]", "example": "/giveaway end 1234567890",
                "args": [
                    {"name": "message_id", "type": "String", "required": True, "desc": "ID của tin nhắn Giveaway"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đang tiến hành quay số và kết thúc Giveaway..."
                }
            }
        ]
    },
    {
        "category": "Tickets",
        "icon": "🎫",
        "commands": [
            {
                "name": "tickets", "emoji": "🎫",
                "desc": "Tính năng này không có lệnh Slash. Vui lòng sử dụng Web Dashboard để tạo Panel hỗ trợ.",
                "usage": "(Dashboard)", "example": "Dashboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎫 Ticket System",
                    "desc": "Hệ thống Ticket được quản lý tự động thông qua Dashboard của bot."
                }
            }
        ]
    },
    {
        "category": "Thông tin",
        "icon": "ℹ️",
        "commands": [
            {
                "name": "serverinfo", "emoji": "🏠",
                "desc": "Hiển thị thông tin chi tiết về server",
                "usage": "/serverinfo", "example": "/serverinfo",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🏠 Server Info",
                    "desc": "Thông tin về server hiện tại",
                    "fields": [
                        {"name": "📋 Tên", "value": "My Server"},
                        {"name": "👑 Chủ sở hữu", "value": "@Admin"},
                        {"name": "👥 Thành viên", "value": "142"},
                        {"name": "📅 Ngày tạo", "value": "01/01/2023"},
                    ]
                }
            },
            {
                "name": "userinfo", "emoji": "👤",
                "desc": "Xem thông tin của một thành viên",
                "usage": "/userinfo [@member]", "example": "/userinfo @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": False,
                     "desc": "Thành viên cần xem (mặc định: bạn)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "👤 User Info",
                    "desc": "Thông tin chi tiết của thành viên",
                    "fields": [
                        {"name": "🏷️ Username", "value": "Nam#0001"},
                        {"name": "📅 Tham gia", "value": "15/06/2023"},
                        {"name": "🎭 Roles", "value": "@Admin, @Member"},
                        {"name": "🆔 ID", "value": "123456789"},
                    ]
                }
            },
            {
                "name": "avatar", "emoji": "🖼️",
                "desc": "Xem avatar của một thành viên với đường link tải về",
                "usage": "/avatar [@member]", "example": "/avatar @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": False,
                     "desc": "Thành viên cần xem avatar (mặc định: bạn)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🖼️ Avatar của Nam",
                    "desc": "[PNG](https://...) | [JPG](https://...) | [WebP](https://...)",
                    "image": "https://cdn.discordapp.com/embed/avatars/0.png"
                }
            },
            {
                "name": "botinfo", "emoji": "🤖",
                "desc": "Hiển thị thông số kỹ thuật và trạng thái của bot",
                "usage": "/botinfo", "example": "/botinfo",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🤖 Thông tin Bot",
                    "desc": "**⚙️ CPU:** `2.5%` | **🗄️ RAM:** `45.2 MB`<br>**🐍 Python:** `3.10.0` | **🏰 Servers:** `5`"
                }
            },
            {
                "name": "roleinfo", "emoji": "🎭",
                "desc": "Hiển thị thông tin về một Role",
                "usage": "/roleinfo [@role]", "example": "/roleinfo @Admin",
                "args": [{"name": "role", "type": "Mention", "required": True, "desc": "Role cần xem thông tin"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎭 Thông tin Role: Admin",
                    "desc": "**🪪 ID:** `123456789`<br>**👥 Số người có:** `5`<br>**📌 Có thể tag:** ✅"
                }
            },
            {
                "name": "channelinfo", "emoji": "📺",
                "desc": "Hiển thị thông tin về một Kênh",
                "usage": "/channelinfo [#channel]", "example": "/channelinfo #general",
                "args": [{"name": "channel", "type": "Mention", "required": False, "desc": "Kênh cần xem thông tin (mặc định: kênh hiện tại)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📺 Thông tin Kênh: general",
                    "desc": "**🪪 ID:** `987654321`<br>**📂 Thể loại:** `text`<br>**🔞 NSFW:** ❌"
                }
            }
        ]
    },
    {
        "category": "Music 🎵",
        "icon": "🎵",
        "commands": [
            {
                "name": "play", "emoji": "▶️",
                "desc": "Phát nhạc từ YouTube. Nhập tên bài hoặc link trực tiếp",
                "usage": "/play [tên bài hoặc link]",
                "example": "/play Đen - Bố Già  |  /play https://youtu.be/...",
                "args": [
                    {"name": "query", "type": "Text", "required": True,
                     "desc": "Tên bài hát để tìm kiếm, hoặc link YouTube"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🎵 Đang phát",
                    "desc": "[Đen - Bố Già](https://youtu.be/...)",
                    "fields": [
                        {"name": "⏱ Thời lượng", "value": "4:32"},
                        {"name": "📺 Kênh", "value": "Đen Vâu"},
                    ]
                }
            },
            {
                "name": "search", "emoji": "🔍",
                "desc": "Tìm kiếm nhạc và hiển thị 5 kết quả để chọn",
                "usage": "/search [tên bài]", "example": "/search Sơn Tùng MTP",
                "args": [
                    {"name": "query", "type": "Text", "required": True,
                     "desc": "Tên bài hát cần tìm kiếm"}
                ],
                "preview": {
                    "type": "select",
                    "desc": "1️⃣ **Hãy Trao Cho Anh** — `4:12`<br>"
                            "2️⃣ **Muộn Rồi Mà Sao Còn** — `4:01`<br>"
                            "3️⃣ **Chạy Ngay Đi** — `3:48`",
                    "options": [
                        "Hãy Trao Cho Anh — 4:12 | Sơn Tùng MTP",
                        "Muộn Rồi Mà Sao Còn — 4:01 | Sơn Tùng MTP",
                        "Chạy Ngay Đi — 3:48 | Sơn Tùng MTP",
                        "Không Phải Dạng Vừa Đâu — 3:55 | Sơn Tùng MTP",
                        "Nơi Này Có Anh — 4:20 | Sơn Tùng MTP",
                    ]
                }
            },
            {
                "name": "stop", "emoji": "⏹️",
                "desc": "Dừng nhạc và xóa toàn bộ hàng chờ",
                "usage": "/stop", "example": "/stop", "args": [],
                "preview": {
                    "type": "text",
                    "text": "⏹️ Đã dừng nhạc và xóa hàng chờ!"
                }
            },
            {
                "name": "resume", "emoji": "▶️",
                "desc": "Tiếp tục phát nhạc đang bị tạm dừng",
                "usage": "/resume", "example": "/resume", "args": [],
                "preview": {"type": "text", "text": "▶️ Đã tiếp tục phát!"}
            },
            {
                "name": "loop", "emoji": "🔂",
                "desc": "Bật/tắt chế độ lặp lại bài hiện tại",
                "usage": "/loop", "example": "/loop", "args": [],
                "preview": {"type": "text", "text": "🔂 Đã **bật** chế độ lặp lại!"}
            },
            {
                "name": "autoplay", "emoji": "♾️",
                "desc": "Bật/tắt tự động phát bài tiếp theo khi hết queue",
                "usage": "/autoplay", "example": "/autoplay", "args": [],
                "preview": {"type": "text", "text": "♾️ Đã **bật** Autoplay!"}
            },
            {
                "name": "replay", "emoji": "🔁",
                "desc": "Phát lại bài hát hiện tại từ đầu",
                "usage": "/replay", "example": "/replay", "args": [],
                "preview": {"type": "text", "text": "🔁 Đang phát lại bài hiện tại..."}
            },
            {
                "name": "lofi", "emoji": "📻",
                "desc": "Phát stream Lofi Girl 24/7 — nhạc lo-fi không có quảng cáo",
                "usage": "/lofi", "example": "/lofi", "args": [],
                "preview": {"type": "text", "text": "📻 **Lofi Girl 24/7** đang bật... ☕🌙"}
            },
            {
                "name": "join", "emoji": "🔊",
                "desc": "Bot vào kênh voice đang ngồi của bạn",
                "usage": "/join", "example": "/join", "args": [],
                "preview": {"type": "text", "text": "✅ Đã vào **🎶 music**!"}
            },
            {
                "name": "leave", "emoji": "🚪",
                "desc": "Bot rời kênh voice và xóa hàng chờ",
                "usage": "/leave", "example": "/leave", "args": [],
                "preview": {"type": "text", "text": "👋 Đã rời kênh voice!"}
            },
            {
                "name": "playlist", "emoji": "📂",
                "desc": "Quản lý và phát danh sách nhạc (playlist)",
                "usage": "/playlist [name/add/play/show/remove/removesong]", "example": "/playlist play Nhạc Trẻ",
                "args": [
                    {"name": "action", "type": "Text", "required": True,
                     "desc": "Hành động (name, add, play, show, remove, removesong)"},
                    {"name": "playlist_name", "type": "Text", "required": True,
                     "desc": "Tên playlist"},
                    {"name": "query", "type": "Text", "required": False,
                     "desc": "Link nhạc hoặc tên bài hát (dành cho add)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📂 Playlist: Nhạc Trẻ",
                    "desc": "1. **Bài hát A** — `3:45`<br>2. **Bài hát B** — `4:02`<br>... và 10 bài hát khác."
                }
            },
        ]
    },
    {
        "category": "Kinh tế & Shop",
        "icon": "🪙",
        "commands": [
            {
                "name": "daily", "emoji": "📅",
                "desc": "Điểm danh hàng ngày nhận tiền thưởng và chuỗi streak",
                "usage": "/daily", "example": "/daily", "args": [],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "📅 Điểm Danh Hàng Ngày",
                    "desc": "🎉 Bạn đã nhận được **+100** 🪙!<br>🔥 Chuỗi điểm danh: **3 ngày liên tiếp**"
                }
            },
            {
                "name": "balance", "emoji": "💰",
                "desc": "Xem số dư ví tiền mặt, ngân hàng và tổng tài sản",
                "usage": "/balance [@member]", "example": "/balance @Nam",
                "args": [{"name": "member", "type": "Mention", "required": False, "desc": "Thành viên cần xem số dư"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "Ví Tiền & Tài Sản — Nam",
                    "desc": "💵 **Ví:** `500 🪙`<br>🏦 **Ngân hàng:** `2,500 🪙`<br>💎 **Tổng tài sản:** `3,000 🪙`"
                }
            },
            {
                "name": "pay", "emoji": "💸",
                "desc": "Chuyển tiền mặt cho thành viên khác trong server",
                "usage": "/pay <@member> <amount>", "example": "/pay @Nam 200",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Thành viên nhận tiền"},
                    {"name": "amount", "type": "Number", "required": True, "desc": "Số tiền cần chuyển"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "💸 Chuyển Tiền Thành Công",
                    "desc": "✅ Bạn đã chuyển thành công **200 🪙** cho @Nam!"
                }
            },
            {
                "name": "rich", "emoji": "🏆",
                "desc": "Bảng xếp hạng đại gia tiền tệ trong server",
                "usage": "/rich", "example": "/rich", "args": [],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "🏆 Bảng Xếp Hạng Đại Gia",
                    "desc": "🥇 **Nam** — `15,400 🪙`<br>🥈 **Alex** — `9,850 🪙`<br>🥉 **Cú** — `5,200 🪙`"
                }
            },
            {
                "name": "coinflip", "emoji": "🪙",
                "desc": "Cược tiền trò chơi tung đồng xu (Ngửa / Sấp)",
                "usage": "/coinflip <heads/tails> <bet>", "example": "/coinflip heads 50",
                "args": [
                    {"name": "choice", "type": "Choice", "required": True, "desc": "Chọn Mặt Ngửa (heads) hoặc Mặt Sấp (tails)"},
                    {"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🪙 Thắng Cược Tung Đồng Xu!",
                    "desc": "Đồng xu rơi vào mặt **Ngửa**!<br>🎉 Bạn nhận được **+100 🪙**!"
                }
            },
            {
                "name": "slots", "emoji": "🎰",
                "desc": "Quay hũ Slot Machine may mắn với nhiều mức nhân thưởng",
                "usage": "/slots <bet>", "example": "/slots 50",
                "args": [{"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🎰 Thắng Lớn Slot Machine!",
                    "desc": "[ 💎 | 💎 | 💎 ]<br>🎉 Bạn trúng x5 và nhận được **+250 🪙**!"
                }
            },
            {
                "name": "blackjack", "emoji": "🃏",
                "desc": "Đánh bài Xì Dách 21 điểm với Nhà Cái tương tác bằng nút bấm",
                "usage": "/blackjack <bet>", "example": "/blackjack 100",
                "args": [{"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🃏 Đánh Bài Xì Dách (Blackjack)",
                    "desc": "**Bài của bạn:** 🂡 🂪 (21 điểm)<br>**Nhà cái:** 🂱 🂸 (19 điểm)<br>🎉 **BẠN THẮNG!** Nhận được **+200 🪙**!"
                }
            },
            {
                "name": "shop", "emoji": "🛒",
                "desc": "Xem danh sách các Role đang được bán trong shop server",
                "usage": "/shop", "example": "/shop", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🛒 Cửa Hàng Server",
                    "desc": "• **`#1` VIP Member** — `500 🪙` (Còn 10)<br>• **`#2` Pro Gamer** — `1,000 🪙` (Vô hạn)<br><br>Dùng `/buy <ID>` để mua."
                }
            },
            {
                "name": "buy", "emoji": "🛍️",
                "desc": "Mua Role trong shop server bằng tiền ảo",
                "usage": "/buy <item_id>", "example": "/buy 1",
                "args": [{"name": "item_id", "type": "Number", "required": True, "desc": "ID vật phẩm trong shop"}],
                "preview": {
                    "type": "text", "text": "🎉 Bạn đã mua thành công **VIP Member**!"
                }
            }
        ]
    },
    {
        "category": "Voice Tạm thời",
        "icon": "🎙️",
        "commands": [
            {
                "name": "voice lock", "emoji": "🔒",
                "desc": "Khóa phòng voice cá nhân (chỉ người được mời mới vào được)",
                "usage": "/voice lock", "example": "/voice lock", "args": [],
                "preview": {"type": "text", "text": "🔒 Đã KHÓA phòng voice riêng của bạn!"}
            },
            {
                "name": "voice unlock", "emoji": "🔓",
                "desc": "Mở khóa phòng voice cá nhân cho mọi người cùng vào",
                "usage": "/voice unlock", "example": "/voice unlock", "args": [],
                "preview": {"type": "text", "text": "🔓 Đã MỞ KHÓA phòng voice cho tất cả thành viên!"}
            },
            {
                "name": "voice limit", "emoji": "👥",
                "desc": "Đặt giới hạn số lượng người tối đa trong phòng voice",
                "usage": "/voice limit <number>", "example": "/voice limit 5",
                "args": [{"name": "limit", "type": "Number", "required": True, "desc": "Số người tối đa (0 = vô hạn)"}],
                "preview": {"type": "text", "text": "✅ Đã đặt giới hạn phòng thành **5 người**!"}
            },
            {
                "name": "voice rename", "emoji": "✏️",
                "desc": "Đổi tên phòng voice cá nhân của bạn",
                "usage": "/voice rename <name>", "example": "/voice rename Phòng Chơi Game",
                "args": [{"name": "name", "type": "Text", "required": True, "desc": "Tên phòng mới"}],
                "preview": {"type": "text", "text": "✅ Đã đổi tên phòng voice thành: **Phòng Chơi Game**!"}
            }
        ]
    },
    {
        "category": "Lệnh Tùy biến",
        "icon": "⚡",
        "commands": [
            {
                "name": "customcmd list", "emoji": "📋",
                "desc": "Xem danh sách các lệnh tùy biến và auto-responders trong server",
                "usage": "/customcmd list", "example": "/customcmd list", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "⚡ Danh Sách Lệnh Tùy Biến",
                    "desc": "• **`!ip`** `[exact]` — 45 lần sử dụng<br>• **`!rules`** `[exact]` — 120 lần sử dụng"
                }
            },
            {
                "name": "customcmd add", "emoji": "➕",
                "desc": "Thêm một lệnh phản hồi tự động nhanh bằng văn bản",
                "usage": "/customcmd add <trigger> <response>", "example": "/customcmd add !ip IP server là play.example.com",
                "args": [
                    {"name": "trigger", "type": "Text", "required": True, "desc": "Từ khóa kích hoạt (VD: !ip)"},
                    {"name": "response", "type": "Text", "required": True, "desc": "Nội dung phản hồi (hỗ trợ {user}, {server})"}
                ],
                "preview": {"type": "text", "text": "✅ Đã tạo lệnh tùy biến mới: **`!ip`**!"}
            },
            {
                "name": "customcmd delete", "emoji": "🗑️",
                "desc": "Xóa một lệnh tùy biến trong server",
                "usage": "/customcmd delete <trigger>", "example": "/customcmd delete !ip",
                "args": [{"name": "trigger", "type": "Text", "required": True, "desc": "Từ khóa của lệnh cần xóa"}],
                "preview": {"type": "text", "text": "🗑️ Đã xóa lệnh tùy biến: **`!ip`**!"}
            }
        ]
    },
    {
        "category": "Trợ lý AI",
        "icon": "🤖",
        "commands": [
            {
                "name": "ask", "emoji": "💡",
                "desc": "Đặt câu hỏi thông minh cho trợ lý AI Google Gemini 2.0",
                "usage": "/ask <prompt>", "example": "/ask Giải thích cách hoạt động của hố đen",
                "args": [{"name": "prompt", "type": "Text", "required": True, "desc": "Câu hỏi cần giải đáp"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🤖 Trợ Lý AI Zeryn",
                    "desc": "Hố đen là một vùng không gian có trường hấp dẫn mạnh đến mức không vật chất hay bức xạ nào có thể thoát ra..."
                }
            },
            {
                "name": "summarize", "emoji": "📋",
                "desc": "Đọc và tóm tắt ngắn gọn các tin nhắn gần nhất trong kênh chat",
                "usage": "/summarize [limit]", "example": "/summarize 30",
                "args": [{"name": "limit", "type": "Number", "required": False, "desc": "Số lượng tin nhắn cần tóm tắt (10-50)"}],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "📋 Tóm Tắt Cuộc Trò Chuyện",
                    "desc": "• **Chủ đề chính:** Mọi người đang bàn về kế hoạch chơi game cuối tuần.<br>• **Quyết định:** Thống nhất chơi Valorant lúc 20h tối thứ 7."
                }
            }
        ]
    }
]

@app.route("/dashboard/<guild_id>/commands")
@guild_access_required
def server_commands(guild_id: str):
    ui_lang = session.get("ui_lang", "vi")
    cat_map = {
        "Tổng quan": t("commands.cat_overview", lang=ui_lang),
        "Tổng quát": t("commands.cat_overview", lang=ui_lang),
        "Thông tin": t("commands.cat_info", lang=ui_lang),
        "Music 🎵": t("commands.cat_music", lang=ui_lang),
        "Kinh tế & Shop": t("nav.economy", lang=ui_lang),
        "Voice Tạm thời": t("nav.tempvoice", lang=ui_lang),
        "Lệnh Tùy biến": t("nav.customcommands", lang=ui_lang),
        "Trợ lý AI": t("nav.ai", lang=ui_lang),
    }
    localized_data = []
    for c in _COMMANDS_DATA:
        c_copy = dict(c)
        c_copy["category"] = cat_map.get(c["category"], c["category"])
        cmd_list = []
        for cmd in c["commands"]:
            cmd_copy = dict(cmd)
            desc_key = f"cmd.{cmd['name'].replace(' ', '_')}.desc"
            trans_desc = t(desc_key, lang=ui_lang)
            if trans_desc != desc_key:
                cmd_copy["desc"] = trans_desc
            cmd_list.append(cmd_copy)
        c_copy["commands"] = cmd_list
        localized_data.append(c_copy)

    total = sum(len(c["commands"]) for c in _COMMANDS_DATA)
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
    
    video_id = None
    webpage_url = None
    
    try:
        if query.startswith(("http://", "https://")):
            webpage_url = query
            match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", webpage_url)
            if match:
                video_id = match.group(1)
        else:
            resp = requests.get(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}", timeout=5)
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


@app.route("/dashboard/<guild_id>/music/playlist/<int:playlist_id>/delete", methods=["POST", "GET"])
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


@app.route("/dashboard/<guild_id>/music/playlist/track/<int:track_id>/delete", methods=["POST", "GET"])
@guild_access_required
def delete_track_route(guild_id: str, track_id: int):
    # Just delete it
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


@app.route("/dashboard/<guild_id>/economy/delete_item/<int:item_id>", methods=["POST", "GET"])
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
        hub_channel_id = request.form.get("hub_channel_id", "").strip()
        category_id = request.form.get("category_id", "").strip()
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


@app.route("/dashboard/<guild_id>/tempvoice/delete_channel/<channel_id>", methods=["POST", "GET"])
@guild_access_required
def server_tempvoice_delete_channel(guild_id: str, channel_id: str):
    import database as db_mod
    with sqlite3.connect(db_mod.DB_PATH) as conn:
        conn.execute("DELETE FROM tempvoice_active WHERE channel_id = ?", (channel_id,))
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


@app.route("/dashboard/<guild_id>/customcommands/delete/<int:cmd_id>", methods=["POST", "GET"])
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
        ai_channel_id = request.form.get("ai_channel_id", "").strip()
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


@app.route("/admin")
@owner_required
def admin_panel():
    guilds    = _get_all_bot_guilds_detailed()
    blacklist = db.get_blacklist()
    blacklist_ids = {b["guild_id"] for b in blacklist}
    global_ai_key = db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
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
    )


@app.route("/admin/ai_key", methods=["POST"])
@owner_required
def admin_save_ai_key():
    key = request.form.get("global_ai_key", "").strip()
    db.set_global_setting("gemini_api_key", key)
    flash("✅ Đã lưu cấu hình AI API Key toàn cục thành công!", "success")
    return redirect(url_for("admin_panel") + "#ai_settings")


@app.route("/api/admin/test_ai_key", methods=["POST"])
@owner_required
def api_admin_test_ai_key():
    import urllib.request, time
    data = request.get_json(silent=True) or {}
    key = data.get("api_key") or db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
    key = key.strip()
    if not key:
        return jsonify({"ok": False, "status": "no_key", "message": "Chưa có API Key (Đang dùng Smart Local Responder)"})

    # 1. Groq Cloud (Key starts with gsk_)
    if key.startswith("gsk_"):
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        groq_payload = json.dumps({
            "model": "openai/gpt-oss-120b",
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
                        "model": "Groq Cloud (GPT-OSS 120B / Llama 3.3)",
                        "latency_ms": latency,
                        "message": f"Kết nối Groq Cloud siêu tốc thành công ({latency}ms)"
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

@app.route("/admin/system/terminal", methods=["POST"])
@owner_required
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
@owner_required
def admin_system_git_pull():
    """Cập nhật code mới nhất từ Git (git pull)."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exec_shell = None if os.name == "nt" else (shutil.which("bash") or shutil.which("sh"))
        res = subprocess.run(
            "git pull",
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
@owner_required
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
    app.run(host="0.0.0.0", port=5000, debug=True)

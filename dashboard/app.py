"""
app.py — Flask dashboard for Discord Bot v2.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, redirect, url_for, session, request, flash
from datetime import datetime
import config
import database as db
from dashboard.auth import (
    get_oauth2_url, exchange_code, get_user, get_manageable_guilds, get_avatar_url
)
from dashboard.api import api

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = config.FLASK_SECRET_KEY
app.register_blueprint(api)

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
    if "user" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))

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
    return render_template("server.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guild_id=guild_id,
        guild=guild_info,
        meta=meta,
        modules=modules,
        active_page="overview",
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
            "announce_channel_id": form.get("announce_channel_id") or None,
            "announce_message": form.get("announce_message", "🎉 Chúc mừng {user} đã đạt cấp **{level}**!")
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
        is_module_active = fields["spam_enabled"] or fields["bad_words_enabled"] or fields["links_enabled"]
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
            },
            {
                "name": "autorole toggle", "emoji": "🔄",
                "desc": "Bật/Tắt tính năng Auto Roles",
                "usage": "/autorole toggle", "example": "/autorole toggle",
                "args": [],
                "preview": {
                    "type": "text",
                    "content": "✅ Đã **Bật** tính năng Auto Roles."
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
            },
            {
                "name": "automods toggle", "emoji": "🔄",
                "desc": "Bật/Tắt hệ thống Automods",
                "usage": "/automods toggle", "example": "/automods toggle",
                "args": [],
                "preview": {
                    "type": "text",
                    "content": "✅ Đã **BẬT** hệ thống Automods cho server này!"
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
]

@app.route("/dashboard/<guild_id>/commands")
@guild_access_required
def server_commands(guild_id: str):
    total = sum(len(c["commands"]) for c in _COMMANDS_DATA)
    return render_template("commands.html", **_server_ctx(
        guild_id, "commands",
        commands_data=_COMMANDS_DATA,
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
    panels = db.get_ticket_panels(guild_id)
    text_channels = db.get_guild_channels(guild_id) or []
    categories = db.get_guild_categories(guild_id) or []
    
    # Fetch roles dynamically using bot token
    import requests as _req
    roles = []
    try:
        resp = _req.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/roles",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=5
        )
        if resp.status_code == 200:
            roles = [r for r in resp.json() if r["name"] != "@everyone"]
    except Exception as e:
        print(f"Error fetching roles: {e}")

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
    import requests as _req
    roles = []
    try:
        resp = _req.get(
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
    import requests
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
    import requests as _req
    try:
        resp = _req.get(
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
    return render_template(
        "admin.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guilds=guilds,
        blacklist=blacklist,
        blacklist_ids=blacklist_ids,
        total_servers=len(guilds),
        total_blacklist=len(blacklist),
    )


@app.route("/admin/kick/<guild_id>", methods=["POST"])
@owner_required
def admin_kick_guild(guild_id: str):
    """Buộc bot rời khỏi server và thêm vào blacklist."""
    import requests as _req
    reason = request.form.get("reason", "Bị kick bởi Owner").strip() or "Bị kick bởi Owner"

    # Lấy tên server trước khi kick
    guild_name = request.form.get("guild_name", "Unknown")

    # Gọi Discord API để bot rời server
    try:
        resp = _req.delete(
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


@app.route("/admin/broadcast", methods=["POST"])
@owner_required
def admin_broadcast():
    """Gửi thông báo broadcast đến các server đã chọn."""
    import requests as _req

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
            gr = _req.get(
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
                cr = _req.get(
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
            mr = _req.post(
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


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

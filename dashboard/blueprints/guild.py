"""
guild.py — Route quản lý server: tổng quan + toàn bộ module cấu hình.
"""

import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import json
import sqlite3
import time
from datetime import datetime, timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import config
import database as db
from i18n import tr
from dashboard.auth import channel_belongs_to_guild, get_guild_roles
from dashboard.extensions import limiter, logger
from dashboard.web_helpers import (
    _get_guild_from_session,
    _safe_channel,
    _server_ctx,
    guild_access_required,
    login_required,
)

bp = Blueprint("guild", __name__)


@bp.route("/dashboard")
@login_required
def home():
    now = time.time()
    fetched_at = session.get("guilds_fetched_at", 0) or 0
    guilds = session.get("guilds") or []
    # Tối ưu: Nếu session đã có danh sách server và chưa quá 120s, phản hồi tức thì (<20ms).
    # Chỉ gọi Discord REST API khi session trống, quá 120s, hoặc có tham số ?refresh=1.
    if not guilds or (now - fetched_at > 120) or request.args.get("refresh"):
        try:
            from dashboard.auth import get_manageable_guilds
            fresh_guilds = get_manageable_guilds(session["access_token"])
            if fresh_guilds:
                guilds = fresh_guilds
                session["guilds"] = guilds
                session["guilds_fetched_at"] = now
                session.modified = True
        except Exception as e:
            logger.warning("Lỗi làm mới danh sách guild khi tải trang: %s", e)

    bot_guilds = [g for g in guilds if g.get("bot_in_guild")]
    no_bot_guilds = [g for g in guilds if not g.get("bot_in_guild")]

    return render_template("home.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guilds=guilds,
        bot_guilds=bot_guilds,
        no_bot_guilds=no_bot_guilds,
        bot_client_id=str(config.CLIENT_ID),
        owner_id=str(config.BOT_OWNER_ID),
    )

@bp.route("/dashboard/<guild_id>")
@guild_access_required
def server_overview(guild_id: str):
    if not str(guild_id).isdigit():
        flash("Server ID không hợp lệ.", "error")
        return redirect(url_for("guild.home"))
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
        raw_stats=raw_stats,
        channel_map=channel_map,
        recent_events=recent_events,
    )

@bp.route("/api/guild/<guild_id>/recent_events")
@guild_access_required
def api_guild_recent_events(guild_id: str):
    """API lấy tối đa 15 Recent Events gần nhất của server (định dạng JSON)."""
    events = db.get_recent_guild_events(guild_id, limit=15)
    return jsonify({"ok": True, "events": events})

@bp.route("/dashboard/<guild_id>/welcome", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_welcome", guild_id=guild_id))

    return render_template("welcome.html", **_server_ctx(
        guild_id, "welcome",
        settings=db.get_guild_settings(guild_id),
        channels=db.get_guild_channels(guild_id),
        meta=db.get_guild_meta(guild_id) or {},
    ))

@bp.route("/dashboard/<guild_id>/autoroles", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_autoroles", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/leveling", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_leveling", guild_id=guild_id))
        
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

@bp.route("/dashboard/<guild_id>/logger", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_logger", guild_id=guild_id))

    settings = db.get_logger_settings(guild_id)
    channels = db.get_guild_channels(guild_id)
    return render_template(
        "server_logger.html",
        **_server_ctx(guild_id, active_page="logger"),
        settings=settings,
        channels=channels,
        meta=db.get_guild_meta(guild_id) or {}
    )

@bp.route("/dashboard/<guild_id>/automod", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_automod", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/verify", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_verify", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/moderation", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_moderation", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/birthday", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_birthday", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/embeds")
@guild_access_required
def server_embeds(guild_id: str):
    return render_template("embeds.html", **_server_ctx(
        guild_id, "embeds",
        embeds=db.get_saved_embeds(guild_id),
        channels=db.get_guild_channels(guild_id),
        now=datetime.now(timezone.utc).strftime("%H:%M"),
    ))

@bp.route("/dashboard/<guild_id>/modules", methods=["GET", "POST"])
@guild_access_required
def server_modules(guild_id: str):
    if request.method == "POST":
        # Save bot admin roles
        bot_admin_roles = request.form.getlist("bot_admin_roles")
        import json
        db.upsert_guild(guild_id, bot_admin_roles=json.dumps(bot_admin_roles))
        
        flash("✅ Đã cập nhật Modules & Quyền quản trị!", "success")
        return redirect(url_for("guild.server_modules", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/commands")
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

@bp.route("/dashboard/<guild_id>/tickets")
@guild_access_required
def server_tickets(guild_id: str):
    panels = db.get_ticket_panels(guild_id) or []
    text_channels = db.get_guild_channels(guild_id) or []
    categories = db.get_guild_categories(guild_id) or []
    
    # Roles: cache 5 phút (REST → fallback bảng guild_roles). Trước đây mỗi lần
    # mở trang là 1 request REST 5s giữ 1 trong 4 thread của waitress.
    roles = get_guild_roles(guild_id)

    return render_template("tickets.html", **_server_ctx(
        guild_id, "tickets",
        panels=panels,
        text_channels=text_channels,
        categories=categories,
        roles=roles,
    ))

@bp.route("/dashboard/<guild_id>/reactionroles")
@guild_access_required
def server_reactionroles(guild_id: str):
    panels = db.get_reaction_roles_panels(guild_id)
    text_channels = db.get_guild_channels(guild_id) or []
    
    roles = get_guild_roles(guild_id)

    return render_template("reactionroles.html", **_server_ctx(
        guild_id, "reactionroles",
        panels=panels,
        text_channels=text_channels,
        roles=roles,
    ))

@bp.route("/dashboard/<guild_id>/economy", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_economy", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/economy/add_item", methods=["POST"])
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
    return redirect(url_for("guild.server_economy", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/economy/delete_item/<int:item_id>", methods=["POST"])
@guild_access_required
def server_economy_delete_item(guild_id: str, item_id: int):
    db.delete_economy_shop_item(item_id, guild_id)
    flash("✅ Đã xóa vật phẩm khỏi Cửa hàng!", "success")
    return redirect(url_for("guild.server_economy", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/tempvoice", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_tempvoice", guild_id=guild_id))

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

@bp.route("/dashboard/<guild_id>/tempvoice/delete_channel/<channel_id>", methods=["POST"])
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
    return redirect(url_for("guild.server_tempvoice", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/customcommands", methods=["GET"])
@guild_access_required
def server_customcommands(guild_id: str):
    custom_cmds = db.get_custom_commands(guild_id)

    return render_template(
        "server_customcommands.html",
        **_server_ctx(guild_id, active_page="customcommands"),
        custom_cmds=custom_cmds
    )

@bp.route("/dashboard/<guild_id>/customcommands/add", methods=["POST"])
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

    return redirect(url_for("guild.server_customcommands", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/customcommands/delete/<int:cmd_id>", methods=["POST"])
@guild_access_required
def server_customcommands_delete(guild_id: str, cmd_id: int):
    db.delete_custom_command(cmd_id, guild_id)
    flash("✅ Đã xóa lệnh tùy biến!", "success")
    return redirect(url_for("guild.server_customcommands", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/ai", methods=["GET", "POST"])
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
        return redirect(url_for("guild.server_ai", guild_id=guild_id))

    ai_settings = db.get_ai_settings(guild_id)
    channels = db.get_guild_channels(guild_id)
    text_channels = [c for c in channels if c.get("channel_type") == 0]

    return render_template(
        "server_ai.html",
        **_server_ctx(guild_id, active_page="ai"),
        ai_settings=ai_settings,
        text_channels=text_channels
    )

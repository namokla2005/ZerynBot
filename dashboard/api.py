"""
api.py — REST JSON API endpoints for the dashboard.
Imported as a Blueprint and registered in app.py.
"""
import sys, os
_V2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho card_generator, checks, etc.

from flask import Blueprint, request, jsonify, session
import requests
import database as db
import config
from i18n import i18n as i18n_manager

api = Blueprint("api", __name__, url_prefix="/api")


def _require_guild_access(guild_id: str):
    """Return error response if user doesn't have access to this guild."""
    guilds = session.get("guilds", [])
    allowed = {g["id"] for g in guilds if g.get("bot_in_guild")}
    if guild_id not in allowed:
        return jsonify({"error": "Forbidden"}), 403
    return None


# ─── Welcome / Goodbye settings ────────────────────────────────────────────────

@api.route("/guild/<guild_id>/welcome", methods=["POST"])
def save_welcome(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    data = request.json or {}
    allowed_fields = {
        "welcome_channel_id", "welcome_message", "welcome_use_embed",
        "welcome_embed_color", "welcome_embed_title",
        "goodbye_channel_id", "goodbye_message", "goodbye_use_embed",
        "goodbye_embed_color", "goodbye_embed_title",
    }
    fields = {k: v for k, v in data.items() if k in allowed_fields}
    if fields:
        db.upsert_guild(guild_id, **fields)
    return jsonify({"ok": True})


# ─── Modules ───────────────────────────────────────────────────────────────────

@api.route("/guild/<guild_id>/modules", methods=["GET"])
def get_modules(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    return jsonify(db.get_guild_modules(guild_id))


@api.route("/guild/<guild_id>/modules/<module_name>", methods=["POST"])
def toggle_module(guild_id: str, module_name: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    data = request.json or {}
    enabled = bool(data.get("enabled", True))
    db.set_module(guild_id, module_name, enabled)
    return jsonify({"ok": True, "enabled": enabled})


# ─── Saved embeds ──────────────────────────────────────────────────────────────

@api.route("/guild/<guild_id>/embeds", methods=["GET"])
def list_embeds(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    embeds = db.get_saved_embeds(guild_id)
    return jsonify(embeds)


@api.route("/guild/<guild_id>/embeds", methods=["POST"])
def create_embed(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    data = request.json or {}
    name = data.get("name", "Embed không tên")
    embed_data = data.get("embed", {})
    embed_id = db.save_embed(guild_id, name, embed_data)
    return jsonify({"ok": True, "id": embed_id})


@api.route("/guild/<guild_id>/embeds/<int:embed_id>", methods=["DELETE"])
def delete_embed(guild_id: str, embed_id: int):
    err = _require_guild_access(guild_id)
    if err:
        return err
    db.delete_embed(embed_id, guild_id)
    return jsonify({"ok": True})


# ─── Channels (for dropdowns) ──────────────────────────────────────────────────

@api.route("/guild/<guild_id>/channels", methods=["GET"])
def get_channels(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    return jsonify(db.get_guild_channels(guild_id))


# ─── Send embed / message to a channel ────────────────────────────────────────

@api.route("/guild/<guild_id>/send-embed", methods=["POST"])
def send_embed_to_channel(guild_id: str):
    """Send an embed (and/or plain text) to a Discord channel using the bot token."""
    err = _require_guild_access(guild_id)
    if err:
        return err

    data       = request.json or {}
    channel_id = data.get("channel_id")
    embed_data  = data.get("embed") or {}
    content     = data.get("content", "")

    if not channel_id:
        return jsonify({"error": "Vui lòng chọn kênh"}), 400

    discord_embed = _build_discord_embed(embed_data)

    payload: dict = {}
    if content:
        payload["content"] = str(content)[:2000]
    if discord_embed:
        payload["embeds"] = [discord_embed]

    if not payload:
        return jsonify({"error": "Không có nội dung để gửi (embed trống)"}), 400

    try:
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {config.TOKEN}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return jsonify({"ok": True})
        try:
            err_msg = resp.json().get("message", resp.text)
        except Exception:
            err_msg = resp.text
        return jsonify({"error": err_msg}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _build_discord_embed(data: dict) -> dict:
    """Convert dashboard embed dict → Discord API embed object."""
    if not data:
        return {}
    e: dict = {}

    if data.get("color"):
        try:
            e["color"] = int(str(data["color"]).lstrip("#"), 16)
        except Exception:
            e["color"] = 0x5865F2

    if data.get("title"):
        e["title"] = str(data["title"])[:256]
    if data.get("url"):
        e["url"] = str(data["url"])
    if data.get("description"):
        e["description"] = str(data["description"])[:4096]

    author = data.get("author") or {}
    if isinstance(author, dict) and author.get("name"):
        e["author"] = {"name": str(author["name"])[:256]}

    if data.get("thumbnail"):
        e["thumbnail"] = {"url": str(data["thumbnail"])}
    if data.get("image"):
        e["image"] = {"url": str(data["image"])}

    footer = data.get("footer") or {}
    if isinstance(footer, dict) and footer.get("text"):
        fo = {"text": str(footer["text"])[:2048]}
        if footer.get("icon_url"):
            fo["icon_url"] = str(footer["icon_url"])
        e["footer"] = fo

    raw_fields = data.get("fields") or []
    if raw_fields:
        e["fields"] = [
            {
                "name":   str(f.get("name",  "\u200b"))[:256],
                "value":  str(f.get("value", "\u200b"))[:1024],
                "inline": bool(f.get("inline", False)),
            }
            for f in raw_fields[:25]
            if f.get("name") or f.get("value")
        ]

    return e


# ─── Ticket Panels ────────────────────────────────────────────────────────────

@api.route("/guild/<guild_id>/tickets", methods=["POST"])
def save_ticket(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    data = request.json or {}
    panel_data = data.get("panel", {})
    buttons_data = data.get("buttons", [])
    
    panel_id = db.save_ticket_panel(guild_id, panel_data, buttons_data)
    return jsonify({"ok": True, "id": panel_id})


@api.route("/guild/<guild_id>/tickets/<int:panel_id>", methods=["DELETE"])
def delete_ticket(guild_id: str, panel_id: int):
    err = _require_guild_access(guild_id)
    if err:
        return err
    
    db.delete_ticket_panel(panel_id, guild_id)
    return jsonify({"ok": True})


@api.route("/guild/<guild_id>/tickets/<int:panel_id>/send", methods=["POST"])
def send_ticket_panel(guild_id: str, panel_id: int):
    err = _require_guild_access(guild_id)
    if err:
        return err
        
    panel = db.get_ticket_panel(panel_id)
    if not panel:
        return jsonify({"error": "Không tìm thấy panel"}), 404
        
    # Build embed
    embed_data = {
        "title": panel.get("title"),
        "description": panel.get("description"),
        "color": panel.get("color"),
        "image": panel.get("image_url"),
        "thumbnail": panel.get("thumbnail_url"),
        "footer": {"text": panel.get("footer_text")} if panel.get("footer_text") else None
    }
    discord_embed = _build_discord_embed(embed_data)
    
    # Build buttons components
    STYLE_MAP = {
        "primary": 1,
        "secondary": 2,
        "success": 3,
        "danger": 4
    }
    buttons = panel.get("buttons", [])
    discord_components = []
    if buttons:
        action_row = {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": STYLE_MAP.get(btn["style"], 1),
                    "label": btn["label"],
                    "custom_id": f"ticket:btn:{btn['id']}"
                }
                for btn in buttons[:5] # Max 5 buttons per action row in Discord
            ]
        }
        discord_components.append(action_row)
        
    payload = {
        "embeds": [discord_embed] if discord_embed else []
    }
    if discord_components:
        payload["components"] = discord_components
        
    if not payload["embeds"] and not payload.get("components"):
        return jsonify({"error": "Nội dung panel trống!"}), 400
        
    # Try deleting old message
    old_msg_id = panel.get("message_id")
    if old_msg_id:
        try:
            requests.delete(
                f"https://discord.com/api/v10/channels/{panel['channel_id']}/messages/{old_msg_id}",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5
            )
        except Exception:
            pass
            
    # Send new message
    try:
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{panel['channel_id']}/messages",
            headers={"Authorization": f"Bot {config.TOKEN}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            new_msg_id = resp.json().get("id")
            db.update_panel_message_id(panel_id, new_msg_id)
            return jsonify({"ok": True, "message_id": new_msg_id})
            
        try:
            err_msg = resp.json().get("message", resp.text)
        except Exception:
            err_msg = resp.text
        return jsonify({"error": f"Discord API Error: {err_msg}"}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─── Reaction Roles ───────────────────────────────────────────────────────────

@api.route("/guild/<guild_id>/reactionroles", methods=["POST"])
def save_reaction_role(guild_id: str):
    err = _require_guild_access(guild_id)
    if err:
        return err
    data = request.json or {}
    panel_data = data.get("panel", {})
    items_data = data.get("items", [])
    
    panel_id = db.save_reaction_roles_panel(guild_id, panel_data, items_data)
    return jsonify({"ok": True, "id": panel_id})


@api.route("/guild/<guild_id>/reactionroles/<int:panel_id>", methods=["DELETE"])
def delete_reaction_role(guild_id: str, panel_id: int):
    err = _require_guild_access(guild_id)
    if err:
        return err
    
    db.delete_reaction_roles_panel(panel_id, guild_id)
    return jsonify({"ok": True})


@api.route("/guild/<guild_id>/reactionroles/<int:panel_id>/send", methods=["POST"])
def send_reaction_role_panel(guild_id: str, panel_id: int):
    err = _require_guild_access(guild_id)
    if err:
        return err
        
    panel = db.get_reaction_roles_panel(panel_id)
    if not panel:
        return jsonify({"error": "Không tìm thấy panel"}), 404
        
    embed_data = {
        "title": panel.get("title"),
        "description": panel.get("description"),
        "color": panel.get("color"),
        "image": panel.get("image_url"),
        "thumbnail": panel.get("thumbnail_url"),
        "footer": {"text": panel.get("footer_text")} if panel.get("footer_text") else None
    }
    discord_embed = _build_discord_embed(embed_data)
    
    payload = {
        "embeds": [discord_embed] if discord_embed else []
    }
        
    if not payload["embeds"]:
        return jsonify({"error": "Nội dung panel trống!"}), 400
        
    import urllib.parse
    
    old_msg_id = panel.get("message_id")
    if old_msg_id:
        try:
            requests.delete(
                f"https://discord.com/api/v10/channels/{panel['channel_id']}/messages/{old_msg_id}",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5
            )
        except Exception:
            pass
            
    try:
        resp = requests.post(
            f"https://discord.com/api/v10/channels/{panel['channel_id']}/messages",
            headers={"Authorization": f"Bot {config.TOKEN}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            new_msg_id = resp.json().get("id")
            db.update_reaction_roles_message_id(panel_id, new_msg_id)
            
            # Add reactions
            items = panel.get("items", [])
            for item in items:
                emoji = item["emoji"]
                # For custom emojis like <:name:id>, the API expects name:id
                if emoji.startswith("<:") and emoji.endswith(">"):
                    emoji_parsed = emoji.strip("<>").split(":", 1)[1] # yields name:id
                elif emoji.startswith("<a:") and emoji.endswith(">"):
                    emoji_parsed = emoji.strip("<>").split(":", 1)[1]
                else:
                    emoji_parsed = emoji
                    
                emoji_encoded = urllib.parse.quote(emoji_parsed)
                
                try:
                    _req.put(
                        f"https://discord.com/api/v10/channels/{panel['channel_id']}/messages/{new_msg_id}/reactions/{emoji_encoded}/@me",
                        headers={"Authorization": f"Bot {config.TOKEN}"},
                        timeout=5
                    )
                except Exception as e:
                    print(f"Error adding reaction: {e}")
                    
            return jsonify({"ok": True, "message_id": new_msg_id})
            
        try:
            err_msg = resp.json().get("message", resp.text)
        except Exception:
            err_msg = resp.text
        return jsonify({"error": f"Discord API Error: {err_msg}"}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─── Test welcome/goodbye banner card ─────────────────────────────────────────

@api.route("/guild/<guild_id>/send-test-card", methods=["POST"])
def send_test_card(guild_id: str):
    """Generate and send a welcome/goodbye banner card using the real logged-in user."""
    err = _require_guild_access(guild_id)
    if err:
        return err

    data      = request.json or {}
    card_type = data.get("type", "welcome")   # "welcome" | "goodbye"

    settings   = db.get_guild_settings(guild_id)
    channel_id = settings.get(f"{card_type}_channel_id")
    if not channel_id:
        return jsonify({"error": f"Chưa chọn kênh {card_type}"}), 400

    # Retrieve current unsaved state from frontend, or fallback to saved settings
    use_embed = data.get("use_embed")
    if use_embed is None:
        use_embed = bool(settings.get(f"{card_type}_use_embed", 1))

    custom_msg = data.get("message")
    if custom_msg is None:
        custom_msg = settings.get(f"{card_type}_message")

    # ── Real user from session ──────────────────────────────────────────────
    from flask import session as flask_session
    user        = flask_session.get("user", {})
    avatar_url  = flask_session.get("avatar", "")
    # global_name is the display name (e.g. "Nam"); fallback to username
    display_name = user.get("global_name") or user.get("username") or "User"

    # ── Guild info ─────────────────────────────────────────────────────────
    guild_meta   = db.get_guild_meta(guild_id) or {}
    guild_name   = guild_meta.get("name", "Server")
    member_count = guild_meta.get("member_count", "???")

    # ── Format message ─────────────────────────────────────────────────────
    user_id_str = user.get("id", "000")
    def format_msg(text, default_text):
        if not text:
            return default_text
        text = text.replace("{user}", f"<@{user_id_str}>")
        text = text.replace("{user_name}", display_name)
        text = text.replace("{server}", guild_name)
        text = text.replace("{member_count}", str(member_count))
        text = text.replace("{user_id}", user_id_str)
        return text

    if card_type == "welcome":
        raw_msg = custom_msg or "👋 **{user_name}** đã tham gia **{server}**!"
        content_msg = format_msg(raw_msg, f"👋 **{display_name}** đã tham gia **{guild_name}**!")
    else:
        raw_msg = custom_msg or "👋 **{user_name}** đã rời khỏi **{server}**."
        content_msg = format_msg(raw_msg, f"👋 **{display_name}** đã rời khỏi **{guild_name}**.")

    # ── Generate card if enabled ───────────────────────────────────────────
    buf = None
    if use_embed:
        avatar_bytes = None
        if avatar_url:
            try:
                r = requests.get(avatar_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
                if r.status_code == 200:
                    avatar_bytes = r.content
            except Exception:
                pass

        bg_bytes = None
        # get bg_url from frontend request, fallback to db
        bg_url = data.get("bg_url")
        if bg_url is None:
            bg_url = settings.get(f"{card_type}_bg_url")

        if bg_url:
            try:
                r = requests.get(bg_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
                if r.status_code == 200:
                    bg_bytes = r.content
            except Exception:
                pass

        try:
            try:
                from bot.card_generator import _render_card
            except (ImportError, ModuleNotFoundError):
                from card_generator import _render_card
            if card_type == "welcome":
                buf = _render_card(
                    avatar_bytes  = avatar_bytes,
                    top_label     = f"Member #{member_count}",
                    username      = f"Welcome {display_name}",
                    preposition   = "to",
                    server_name   = guild_name,
                    accent_color  = (0, 132, 255),    # Ignored now
                    accent_color2 = (0, 212, 255),    # Ignored now
                    bg_bytes      = bg_bytes,
                )
            else:
                buf = _render_card(
                    avatar_bytes  = avatar_bytes,
                    top_label     = "Sad to see you go!",
                    username      = f"Goodbye {display_name}",
                    preposition   = "from",
                    server_name   = guild_name,
                    accent_color  = (237, 66, 69),    # Ignored now
                    accent_color2 = (255, 120, 120),  # Ignored now
                    bg_bytes      = bg_bytes,
                )
        except Exception as e:
            return jsonify({"error": f"Lỗi tạo card: {e}"}), 500

    # ── Send to Discord ────────────────────────────────────────────────────
    try:
        req_kwargs = {
            "headers": {"Authorization": f"Bot {config.TOKEN}"},
            "data": {"content": content_msg},
            "timeout": 15
        }
        if buf:
            req_kwargs["files"] = {"files[0]": (f"{card_type}.png", buf, "image/png")}

        resp = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            **req_kwargs
        )
        if resp.status_code in (200, 201):
            return jsonify({"ok": True})
        try:
            err_msg = resp.json().get("message", resp.text)
        except Exception:
            err_msg = resp.text
        return jsonify({"error": err_msg}), resp.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─── i18n: Guild Language ────────────────────────────────────────────────────────────

@api.route("/guild/<guild_id>/language", methods=["POST"])
def set_guild_language_api(guild_id: str):
    """
    Cập nhật ngôn ngữ bot cho Guild (lưu vào DB).
    Độc lập với session['ui_lang'] — không thay đổi ngôn ngữ giao diện web của user.
    """
    err = _require_guild_access(guild_id)
    if err:
        return err

    data = request.json or {}
    lang_code = data.get("language", "vi").lower().strip()
    supported = i18n_manager.get_supported_languages()

    if lang_code not in supported:
        return jsonify({
            "error": f"Unsupported language '{lang_code}'. Supported: {list(supported.keys())}"
        }), 400

    db.set_guild_language(guild_id, lang_code)
    # DO NOT set session["ui_lang"] — the two are intentionally separate
    return jsonify({"ok": True, "language": lang_code, "label": supported[lang_code]})

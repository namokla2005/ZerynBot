"""
auth.py — Discord OAuth2 helpers for the Flask dashboard.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ipaddress
import time
from urllib.parse import urlencode, urlparse

import requests
import config

# Permissions bit: Manage Guild (0x20 = 32)
MANAGE_GUILD = 0x20

# TTL làm mới danh sách guild trong session (giây) — chống session cũ sau khi
# user bị thu hồi quyền MANAGE_GUILD trên Discord.
SESSION_GUILD_TTL = 15 * 60

# TTL cache danh sách kênh của guild (giây) — dùng cho kiểm tra quyền sở hữu kênh.
_CHANNEL_CACHE_TTL = 300
_channel_cache: dict = {}  # guild_id -> (timestamp, set_of_channel_ids)


def get_oauth2_url(state: str = "") -> str:
    """Build the Discord OAuth2 authorization URL (kèm state chống Login CSRF)."""
    params = {
        "client_id":     config.CLIENT_ID,
        "redirect_uri":  config.REDIRECT_URI,
        "response_type": "code",
        "scope":         config.OAUTH2_SCOPES,
    }
    if state:
        params["state"] = state
    return f"{config.OAUTH2_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for an access token."""
    data = {
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  config.REDIRECT_URI,
    }
    resp = requests.post(
        config.OAUTH2_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_user(access_token: str) -> dict:
    """Fetch current user from Discord API."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_user_guilds(access_token: str) -> list:
    """Fetch guilds the user is in."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_bot_guilds() -> list:
    """Fetch guilds the bot is in (using bot token)."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bot {config.TOKEN}"},
        timeout=10,
    )
    if not resp.ok:
        return []
    return resp.json()

def get_member_roles(guild_id: str, user_id: str) -> list:
    """Fetch member's role IDs from a guild using the bot token."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {config.TOKEN}"},
        timeout=10,
    )
    if not resp.ok:
        return []
    data = resp.json()
    return data.get("roles", [])


def get_manageable_guilds(access_token: str) -> list:
    """
    Return guilds where:
    - The user has MANAGE_GUILD permission, AND
    - The bot is present in that guild.
    Each guild dict gets an extra 'bot_in_guild' key.
    """
    user_guilds = get_user_guilds(access_token)
    bot_guild_ids = {g["id"] for g in get_bot_guilds()}

    result = []
    for g in user_guilds:
        perms = int(g.get("permissions", 0))
        if perms & MANAGE_GUILD:
            g["bot_in_guild"] = g["id"] in bot_guild_ids
            g["icon_url"] = (
                f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
                if g.get("icon") else None
            )
            result.append(g)
    return result


def get_avatar_url(user: dict) -> str:
    """Build Discord CDN avatar URL for a user dict."""
    uid   = user.get("id", "")
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{ext}?size=256"
    disc = int(user.get("discriminator", 0) or 0)
    return f"https://cdn.discordapp.com/embed/avatars/{disc % 5}.png"


# ─── Guild channel ownership guard (chống IDOR cross-server, P0.4) ─────────────

def get_guild_channel_ids(guild_id: str) -> set:
    """
    Lấy tập hợp channel_id HỢP LỆ của một guild (kênh text/voice/category),
    xác thực trực tiếp qua Discord REST bằng bot token (authoritative),
    cache ngắn 5 phút để không spam API.

    Trả về None nếu không gọi được Discord API (mạng/token lỗi) — caller nên
    fail-closed (từ chối) trong trường hợp đó cho các hành động nhạy cảm.
    """
    now = time.time()
    cached = _channel_cache.get(guild_id)
    if cached and now - cached[0] < _CHANNEL_CACHE_TTL:
        return cached[1]

    try:
        resp = requests.get(
            f"{config.DISCORD_API_BASE}/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=10,
        )
        if not resp.ok:
            # Fallback: dữ liệu cache nội bộ do bot đồng bộ (guild_channels table)
            import database as db
            local = {str(c.get("channel_id")) for c in db.get_guild_channels(guild_id)}
            if local:
                _channel_cache[guild_id] = (now, local)
                return local
            return None
        ids = {str(c["id"]) for c in resp.json()}
        _channel_cache[guild_id] = (now, ids)
        return ids
    except Exception:
        import database as db
        try:
            local = {str(c.get("channel_id")) for c in db.get_guild_channels(guild_id)}
            if local:
                _channel_cache[guild_id] = (now, local)
                return local
        except Exception:
            pass
        return None


def channel_belongs_to_guild(guild_id: str, channel_id) -> bool:
    """True chỉ khi channel_id tồn tại VÀ thuộc đúng guild_id (fail-closed)."""
    if not channel_id:
        return False
    ids = get_guild_channel_ids(str(guild_id))
    if ids is None:
        return False  # không xác thực được → từ chối (an toàn)
    return str(channel_id) in ids


def invalidate_guild_channel_cache(guild_id: str) -> None:
    """Xóa cache kênh của guild (gọi sau khi bot đồng bộ lại danh sách kênh)."""
    _channel_cache.pop(str(guild_id), None)


# ─── SSRF guard cho URL người dùng nhập (P1.8) ─────────────────────────────────

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def is_safe_http_url(url: str) -> bool:
    """
    Chỉ cho phép URL http(s) trỏ ra Internet công cộng.
    Chặn: scheme lạ, host trống, localhost, IP private/loopback/link-local/multicast
    (literal). Không resolve DNS (giữ nhẹ cho Termux) — đủ chặn các payload phổ biến.
    """
    if not url or not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".local"):
        return False
    # Nếu host là IP literal → kiểm tra dải IP
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return False
    except ValueError:
        pass  # hostname thường, không phải IP literal
    return True

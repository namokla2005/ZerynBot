"""
auth.py — Discord OAuth2 helpers for the Flask dashboard.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ipaddress
import socket
import threading
import time
from urllib.parse import urlencode, urlparse, urljoin
import re

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


# ─── OAuth access-token vault (token thật KHÔNG nằm trong session cookie) ──────
# Flask chỉ KÝ session cookie chứ không mã hóa nội dung. Trước đây `access_token`
# được nhét thẳng vào session, nghĩa là bearer token của người dùng nằm trong cookie
# jar (và mọi bản sao cookie: log proxy, backup trình duyệt, máy dùng chung) suốt
# SESSION_LIFETIME_DAYS = 7 ngày, và `/logout` chỉ xóa phía mình chứ không thu hồi
# trên Discord. Giờ cookie chỉ mang một con trỏ ngẫu nhiên.
_token_vault: dict = {}          # token_id -> (access_token, expires_at)
_token_lock = threading.Lock()
_TOKEN_VAULT_TTL = 7 * 24 * 3600


def store_access_token(access_token: str) -> str:
    """Lưu token vào bộ nhớ tiến trình, trả về id ngẫu nhiên để nhét vào session."""
    import secrets as _secrets

    token_id = _secrets.token_urlsafe(16)
    expires_at = time.time() + _TOKEN_VAULT_TTL
    with _token_lock:
        now = time.time()
        for stale in [k for k, (_, exp) in _token_vault.items() if exp < now]:
            _token_vault.pop(stale, None)
        _token_vault[token_id] = (access_token, expires_at)
    return token_id


def drop_access_token(token_id: str = None) -> None:
    """Xóa token khỏi vault; không truyền id thì xóa theo phiên hiện tại."""
    from flask import session

    with _token_lock:
        if token_id is None:
            token_id = session.pop("oauth_token_id", None)
        if token_id:
            _token_vault.pop(token_id, None)


def get_access_token() -> str:
    """Token của phiên hiện tại, hoặc "" nếu chưa đăng nhập / hết hạn / restart dashboard."""
    from flask import session

    token_id = session.get("oauth_token_id")
    if not token_id:
        return ""
    with _token_lock:
        entry = _token_vault.get(token_id)
    if not entry:
        return ""
    token, expires_at = entry
    if expires_at < time.time():
        drop_access_token(token_id)
        return ""
    return token


def revoke_access_token() -> bool:
    """Báo Discord thu hồi access token khi logout — token đánh cắp sẽ vô dụng ngay."""
    token = get_access_token()
    try:
        if not token or not config.CLIENT_SECRET:
            return False
        requests.post(
            "https://discord.com/api/oauth2/token/revoke",
            data={
                "token": token,
                "client_id": config.CLIENT_ID,
                "client_secret": config.CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return True
    except Exception:
        return False
    finally:
        drop_access_token()


def get_user(access_token: str) -> dict:
    """Fetch current user from Discord API (thu gọn tối đa để giữ session cookie < 1KB)."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    raw = resp.json()
    return {
        "id": str(raw.get("id", "")),
        "username": str(raw.get("username", "")),
        "global_name": raw.get("global_name"),
        "avatar": raw.get("avatar"),
    }


def get_user_guilds(access_token: str) -> list:
    """Fetch guilds the user is in."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


_bot_guilds_cache_box = {"ts": 0.0, "data": []}
_BOT_GUILDS_CACHE_TTL = 120.0
_bot_guilds_lock = threading.Lock()

def get_bot_guilds() -> list:
    """Fetch guilds the bot is in (using bot token), cached 120s with thread lock."""
    with _bot_guilds_lock:
        now = time.time()
        if _bot_guilds_cache_box["data"] and (now - _bot_guilds_cache_box["ts"] < _BOT_GUILDS_CACHE_TTL):
            return _bot_guilds_cache_box["data"]

        try:
            resp = requests.get(
                f"{config.DISCORD_API_BASE}/users/@me/guilds",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5,
            )
            if resp.ok:
                data = resp.json()
                _bot_guilds_cache_box["ts"] = time.time()
                _bot_guilds_cache_box["data"] = data
                return data
        except Exception as e:
            logger.warning("Lỗi fetch bot guilds từ Discord API: %s", e)

        return _bot_guilds_cache_box["data"]

_MEMBER_ROLES_TTL = 60.0
_member_roles_cache: dict = {}  # (guild_id, user_id) -> (timestamp, list_of_roles)

def get_member_roles(guild_id: str, user_id: str) -> list:
    """Fetch member's role IDs from a guild using the bot token (cached 60s)."""
    global _member_roles_cache
    now = time.time()
    cache_key = (str(guild_id), str(user_id))
    cached = _member_roles_cache.get(cache_key)
    if cached and now - cached[0] < _MEMBER_ROLES_TTL:
        return cached[1]

    if len(_member_roles_cache) > 500:
        _member_roles_cache = {k: v for k, v in _member_roles_cache.items() if now - v[0] < _MEMBER_ROLES_TTL}

    try:
        resp = requests.get(
            f"{config.DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            headers={"Authorization": f"Bot {config.TOKEN}"},
            timeout=5,
        )
        if not resp.ok:
            return cached[1] if cached else []
        data = resp.json()
        roles = data.get("roles", [])
        _member_roles_cache[cache_key] = (now, roles)
        return roles
    except Exception:
        return cached[1] if cached else []


def get_guild_icon_url(guild_id: str | None, icon_hash: str | None) -> str | None:
    """Xây dựng Discord CDN URL an toàn cho Server Icon, validate chặt chống injection."""
    if not guild_id or not icon_hash:
        return None
    s_id = str(guild_id).strip()
    s_icon = str(icon_hash).strip()
    if not s_id.isdigit():
        return None
    if not re.match(r"^[a-zA-Z0-9_]+$", s_icon):
        return None
    ext = "gif" if s_icon.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/icons/{s_id}/{s_icon}.{ext}"


def get_manageable_guilds(access_token: str) -> list:
    """
    Return guilds where:
    - The user has MANAGE_GUILD permission, AND
    - The bot is present in that guild.
    Each guild dict gets an extra 'bot_in_guild' key.
    Giới hạn tối đa 15 guild và làm sạch trường dữ liệu để cookie Flask luôn < 1.5KB.
    """
    user_guilds = get_user_guilds(access_token)
    bot_guild_ids = {g["id"] for g in get_bot_guilds()}

    result = []
    for g in user_guilds:
        perms = int(g.get("permissions", 0))
        if perms & MANAGE_GUILD:
            raw_id = str(g.get("id", "")).strip()
            if not raw_id.isdigit():
                continue
            raw_icon = g.get("icon")
            clean_icon = str(raw_icon).strip() if (raw_icon and re.match(r"^[a-zA-Z0-9_]+$", str(raw_icon).strip())) else None

            result.append({
                "id": raw_id,
                "name": str(g.get("name", "Server"))[:25],
                "icon": clean_icon,
                "bot_in_guild": raw_id in bot_guild_ids,
                "owner": bool(g.get("owner", False)),
            })
            if len(result) >= 15:
                break
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


# ─── Cache danh sách role của guild (tránh gọi REST mỗi lần mở trang) ──────────

_GUILD_ROLES_TTL = 300.0
_guild_roles_cache: dict = {}  # guild_id -> (timestamp, list_of_role_dicts)


def _normalize_db_role(row: dict) -> dict:
    """Chuẩn hoá 1 dòng bảng guild_roles về đúng dạng payload role của Discord REST."""
    return {
        "id": str(row.get("role_id") or row.get("id") or ""),
        "name": row.get("role_name") or row.get("name") or "",
        "color": row.get("color_hex"),
        "position": row.get("position") or 0,
    }


def get_guild_roles(guild_id: str, include_everyone: bool = False) -> list:
    """
    Lấy danh sách role của guild qua Discord REST (bot token), cache 5 phút.

    Dedupe tải cho Termux: trước đây mỗi lần mở /tickets và /reactionroles là
    một request REST 5s giữ 1 trong 4 thread của waitress.

    Fallback (khi REST lỗi hoặc chưa có token): bảng guild_roles do bot đồng bộ,
    đã được chuẩn hoá về cùng dạng dict (id/name/color/position) để template dùng
    chung một đường.
    """
    global _guild_roles_cache
    gid = str(guild_id)
    now = time.time()

    cached = _guild_roles_cache.get(gid)
    if cached and now - cached[0] < _GUILD_ROLES_TTL:
        return cached[1]

    # Dọn cache hết hạn khi vượt ngưỡng (không để dict phình mãi trên máy 6GB).
    if len(_guild_roles_cache) > 200:
        _guild_roles_cache = {
            k: v for k, v in _guild_roles_cache.items() if now - v[0] < _GUILD_ROLES_TTL
        }

    roles: list = []
    try:
        if config.TOKEN:
            resp = requests.get(
                f"{config.DISCORD_API_BASE}/guilds/{gid}/roles",
                headers={"Authorization": f"Bot {config.TOKEN}"},
                timeout=5,
            )
            if resp.ok:
                roles = [
                    r for r in resp.json()
                    if include_everyone or r.get("name") != "@everyone"
                ]
    except Exception:
        roles = []

    if not roles:
        try:
            import database as db
            roles = [_normalize_db_role(r) for r in (db.get_guild_roles(gid) or [])]
            if not include_everyone:
                roles = [r for r in roles if r.get("name") != "@everyone"]
        except Exception:
            roles = []

    if roles:
        _guild_roles_cache[gid] = (now, roles)
    return roles


def invalidate_guild_roles_cache(guild_id: str) -> None:
    """Xóa cache role của guild (gọi sau khi bot đồng bộ lại danh sách role)."""
    _guild_roles_cache.pop(str(guild_id), None)


# ─── SSRF guard cho URL người dùng nhập (P1.8) ─────────────────────────────────

_BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "metadata.google.internal",
    "host.docker.internal", "metadata", "instance-data"
}

_DNS_CACHE: dict[str, tuple[float, bool]] = {}
_DNS_CACHE_TTL = 60.0  # cache kết quả DNS 60s để giảm tải cho Termux


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _cache_dns_result(host: str, is_safe: bool) -> None:
    if len(_DNS_CACHE) > 500:
        _DNS_CACHE.clear()
    _DNS_CACHE[host] = (time.time(), is_safe)


def is_safe_http_url(url: str) -> bool:
    """
    Chỉ cho phép URL http(s) trỏ ra Internet công cộng.
    Chặn:
    - Scheme không phải http hoặc https.
    - Hostname rỗng, bị cấm (.local, .internal, .lan, localhost...).
    - IP dạng số (decimal, octal) và IPv6 loopback.
    - Phân giải DNS kiểm tra toàn bộ IP (IPv4 & IPv6): chặn dải private,
      loopback, link-local (169.254.x), reserved, multicast.
    - Có cơ chế cache kết quả DNS 60s để tiết kiệm tài nguyên mạng cho Termux.
    """
    if not url or not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith((".local", ".internal", ".lan")):
        return False

    # Kiểm tra cache DNS
    now = time.time()
    cached = _DNS_CACHE.get(host)
    if cached and (now - cached[0]) < _DNS_CACHE_TTL:
        return cached[1]

    # 1. Kiểm tra nếu host là IP literal (kể cả dạng số nguyên decimal)
    try:
        if host.isdigit():
            ip_obj = ipaddress.ip_address(int(host))
            if _is_disallowed_ip(ip_obj):
                _cache_dns_result(host, False)
                return False
        else:
            ip_obj = ipaddress.ip_address(host)
            if _is_disallowed_ip(ip_obj):
                _cache_dns_result(host, False)
                return False
    except ValueError:
        pass  # Hostname thông thường dạng tên miền

    # 2. Phân giải DNS thực tế để kiểm tra IP đích
    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        if not addr_info:
            _cache_dns_result(host, False)
            return False

        for item in addr_info:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if _is_disallowed_ip(ip_obj):
                    _cache_dns_result(host, False)
                    return False
            except ValueError:
                _cache_dns_result(host, False)
                return False
    except (socket.gaierror, socket.herror, TimeoutError):
        _cache_dns_result(host, False)
        return False
    except Exception:
        _cache_dns_result(host, False)
        return False

    _cache_dns_result(host, True)
    return True


def safe_download_image(url: str, max_bytes: int = 5 * 1024 * 1024, timeout: float = 8.0) -> bytes | None:
    """
    Tải tài nguyên hình ảnh HTTP an toàn:
    - Kiểm tra is_safe_http_url trước khi gửi
    - Tắt allow_redirects tự động, tự kiểm tra URL ở MỌI chặng redirect (tối đa 3 hops)
    - Đọc theo stream và ngắt nếu vượt quá max_bytes (chống DoS / cạn kiệt RAM Termux)
    - Trả về bytes nếu hợp lệ, None nếu có lỗi / URL không an toàn / vượt kích thước
    """
    if not is_safe_http_url(url):
        return None

    current_url = url
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for _ in range(4):  # Tối đa 3 lần redirect
        if not is_safe_http_url(current_url):
            return None
        try:
            resp = requests.get(
                current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    return None
                current_url = urljoin(current_url, location)
                continue

            if resp.status_code != 200:
                return None

            clength = resp.headers.get("Content-Length")
            if clength and clength.isdigit() and int(clength) > max_bytes:
                return None

            content = bytearray()
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        return None
            return bytes(content)
        except Exception:
            return None

    return None


async def async_safe_download_image(url: str, max_bytes: int = 5 * 1024 * 1024, timeout: float = 8.0) -> bytes | None:
    """Async variant cho Discord bot (aiohttp)."""
    if not is_safe_http_url(url):
        return None

    import aiohttp
    current_url = url
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=client_timeout) as session:
            for _ in range(4):
                if not is_safe_http_url(current_url):
                    return None
                async with session.get(current_url, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location:
                            return None
                        current_url = urljoin(current_url, location)
                        continue
                    if resp.status != 200:
                        return None

                    clength = resp.headers.get("Content-Length")
                    if clength and clength.isdigit() and int(clength) > max_bytes:
                        return None

                    content = bytearray()
                    async for chunk in resp.content.iter_chunked(16384):
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            return None
                    return bytes(content)
    except Exception:
        return None
    return None

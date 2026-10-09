"""
web_helpers.py — Helper dùng chung cho các route: decorator auth, context chung
trang server, kiểm tra kênh thuộc guild, cache metadata bài hát.

Tách từ `dashboard/app.py` (Giai đoạn 3.2). Decorator ở đây trỏ tới endpoint
namespace MỚI (`public.login`, `guild.home`) — đó là lý do phải đổi tên endpoint
trong cùng bước tách blueprint.
"""

import os
import sys

_V2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import json
import time as _time
from functools import wraps

import requests
from flask import flash, redirect, session, url_for

import config
import database as db
from dashboard.auth import (
    SESSION_GUILD_TTL,
    get_guild_channel_ids,
    get_manageable_guilds,
    get_member_roles,
    is_safe_http_url,
)
from dashboard.extensions import logger


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("public.login"))
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
    token = _auth.get_access_token()
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
            return redirect(url_for("public.login"))
        _refresh_guilds_if_stale()
        if "user" not in session:  # token Discord hết hạn trong lúc refresh
            return redirect(url_for("public.login"))
        guild_id = kwargs.get("guild_id", "")
        guild_info = _get_guild_from_session(guild_id)
        if not guild_info or not guild_info.get("bot_in_guild"):
            flash("Bạn không có quyền truy cập server này.", "error")
            return redirect(url_for("guild.home"))
            
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
                return redirect(url_for("guild.home"))
                
        return f(*args, **kwargs)
    return decorated

def _get_guild_from_session(guild_id: str) -> dict:
    guilds = session.get("guilds", [])
    return next((g for g in guilds if g["id"] == guild_id), {})

class VerificationUnavailable(RuntimeError):
    """Không kiểm chứng được id với Discord (mất mạng / bot mất quyền xem kênh).

    Handler lưu settings dựng dict rồi mới ghi DB, nên ném exception TỪ TRƯỚC lúc ghi
    cho kết quả đúng: không lưu id lạ, cũng không xóa mất cấu hình đang hợp lệ.
    `app_factory` đăng ký errorhandler flash thông báo rồi quay lại trang cũ.
    """


def _safe_channel(guild_id: str, channel_id):
    """Trả về channel_id nếu nó THỰC SỰ thuộc guild, ngược lại trả về None.

    Chặn cài kênh của server khác vào settings qua form craft tay. Trước đây khi Discord
    không trả được danh sách kênh thì hàm GIỮ NGUYÊN giá trị gửi lên (fail-open) — tức
    đúng lúc hệ thống đang trục trặc là lúc id lạ lọt được vào DB.
    """
    if not channel_id:
        return None
    from dashboard import auth as _auth
    ids = _auth.get_guild_channel_ids(str(guild_id))
    if ids is None:
        raise VerificationUnavailable(f"không kiểm chứng được danh sách kênh của guild {guild_id}")
    return str(channel_id) if str(channel_id) in ids else None


def _safe_role(guild_id: str, role_id):
    """Như _safe_channel nhưng cho role id — trước đây role KHÔNG được kiểm tra gì.

    Các trường notify_role_id / verified_role_id / pending_role_id / autoroles /
    level_role đều lưu thẳng id từ form, nên ai cũng có thể cắm id role của server khác.
    """
    if not role_id:
        return None
    from dashboard import auth as _auth
    roles = _auth.get_guild_roles(str(guild_id), include_everyone=True) or []
    ids = {str(r.get("id")) for r in roles if isinstance(r, dict) and r.get("id")}
    if not ids:
        raise VerificationUnavailable(f"không kiểm chứng được danh sách role của guild {guild_id}")
    return str(role_id) if str(role_id) in ids else None


def _to_int(value, default: int = 0, lo: int = None, hi: int = None) -> int:
    """Parse int từ form: chuỗi rác trả default thay vì 500 cả trang.

    Trước đây `int(form.get("message_xp_min", 15))` gặp ô bị xóa trắng là ValueError,
    và app không có errorhandler nào -> người dùng chỉ thấy trang lỗi của waitress.
    """
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n

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

_TRACK_INFO_CACHE_TTL = 600.0
_TRACK_INFO_CACHE_MAX = 200
_track_info_cache: dict = {}  # query đã chuẩn hoá -> (timestamp, dict)

def fetch_track_info_simple(query: str) -> dict:
    """Wrapper có cache cho _fetch_track_info_simple_uncached (2 request × 5s mỗi lần)."""
    key = (query or "").strip().lower()
    now = _time.time()
    hit = _track_info_cache.get(key)
    if hit and now - hit[0] < _TRACK_INFO_CACHE_TTL:
        return hit[1]
    if len(_track_info_cache) > _TRACK_INFO_CACHE_MAX:
        _track_info_cache.clear()

    info = _fetch_track_info_simple_uncached(query)
    # Chỉ cache kết quả có URL thật (không cache lỗi/rỗng để lần sau còn thử lại).
    if info and info.get("webpage_url"):
        _track_info_cache[key] = (now, info)
    return info

def _fetch_track_info_simple_uncached(query: str) -> dict:
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
        logger.warning("Lỗi lấy metadata bài hát: %s", e)

    return {
        "title": "Video YouTube" if query.startswith("http") else query[:50] + "...",
        "url": "",
        "duration": -1,
        "webpage_url": webpage_url or query,
        "thumbnail": "",
        "uploader": "Unknown"
    }

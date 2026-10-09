"""
extensions.py — Hạ tầng dùng chung của dashboard: logging xoay vòng, rate-limit,
CSRF token và helper gọi Discord REST.

Tách từ `dashboard/app.py` (Giai đoạn 3.2). Module này KHÔNG import blueprint nào
để tránh vòng import: `app_factory` và mọi blueprint đều import từ đây.
"""

import os
import sys

_V2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import logging
import secrets
from logging.handlers import RotatingFileHandler

import requests
from flask import flash, jsonify, redirect, request, session, url_for

import config


logger = logging.getLogger("BotV2.Dashboard")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _log_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        _log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        os.makedirs(_log_dir, exist_ok=True)
        _file_handler = RotatingFileHandler(
            os.path.join(_log_dir, "dashboard.log"),
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        _file_handler.setFormatter(_log_fmt)
        logger.addHandler(_file_handler)
    except Exception as exc:  # lỗi setup log không được làm chết dashboard
        sys.stderr.write(f"Failed to setup RotatingFileHandler: {exc}\n")
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_log_fmt)
    logger.addHandler(_stream_handler)
    logger.propagate = False

def _discord_api(method: str, path: str, *, timeout: float = 10.0, headers: dict | None = None, **kwargs):
    """
    Gọi Discord REST API bằng bot token với timeout thống nhất, KHÔNG raise.

    Trả về response object (caller tự xử lý status) hoặc None nếu lỗi mạng.
    Trước đây mỗi route tự gọi requests.get/post/delete với timeout rải rác 5-10s
    → không thể thêm retry/backoff tập trung và rất dễ quên timeout.
    """
    try:
        hdrs = dict(headers or {})
        hdrs.setdefault("Authorization", f"Bot {config.TOKEN}")
        url = path if path.startswith("http") else f"{config.DISCORD_API_BASE}{path}"
        return requests.request(method, url, headers=hdrs, timeout=timeout, **kwargs)
    except Exception as e:
        logger.warning("Discord API %s %s lỗi: %s", method, path, e)
        return None

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    def _client_key():
        """Khóa rate-limit theo IP THẬT của người truy cập.

        zerynbot.id.vn chạy sau Cloudflare (Server: cloudflare + CF-RAY), và dashboard
        bind 127.0.0.1 nên cloudflared là peer duy nhất — nếu dùng get_remote_address()
        trần thì MỌI visitor toàn thế giới chung một bucket: 5/phút trên
        /admin/system/stepup biến thành self-DoS toàn cục và các giới hạn khác mất tác
        dụng. Cloudflare ghi đè CF-Connecting-IP bằng IP thật nên header này không thể
        được client gửi lên giả mạo. Chỉ tin khi BEHIND_PROXY=1.
        """
        from flask import request

        if getattr(config, "BEHIND_PROXY", False):
            ip = (request.headers.get("CF-Connecting-IP") or "").strip()
            if ip:
                return ip
        return get_remote_address()

    # KHÔNG truyền `app=` ở đây: limiter là singleton của extensions, còn app được
    # dựng trong `app_factory.create_app()` → gọi `limiter.init_app(app)` tại đó.
    # `default_limits` để trống là cố ý: /api/admin/telemetry và các endpoint poll
    # khác bị gọi vài giây một lần, một trần chung 200/giờ sẽ 429 chính dashboard.
    # Thay vào đó mỗi route nặng/nhạy cảm được decorate @limiter.limit tường minh.
    limiter = Limiter(
        key_func=_client_key,
        storage_uri=config.RATELIMIT_STORAGE_URI,
        default_limits=[],
        swallow_errors=True,        # lỗi storage không làm chết dashboard
    )
except ImportError:  # flask-limiter chưa cài → chạy không giới hạn (khuyến nghị cài đặt)
    class _NoopLimiter:
        """Fallback khi chưa cài flask-limiter: giữ đúng API để code gọi được."""

        def limit(self, *a, **k):
            def _decorator(f):
                return f
            return _decorator

        def init_app(self, *a, **k):
            return None

    limiter = _NoopLimiter()

_CSRF_SESSION_KEY = "_csrf_token"
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

def csrf_token() -> str:
    """Lấy (hoặc tạo) CSRF token của session hiện tại — dùng trong templates."""
    tok = session.get(_CSRF_SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = tok
    return tok

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
        return redirect(request.referrer or url_for("guild.home"))
    return None

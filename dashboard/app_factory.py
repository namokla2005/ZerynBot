"""
app_factory.py — Dựng Flask app cho dashboard (Giai đoạn 3.2).

Tách từ `dashboard/app.py`: file này chỉ còn cấu hình app + đăng ký blueprint,
toàn bộ route nằm trong `dashboard/blueprints/*`.

`create_app()` được viết dạng factory để test có thể dựng app riêng, nhưng vẫn
giữ `app = create_app()` ở cuối file để `from dashboard.app import app` (main.py)
và `import dashboard.app as dapp` (tests) chạy y như trước.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 encoding on stdout/stderr for Flask (tránh cp1252 trên Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:  # pragma: no cover — Python < 3.7
    pass

from datetime import timedelta

from flask import Flask

import config
import database as db
from i18n import i18n as i18n_manager, t, tr
from dashboard.api import api
from dashboard.blueprints import admin as admin_blueprint
from dashboard.blueprints import guild as guild_blueprint
from dashboard.blueprints import music as music_blueprint
from dashboard.blueprints import public as public_blueprint
from dashboard.blueprints import support as support_blueprint
from dashboard.extensions import _csrf_protect, csrf_token, logger, limiter


def inject_i18n():
    """Inject translation helpers và danh sách ngôn ngữ vào mọi Jinja2 template."""
    from flask import session

    page_lang = session.get("ui_lang", "vi")  # ui_lang: ngôn ngữ giao diện web (per-user)
    return {
        "t":                   lambda key, **kw: t(key, lang=page_lang, **kw),
        "tr":                  tr,
        "available_languages": i18n_manager.get_supported_languages(),
        "current_ui_lang":     page_lang,
    }


def create_app() -> Flask:
    """Tạo Flask app đã cấu hình đầy đủ (session, limiter, CSRF, i18n, blueprint)."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = config.FLASK_SECRET_KEY

    # ─── Session / Cookie hardening (P1.7) ─────────────────────────────────────
    app.config.update(
        SESSION_COOKIE_HTTPONLY=config.SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE=config.SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_LIFETIME_DAYS),
        # Dashboard chỉ nhận form/JSON vài KB; không đặt trần thì một request hàng
        # GB đủ làm nghẽn tiến trình 6GB đang chạy song song với bot.
        MAX_CONTENT_LENGTH=256 * 1024,
    )

    # ─── Rate limiting ─────────────────────────────────────────────────────────
    limiter.init_app(app)

    # ─── CSRF protection tự quản (P0.5) ────────────────────────────────────────
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(_csrf_protect)

    # ─── i18n cho template ─────────────────────────────────────────────────────
    app.context_processor(inject_i18n)

    # ─── Đọc IP thật khi chạy sau reverse proxy ────────────────────────────────
    if config.BEHIND_PROXY:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ─── Security Headers & Static Cache-Control ──────────────────────────────
    @app.after_request
    def set_security_and_cache_headers(response):
        # 1. Bảo mật: Chống MIME sniffing, clickjacking, rò rỉ referrer và XSS
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        csp = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "form-action 'self' https://discord.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "img-src 'self' data: https://cdn.discordapp.com https://discord.com https://*.discordapp.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers.setdefault("Content-Security-Policy", csp)

        # 2. Cache-Control: Tối ưu hóa Cloudflare Edge & Browser Caching
        from flask import request
        path = request.path or ""
        if path.startswith("/static/"):
            if any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".ico", ".svg", ".woff2", ".ttf")):
                response.headers["Cache-Control"] = "public, max-age=86400"
            elif any(path.endswith(ext) for ext in (".css", ".js")):
                response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        return response

    # ─── Template Filters ──────────────────────────────────────────────────────
    @app.template_filter("guild_icon_url")
    def guild_icon_url_filter(guild):
        if not isinstance(guild, dict):
            return None
        if guild.get("icon_url"):
            return guild["icon_url"]
        from dashboard.auth import get_guild_icon_url
        return get_guild_icon_url(guild.get("id"), guild.get("icon"))

    # ─── Blueprints ────────────────────────────────────────────────────────────
    # Endpoint sau khi tách có dạng `<blueprint>.<tên_hàm>`; URL giữ nguyên 100%.
    app.register_blueprint(api)
    app.register_blueprint(public_blueprint.bp)
    app.register_blueprint(guild_blueprint.bp)
    app.register_blueprint(music_blueprint.bp)
    app.register_blueprint(support_blueprint.bp)
    app.register_blueprint(admin_blueprint.bp)
    return app


app = create_app()


def run_dev_server() -> None:
    """Chạy dashboard bằng Werkzeug dev server (chỉ dùng khi phát triển cục bộ)."""
    db.init_db()
    dash_host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    dash_port = int(os.environ.get("DASHBOARD_PORT", "5000"))
    # P0.5: KHÔNG bật debug=True mặc định. Werkzeug debugger cho phép chạy code
    # tùy ý qua HTTP nếu bị lộ — chỉ bật khi thật sự cần gỡ lỗi cục bộ.
    _debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    if _debug:
        logger.warning("[SECURITY] FLASK_DEBUG=1 — Werkzeug debugger đang BẬT. Không dùng khi mở ra Internet!")
    app.run(host=dash_host, port=dash_port, debug=_debug)


if __name__ == "__main__":  # pragma: no cover
    run_dev_server()

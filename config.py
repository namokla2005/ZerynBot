"""
config.py — Shared configuration for bot and dashboard.
Both bot/ and dashboard/ add the parent (v2/) to sys.path, so this is importable from both.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Bot ───────────────────────────────────────────────────────────────────────
TOKEN: str          = os.getenv("DISCORD_TOKEN", "")
CLIENT_ID: int      = int(os.getenv("DISCORD_CLIENT_ID", 0) or 0)
CLIENT_SECRET: str  = os.getenv("DISCORD_CLIENT_SECRET", "")

_dev = os.getenv("DEV_GUILD_ID", "").strip()
DEV_GUILD_ID: int   = int(_dev) if _dev.isdigit() else 0

_owner = os.getenv("BOT_OWNER_ID", "").strip()
BOT_OWNER_ID: int   = int(_owner) if _owner.isdigit() else 0

GLOBAL_COOLDOWN: int = 3 # Giới hạn 3 giây/lệnh
WEBHOOK_LOG_URL: str = os.getenv("WEBHOOK_LOG_URL", "")
STATUS_WEBHOOK_URL: str = os.getenv("STATUS_WEBHOOK_URL", "")
BACKUP_DB_URL: str = os.getenv("BACKUP_DB", "") or os.getenv("BACKUP_WEBHOOK_URL", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ─── Dashboard ─────────────────────────────────────────────────────────────────
# P0.1 (security): KHÔNG fallback về chuỗi bí mật tĩnh/hardcoded.
# Nếu thiếu hoặc để giá trị mặc định của .env.example → tự sinh key ngẫu nhiên
# mỗi lần khởi động (an toàn; đánh đổi: mọi session bị đăng xuất sau khi restart
# dashboard cho tới khi user đặt FLASK_SECRET_KEY thật trong .env).
_INSECURE_DEFAULT_KEYS = {
    "",
    "dev-secret-key-change-me",
    "change_this_to_a_random_secret_key_32chars",
}

_secret = os.getenv("FLASK_SECRET_KEY", "").strip()
if _secret in _INSECURE_DEFAULT_KEYS:
    import secrets as _secrets
    import warnings as _warnings

    _secret = _secrets.token_hex(32)
    _warnings.warn(
        "[SECURITY] FLASK_SECRET_KEY chưa cấu hình (hoặc đang là giá trị mặc định)! "
        "Đang dùng key ngẫu nhiên tạm thời — hãy đặt FLASK_SECRET_KEY cố định trong .env "
        "để session không bị reset khi khởi động lại.",
        stacklevel=2,
    )
FLASK_SECRET_KEY: str = _secret

DASHBOARD_URL: str    = os.getenv("DASHBOARD_URL", "http://localhost:5000")
REDIRECT_URI: str     = os.getenv("REDIRECT_URI", "http://localhost:5000/callback")

# Session / Cookie hardening (P1.7)
SESSION_COOKIE_HTTPONLY: bool = True
SESSION_COOKIE_SAMESITE: str  = "Lax"
# Secure=True bắt buộc khi chạy HTTPS; tự suy ra từ DASHBOARD_URL, có thể ghi đè bằng env.
_cookie_secure_env = os.getenv("COOKIE_SECURE", "").strip().lower()
if _cookie_secure_env in ("1", "true", "yes"):
    SESSION_COOKIE_SECURE: bool = True
elif _cookie_secure_env in ("0", "false", "no"):
    SESSION_COOKIE_SECURE: bool = False
else:
    SESSION_COOKIE_SECURE: bool = DASHBOARD_URL.startswith("https://")

SESSION_LIFETIME_DAYS: int = 7
# Đặt "1"/"true" khi dashboard chạy sau reverse proxy (Nginx/Cloudflare) để Flask
# đọc đúng IP thật từ X-Forwarded-For. KHÔNG bật nếu không có proxy (nguy cơ giả IP).
BEHIND_PROXY: bool = os.getenv("BEHIND_PROXY", "").strip().lower() in ("1", "true", "yes")

# Rate limiting (P1.6) — định dạng flask-limiter
RATELIMIT_STORAGE_URI: str = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

# Discord OAuth2
OAUTH2_AUTH_URL   = "https://discord.com/api/oauth2/authorize"
OAUTH2_TOKEN_URL  = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE  = "https://discord.com/api/v10"
OAUTH2_SCOPES     = "identify guilds"

# ─── Embed colors (int for discord.py, hex str for dashboard) ──────────────────
COLOR_WELCOME  = 0x57F287
COLOR_GOODBYE  = 0xED4245
COLOR_INFO     = 0x5865F2
COLOR_PING     = 0xFEE75C
COLOR_AVATAR   = 0xEB459E
COLOR_ERROR    = 0xED4245
COLOR_SUCCESS  = 0x57F287
COLOR_WARNING  = 0xFEE75C


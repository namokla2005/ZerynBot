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
REDIS_URL: str       = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ─── Dashboard ─────────────────────────────────────────────────────────────────
FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")
DASHBOARD_URL: str    = os.getenv("DASHBOARD_URL", "http://localhost:5000")
REDIRECT_URI: str     = os.getenv("REDIRECT_URI", "http://localhost:5000/callback")

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

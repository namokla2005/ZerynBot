"""
app.py — Shim tương thích ngược của dashboard (Giai đoạn 3.2).

Sau khi tách, dashboard gồm:
    dashboard/app_factory.py      create_app() + đăng ký blueprint
    dashboard/extensions.py       logging, limiter, CSRF, _discord_api
    dashboard/web_helpers.py      decorator auth, helper context, cache metadata
    dashboard/blueprints/*.py     public · guild · music · support · admin

File này giữ nguyên các tên cũ (`app`, `limiter`, `logger`, `_discord_api`,
`login_required`, `fetch_track_info_simple`, `requests`, ...) để `main.py`,
conftest và toàn bộ test hiện có chạy không phải sửa.

Endpoint đã đổi sang namespace blueprint: `login` → `public.login`,
`home` → `guild.home`, `server_*` → `guild.server_*` (trừ `music.server_music`),
`admin_*` → `admin.admin_*`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force UTF-8 encoding on stdout/stderr for Flask (prevents cp1252 UnicodeEncodeError on Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:  # pragma: no cover — Python < 3.7
    pass

from datetime import datetime, timezone  # noqa: F401 — giữ cho code cũ import qua shim
import json  # noqa: F401
import secrets  # noqa: F401
import shlex  # noqa: F401
import sqlite3  # noqa: F401
import time as _time  # noqa: F401

import requests  # noqa: F401 — tests/test_dashboard_cache.py monkeypatch qua dashboard.app

from flask import (  # noqa: F401 — re-export cho code cũ
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import config  # noqa: F401
import database as db  # noqa: F401

from dashboard.app_factory import app, create_app, inject_i18n, run_dev_server  # noqa: F401
from dashboard.extensions import (  # noqa: F401
    _CSRF_METHODS,
    _CSRF_SESSION_KEY,
    _csrf_protect,
    _discord_api,
    csrf_token,
    limiter,
    logger,
)
from dashboard.web_helpers import (  # noqa: F401
    _TRACK_INFO_CACHE_MAX,
    _TRACK_INFO_CACHE_TTL,
    _fetch_track_info_simple_uncached,
    _get_guild_from_session,
    _refresh_guilds_if_stale,
    _safe_channel,
    _server_ctx,
    _track_info_cache,
    fetch_track_info_simple,
    guild_access_required,
    login_required,
)

__all__ = [
    "app",
    "create_app",
    "run_dev_server",
    "limiter",
    "logger",
    "_discord_api",
    "csrf_token",
    "_csrf_protect",
    "login_required",
    "guild_access_required",
    "fetch_track_info_simple",
]


if __name__ == "__main__":  # pragma: no cover — `python dashboard/app.py`
    run_dev_server()

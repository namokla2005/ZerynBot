"""
guilds.py — Lõi cấu hình guild: settings, module bật/tắt, cache kênh/role, meta,
thống kê, ngôn ngữ, blacklist và global setting.

Tách từ `database.py` (Giai đoạn 3.3).
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from cache import cache

from .conn import _connect_async, _connect_sync, _row_to_dict, get_db_connection, get_db_path

logger = logging.getLogger("ZerynBot.Database")

DEFAULT_MODULES = [
    "welcome_goodbye", "autoroles", "leveling", "utility", "info",
    "music", "tickets", "reactionroles", "automods", "logger",
    "giveaways", "economy", "tempvoice", "customcommands", "ai", "remind",
    "moderation", "fun", "birthday", "verify"
]

_DEFAULT_SETTINGS = {
    "welcome_channel_id":  None,
    "welcome_message":     "Xin chào {user}, chào mừng đến với **{server}**! 🎉",
    "welcome_use_embed":   1,
    "welcome_embed_color": "#57F287",
    "welcome_embed_title": "🎉 Chào mừng thành viên mới!",
    "welcome_bg_url":      "",
    "goodbye_channel_id":  None,
    "goodbye_message":     "Tạm biệt **{user_name}**, chúc bạn nhiều may mắn! 👋",
    "goodbye_use_embed":   1,
    "goodbye_embed_color": "#ED4245",
    "goodbye_embed_title": "👋 Tạm biệt!",
    "goodbye_bg_url":      "",
    "autoroles_enabled":   0,
    "autoroles_user":      "[]",
    "autoroles_bot":       "[]",
    "language":            "vi",
}

def get_guild_settings(guild_id: str) -> Dict:
    cache_key = f"settings:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    
    result = {"guild_id": guild_id, **_DEFAULT_SETTINGS}
    if row:
        result = _row_to_dict(row)
        
    cache.set(cache_key, result, ttl=300)
    return result

def upsert_guild(guild_id: str, **fields):
    """Insert or update specific guild settings columns."""
    if not fields:
        return
    with _connect_sync() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (guild_id,)
        )
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE guilds SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
            [*fields.values(), guild_id],
        )
        conn.commit()
    cache.delete(f"settings:{guild_id}")

def get_guild_modules(guild_id: str) -> Dict[str, bool]:
    cache_key = f"modules:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with _connect_sync() as conn:
        rows = conn.execute(
            "SELECT module_name, enabled FROM guild_modules WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    result = {m: True for m in DEFAULT_MODULES}
    for module_name, enabled in rows:
        result[module_name] = bool(enabled)
        
    cache.set(cache_key, result, ttl=300)
    return result

def set_module(guild_id: str, module_name: str, enabled: bool):
    with _connect_sync() as conn:
        conn.execute(
            """INSERT INTO guild_modules (guild_id, module_name, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, module_name) DO UPDATE SET enabled = excluded.enabled""",
            (guild_id, module_name, int(enabled)),
        )
        conn.commit()
    cache.delete(f"modules:{guild_id}")

def get_guild_channels(guild_id: str) -> List[Dict]:
    """Return cached text channels (type=0) for a guild."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 0 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_categories(guild_id: str) -> List[Dict]:
    """Return cached category channels (type=4) for a guild."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 4 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_voice_channels(guild_id: str) -> List[Dict]:
    """Return cached voice channels (type=2) for a guild."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 2 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_roles(guild_id: str) -> List[Dict]:
    """Return cached roles for a guild."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_roles WHERE guild_id = ? ORDER BY position DESC",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_meta(guild_id: str) -> Optional[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guild_meta WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def get_bot_guild_ids() -> List[str]:
    """Return list of guild IDs the bot is currently in (from cache)."""
    with _connect_sync() as conn:
        rows = conn.execute("SELECT guild_id FROM guild_meta").fetchall()
    return [r[0] for r in rows]

def get_top_users(guild_id: str, limit: int = 10) -> list:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM user_levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?", 
            (guild_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

async def async_get_guild_settings(guild_id: str) -> dict:
    cache_key = f"settings:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    result = dict(row) if row else {"guild_id": guild_id, **_DEFAULT_SETTINGS}
    await cache.aset(cache_key, result, ttl=300)
    return result

async def async_increment_stat(guild_id: str, event_type: str, event_label: str, amount: int = 1):
    """
    Increment a stat counter for a specific event and label.
    Aggregated by current hour (YYYY-MM-DD HH:00:00).
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    date_hour = now.strftime("%Y-%m-%d %H:00:00")
    
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO guild_stats (guild_id, event_type, event_label, date_hour, count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, event_type, event_label, date_hour) 
            DO UPDATE SET count = count + ?
        """, (guild_id, event_type, event_label, date_hour, amount, amount))
        await db.commit()

def get_guild_stats(guild_id: str, days: int = 7) -> list:
    """
    Get all stats for a guild within the last N days.
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    start_date = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
    
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT event_type, event_label, date_hour, count 
            FROM guild_stats 
            WHERE guild_id = ? AND date_hour >= ?
            ORDER BY date_hour ASC
        """, (guild_id, start_date))
        return [_row_to_dict(row) for row in cur.fetchall()]

async def async_is_module_enabled(guild_id: str, module_name: str) -> bool:
    # Đọc cả dict modules (đã được cache ở get_guild_modules / set_module) để tận dụng
    # cache key "modules:{guild_id}" dùng chung giữa sync (dashboard) và async (bot).
    modules = await async_get_guild_modules(guild_id)
    return modules.get(module_name, True)  # Default: enabled

async def async_get_guild_modules(guild_id: str) -> Dict[str, bool]:
    cache_key = f"modules:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with _connect_async() as db:
        async with db.execute(
            "SELECT module_name, enabled FROM guild_modules WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
    result = {m: True for m in DEFAULT_MODULES}
    for module_name, enabled in rows:
        result[module_name] = bool(enabled)
    await cache.aset(cache_key, result, ttl=300)
    return result

async def async_cache_guild(guild_id: str, name: str, icon: Optional[str], member_count: int):
    async with _connect_async() as db:
        await db.execute(
            """INSERT INTO guild_meta (guild_id, guild_name, guild_icon, member_count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 guild_name=excluded.guild_name,
                 guild_icon=excluded.guild_icon,
                 member_count=excluded.member_count,
                 updated_at=CURRENT_TIMESTAMP""",
            (guild_id, name, icon, member_count),
        )
        await db.commit()

async def async_remove_guild(guild_id: str):
    async with _connect_async() as db:
        await db.execute("DELETE FROM guild_meta WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def async_cache_channels(guild_id: str, channels: List[Dict]):
    async with _connect_async() as db:
        await db.execute("DELETE FROM guild_channels WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_channels (guild_id, channel_id, channel_name, channel_type) VALUES (?, ?, ?, ?)",
            [(guild_id, ch["id"], ch["name"], ch["type"]) for ch in channels],
        )
        await db.commit()

async def async_cache_roles(guild_id: str, roles: List[Dict]):
    async with _connect_async() as db:
        await db.execute("DELETE FROM guild_roles WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_roles (guild_id, role_id, role_name, color_hex, position) VALUES (?, ?, ?, ?, ?)",
            [(guild_id, r["id"], r["name"], r["color_hex"], r["position"]) for r in roles],
        )
        await db.commit()

def set_guild_language(guild_id: str, language: str) -> None:
    """
    Set guild language — sync version for Flask Dashboard.
    Delegates to upsert_guild and auto-invalidates the settings cache.
    """
    upsert_guild(guild_id, language=language)

async def async_set_guild_language(guild_id: str, language: str) -> None:
    """
    Set guild language — async version for Discord Bot.
    Uses asyncio.to_thread so it never blocks the event loop.
    """
    import asyncio
    await asyncio.to_thread(upsert_guild, guild_id, language=language)
    # Invalidate Redis/memory cache so bot picks up the change immediately
    await cache.adelete(f"settings:{guild_id}")

def get_global_setting(key: str, default: str = "") -> str:
    """Sync — Get a global bot configuration setting."""
    cache_key = f"global_setting:{key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    with _connect_sync() as conn:
        row = conn.execute("SELECT value FROM bot_global_settings WHERE key = ?", (key,)).fetchone()
        val = str(row[0]) if row and row[0] is not None else default
        cache.set(cache_key, val, ttl=300)
        return val

def set_global_setting(key: str, value: str) -> None:
    """Sync — Save a global bot configuration setting."""
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO bot_global_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
    cache.delete(f"global_setting:{key}")

async def async_get_global_setting(key: str, default: str = "") -> str:
    """Async — Get a global bot configuration setting."""
    cache_key = f"global_setting:{key}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached
    async with _connect_async() as db:
        async with db.execute("SELECT value FROM bot_global_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            val = str(row[0]) if row and row[0] is not None else default
            await cache.aset(cache_key, val, ttl=300)
            return val

def get_blacklist() -> List[Dict]:
    """Return all blacklisted guilds."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_blacklist ORDER BY kicked_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist."""
    with _connect_sync() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO guild_blacklist (guild_id, guild_name, reason)
            VALUES (?, ?, ?)
            """,
            (guild_id, guild_name, reason),
        )
        conn.commit()

def remove_from_blacklist(guild_id: str):
    """Remove a guild from the blacklist."""
    with _connect_sync() as conn:
        conn.execute("DELETE FROM guild_blacklist WHERE guild_id = ?", (guild_id,))
        conn.commit()

def is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (sync)."""
    with _connect_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return row is not None

async def async_is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (async)."""
    async with _connect_async() as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
    return row is not None

async def async_add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist (async)."""
    async with _connect_async() as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO guild_blacklist (guild_id, guild_name, reason)
            VALUES (?, ?, ?)
            """,
            (guild_id, guild_name, reason),
        )
        await conn.commit()

set_module_enabled = set_module

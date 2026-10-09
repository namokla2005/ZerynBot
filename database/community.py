"""
community.py — Logger, automod, verify gate, cảnh cáo moderation và custom commands.

Tách từ `database.py` (Giai đoạn 3.3).
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from cache import SETTINGS_TTL, cache

from .conn import _connect_async, _connect_sync, _row_to_dict, get_db_connection, get_db_path

logger = logging.getLogger("ZerynBot.Database")

_DEFAULT_AUTOMOD = {
    "bad_words": "[]",
    "blacklist_links": "[]",
    "whitelist_links": "[]",
    "spam_enabled": 0,
    "bad_words_enabled": 0,
    "links_enabled": 0,
    "anti_invite_enabled": 0,
    "anti_caps_enabled": 0,
    "anti_mentions_enabled": 0,
    "max_mentions": 5,
    "timeout_duration_minutes": 5,
    "notify_role_id": None,
    "log_channel_id": None,
    "immune_roles": "[]",
    "spam_allowed_channels": "[]",
    "anti_raid_enabled": 0,
    "raid_join_per_window": 5,
    "raid_action": "lockdown",
    "anti_nuke_enabled": 0,
    "nuke_actions": "[\"channel_delete\",\"role_delete\",\"guild_update\"]",
    "raid_locked": 0,
    "raid_snapshot": "[]"
}

_DEFAULT_VERIFY = {
    "guild_id": None,
    "enabled": 0,
    "channel_id": None,
    "verified_role_id": None,
    "pending_role_id": None,
    "verify_text": "Chào mừng đến với **{server}**! Bấm nút bên dưới để xác thực.",
    "button_label": "Tôi đã đọc nội quy & Xác thực",
    "log_channel_id": None,
    "hide_channels": 1,
    "saved_overrides": "[]",
}

_CUSTOM_CMDS_TTL = 60

def get_logger_settings(guild_id: str) -> dict:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT * FROM logger_settings WHERE guild_id = ?
        """, (guild_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "log_channel_id": "",
            "log_message_edit": 1,
            "log_message_delete": 1,
            "log_member_join_leave": 1,
            "log_member_kick_ban": 1,
            "log_member_role_change": 1,
            "log_channel_change": 1,
            "log_role_change": 1,
            "log_automod": 1,
            "log_ticket": 1
        }

def set_logger_settings(guild_id: str, settings: dict):
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO logger_settings (
                guild_id, log_channel_id, log_message_edit, log_message_delete,
                log_member_join_leave, log_member_kick_ban, log_member_role_change,
                log_channel_change, log_role_change, log_automod, log_ticket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                log_channel_id=excluded.log_channel_id,
                log_message_edit=excluded.log_message_edit,
                log_message_delete=excluded.log_message_delete,
                log_member_join_leave=excluded.log_member_join_leave,
                log_member_kick_ban=excluded.log_member_kick_ban,
                log_member_role_change=excluded.log_member_role_change,
                log_channel_change=excluded.log_channel_change,
                log_role_change=excluded.log_role_change,
                log_automod=excluded.log_automod,
                log_ticket=excluded.log_ticket
        """, (
            guild_id,
            settings.get("log_channel_id", ""),
            settings.get("log_message_edit", 1),
            settings.get("log_message_delete", 1),
            settings.get("log_member_join_leave", 1),
            settings.get("log_member_kick_ban", 1),
            settings.get("log_member_role_change", 1),
            settings.get("log_channel_change", 1),
            settings.get("log_role_change", 1),
            settings.get("log_automod", 1),
            settings.get("log_ticket", 1)
        ))
        conn.commit()
    cache.delete(f"logger_settings:{guild_id}")

async def async_get_logger_settings(guild_id: str) -> dict:
    cache_key = f"logger_settings:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM logger_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    if row:
        result = dict(row)
    else:
        result = {
            "guild_id": guild_id,
            "log_channel_id": "",
            "log_message_edit": 1,
            "log_message_delete": 1,
            "log_member_join_leave": 1,
            "log_member_kick_ban": 1,
            "log_member_role_change": 1,
            "log_channel_change": 1,
            "log_role_change": 1,
            "log_automod": 1,
            "log_ticket": 1
        }
    await cache.aset(cache_key, result, ttl=SETTINGS_TTL)
    return result

def get_automod_settings(guild_id: str) -> dict:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        if row:
            res = _row_to_dict(row)
            res["bad_words"] = json.loads(res.get("bad_words") or "[]")
            res["blacklist_links"] = json.loads(res.get("blacklist_links") or "[]")
            res["whitelist_links"] = json.loads(res.get("whitelist_links") or "[]")
            res["immune_roles"] = json.loads(res.get("immune_roles") or "[]")
            res["spam_allowed_channels"] = json.loads(res.get("spam_allowed_channels") or "[]")
            res["nuke_actions"] = json.loads(res.get("nuke_actions") or "[\"channel_delete\",\"role_delete\",\"guild_update\"]")
            res["raid_snapshot"] = json.loads(res.get("raid_snapshot") or "[]")
            return res
        res = dict(_DEFAULT_AUTOMOD)
        res["nuke_actions"] = json.loads(res.get("nuke_actions") or "[\"channel_delete\",\"role_delete\",\"guild_update\"]")
        res["raid_snapshot"] = json.loads(res.get("raid_snapshot") or "[]")
        return res

def upsert_automod_settings(guild_id: str, **kwargs):
    s = get_automod_settings(guild_id)
    s.update(kwargs)
    bad_words = json.dumps(s.get("bad_words", [])) if isinstance(s.get("bad_words"), list) else s.get("bad_words", "[]")
    blacklist_links = json.dumps(s.get("blacklist_links", [])) if isinstance(s.get("blacklist_links"), list) else s.get("blacklist_links", "[]")
    whitelist_links = json.dumps(s.get("whitelist_links", [])) if isinstance(s.get("whitelist_links"), list) else s.get("whitelist_links", "[]")
    immune_roles = json.dumps(s.get("immune_roles", [])) if isinstance(s.get("immune_roles"), list) else s.get("immune_roles", "[]")
    spam_allowed_channels = json.dumps(s.get("spam_allowed_channels", [])) if isinstance(s.get("spam_allowed_channels"), list) else s.get("spam_allowed_channels", "[]")
    nuke_actions = json.dumps(s.get("nuke_actions", ["channel_delete","role_delete","guild_update"])) if isinstance(s.get("nuke_actions"), list) else s.get("nuke_actions", "[\"channel_delete\",\"role_delete\",\"guild_update\"]")
    raid_snapshot = json.dumps(s.get("raid_snapshot", [])) if isinstance(s.get("raid_snapshot"), list) else s.get("raid_snapshot", "[]")

    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO automod_settings (
                guild_id, bad_words, blacklist_links, whitelist_links, 
                spam_enabled, bad_words_enabled, links_enabled,
                anti_invite_enabled, anti_caps_enabled, anti_mentions_enabled,
                max_mentions, timeout_duration_minutes,
                notify_role_id, log_channel_id,
                immune_roles, spam_allowed_channels,
                anti_raid_enabled, raid_join_per_window, raid_action,
                anti_nuke_enabled, nuke_actions, raid_locked, raid_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                bad_words=excluded.bad_words,
                blacklist_links=excluded.blacklist_links,
                whitelist_links=excluded.whitelist_links,
                spam_enabled=excluded.spam_enabled,
                bad_words_enabled=excluded.bad_words_enabled,
                links_enabled=excluded.links_enabled,
                anti_invite_enabled=excluded.anti_invite_enabled,
                anti_caps_enabled=excluded.anti_caps_enabled,
                anti_mentions_enabled=excluded.anti_mentions_enabled,
                max_mentions=excluded.max_mentions,
                timeout_duration_minutes=excluded.timeout_duration_minutes,
                notify_role_id=excluded.notify_role_id,
                log_channel_id=excluded.log_channel_id,
                immune_roles=excluded.immune_roles,
                spam_allowed_channels=excluded.spam_allowed_channels,
                anti_raid_enabled=excluded.anti_raid_enabled,
                raid_join_per_window=excluded.raid_join_per_window,
                raid_action=excluded.raid_action,
                anti_nuke_enabled=excluded.anti_nuke_enabled,
                nuke_actions=excluded.nuke_actions,
                raid_locked=excluded.raid_locked,
                raid_snapshot=excluded.raid_snapshot
        """, (
            guild_id, bad_words, blacklist_links, whitelist_links,
            int(s.get("spam_enabled", 0)), int(s.get("bad_words_enabled", 0)), int(s.get("links_enabled", 0)),
            int(s.get("anti_invite_enabled", 0)), int(s.get("anti_caps_enabled", 0)), int(s.get("anti_mentions_enabled", 0)),
            int(s.get("max_mentions", 5)), int(s.get("timeout_duration_minutes", 5)),
            s.get("notify_role_id"), s.get("log_channel_id"),
            immune_roles, spam_allowed_channels,
            int(s.get("anti_raid_enabled", 0)), int(s.get("raid_join_per_window", 5)),
            s.get("raid_action", "lockdown"), int(s.get("anti_nuke_enabled", 0)),
            nuke_actions, int(s.get("raid_locked", 0)), raid_snapshot
        ))
        conn.commit()

async def async_get_automod_settings(guild_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                res = dict(row)
                res["bad_words"] = json.loads(res.get("bad_words") or "[]")
                res["blacklist_links"] = json.loads(res.get("blacklist_links") or "[]")
                res["whitelist_links"] = json.loads(res.get("whitelist_links") or "[]")
                res["immune_roles"] = json.loads(res.get("immune_roles") or "[]")
                res["spam_allowed_channels"] = json.loads(res.get("spam_allowed_channels") or "[]")
                res["nuke_actions"] = json.loads(res.get("nuke_actions") or "[\"channel_delete\",\"role_delete\",\"guild_update\"]")
                res["raid_snapshot"] = json.loads(res.get("raid_snapshot") or "[]")
                res["raid_locked"] = int(res.get("raid_locked") or 0)
                return res
            res = dict(_DEFAULT_AUTOMOD)
            res["nuke_actions"] = json.loads(res.get("nuke_actions") or "[\"channel_delete\",\"role_delete\",\"guild_update\"]")
            res["raid_snapshot"] = json.loads(res.get("raid_snapshot") or "[]")
            res["raid_locked"] = int(res.get("raid_locked") or 0)
            return res

async def async_update_automod_settings(guild_id: str, **fields) -> None:
    """Async — Cập nhật các cột nhất định của automod_settings (dùng cho bot cog)."""
    if not fields:
        return
    allow = {
        "anti_raid_enabled", "raid_join_per_window", "raid_action",
        "anti_nuke_enabled", "nuke_actions", "raid_locked", "raid_snapshot",
    }
    set_clause = ", ".join(f"{k} = ?" for k in fields if k in allow)
    if not set_clause:
        return
    # Với các cột JSON được truyền dạng list, đưa về chuỗi JSON
    params = []
    for k in fields:
        if k not in allow:
            continue
        v = fields[k]
        if k in ("nuke_actions", "raid_snapshot") and isinstance(v, list):
            v = json.dumps(v, ensure_ascii=False)
        elif k in ("anti_raid_enabled", "anti_nuke_enabled", "raid_locked"):
            v = int(v)
        params.append(v)
    async with _connect_async() as db:
        await db.execute(
            f"UPDATE automod_settings SET {set_clause} WHERE guild_id = ?",
            (*params, guild_id),
        )
        await db.commit()

async def async_add_automod_warning(guild_id: str, user_id: str) -> int:
    """Returns the total number of warnings the user has in the last 24 hours (including this one)."""
    async with _connect_async() as db:
        # Delete warnings older than 24h for all users in this guild (cleanup)
        await db.execute("DELETE FROM automod_warnings WHERE guild_id = ? AND created_at <= datetime('now', '-1 day')", (guild_id,))
        
        # Add new warning
        await db.execute("INSERT INTO automod_warnings (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
        
        # Get count
        async with db.execute("SELECT COUNT(*) FROM automod_warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 1
            
        await db.commit()
        return count

async def async_clear_automod_warnings(guild_id: str, user_id: str):
    async with _connect_async() as db:
        await db.execute("DELETE FROM automod_warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()

def get_verify_settings(guild_id: str) -> dict:
    """Sync — Get verify settings for dashboard."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM verify_settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row:
        return _row_to_dict(row)
    return {"guild_id": guild_id, **_DEFAULT_VERIFY}

def upsert_verify_settings(guild_id: str, **fields) -> None:
    """Sync — Insert or update verify settings."""
    if not fields:
        return
    with _connect_sync() as conn:
        conn.execute("INSERT OR IGNORE INTO verify_settings (guild_id) VALUES (?)", (guild_id,))
        allow = {
            "enabled", "channel_id", "verified_role_id", "pending_role_id",
            "verify_text", "button_label", "log_channel_id", "hide_channels",
            "saved_overrides",
        }
        set_clause = ", ".join(f"{k} = ?" for k in fields if k in allow)
        if set_clause:
            params = [fields[k] for k in fields if k in allow]
            conn.execute(
                f"UPDATE verify_settings SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
                (*params, guild_id),
            )
        conn.commit()

async def async_get_verify_settings(guild_id: str) -> dict:
    """Async — Get verify settings for Discord bot."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM verify_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
    return {"guild_id": guild_id, **_DEFAULT_VERIFY}

async def async_upsert_verify_settings(guild_id: str, **fields) -> None:
    """Async — Insert or update verify settings."""
    if not fields:
        return
    async with _connect_async() as db:
        await db.execute("INSERT OR IGNORE INTO verify_settings (guild_id) VALUES (?)", (guild_id,))
        allow = {
            "enabled", "channel_id", "verified_role_id", "pending_role_id",
            "verify_text", "button_label", "log_channel_id", "hide_channels",
            "saved_overrides",
        }
        set_clause = ", ".join(f"{k} = ?" for k in fields if k in allow)
        if set_clause:
            params = [fields[k] for k in fields if k in allow]
            await db.execute(
                f"UPDATE verify_settings SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
                (*params, guild_id),
            )
        await db.commit()

async def async_add_mod_warning(guild_id: str, user_id: str, mod_id: str, reason: str) -> int:
    """Add a moderation warning. Returns the new warning ID."""
    async with _connect_async() as db:
        cur = await db.execute("""
            INSERT INTO mod_warnings (guild_id, user_id, mod_id, reason)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, reason))
        await db.commit()
        return cur.lastrowid

async def async_get_mod_warnings(guild_id: str, user_id: str) -> list:
    """Get all active warnings for a user in a guild."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mod_warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def async_count_mod_warnings(guild_id: str, user_id: str) -> int:
    """Count total warnings for a user."""
    async with _connect_async() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM mod_warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def async_delete_mod_warning(warning_id: int, guild_id: str) -> bool:
    """Delete a warning by ID. Returns True if deleted."""
    async with _connect_async() as db:
        cur = await db.execute(
            "DELETE FROM mod_warnings WHERE id = ? AND guild_id = ?",
            (warning_id, guild_id),
        )
        await db.commit()
        return cur.rowcount > 0

def get_mod_warnings_count_sync(guild_id: str) -> int:
    """Sync — count total warnings in guild (for dashboard)."""
    with _connect_sync() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM mod_warnings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row[0] if row else 0

def get_custom_commands(guild_id: str) -> list:
    """Sync — List all custom commands for dashboard."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM custom_commands WHERE guild_id = ? ORDER BY id DESC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]

def get_custom_command(cmd_id: int, guild_id: str) -> dict | None:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id)).fetchone()
        return _row_to_dict(row) if row else None

def add_custom_command(guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, creator_id: str = "") -> int:
    with _connect_sync() as conn:
        cursor = conn.execute("""
            INSERT INTO custom_commands (guild_id, trigger, match_type, response_text, embed_json, is_enabled, uses_count, creator_id)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?)
        """, (guild_id, trigger.strip().lower(), match_type, response_text, embed_json, creator_id))
        conn.commit()
        lastrowid = cursor.lastrowid
    invalidate_custom_commands_cache(guild_id)
    return lastrowid

def update_custom_command(cmd_id: int, guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, is_enabled: int = 1) -> None:
    with _connect_sync() as conn:
        conn.execute("""
            UPDATE custom_commands
            SET trigger = ?, match_type = ?, response_text = ?, embed_json = ?, is_enabled = ?
            WHERE id = ? AND guild_id = ?
        """, (trigger.strip().lower(), match_type, response_text, embed_json, is_enabled, cmd_id, guild_id))
        conn.commit()
    invalidate_custom_commands_cache(guild_id)

def delete_custom_command(cmd_id: int, guild_id: str) -> None:
    with _connect_sync() as conn:
        conn.execute("DELETE FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id))
        conn.commit()
    invalidate_custom_commands_cache(guild_id)

def _custom_cmds_cache_key(guild_id: str) -> str:
    return f"customcmds:{guild_id}"

def invalidate_custom_commands_cache(guild_id: str) -> None:
    """Xoá cache custom commands của một guild (gọi từ mọi đường ghi)."""
    try:
        cache.delete(_custom_cmds_cache_key(guild_id))
    except Exception as exc:
        logger.debug(f"[Cache] invalidate custom commands error: {exc}")

async def async_get_custom_commands(guild_id: str) -> list:
    """Danh sách custom command đang bật của guild (có cache 60 giây)."""
    key = _custom_cmds_cache_key(guild_id)
    try:
        cached = await cache.aget(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_commands WHERE guild_id = ? AND is_enabled = 1", (guild_id,)) as cur:
            rows = await cur.fetchall()
            result = [dict(r) for r in rows]

    try:
        await cache.aset(key, result, ttl=_CUSTOM_CMDS_TTL)
    except Exception as exc:
        logger.debug(f"[Cache] set custom commands error: {exc}")
    return result

async def async_find_custom_command(guild_id: str, message_content: str) -> dict | None:
    """Find matching custom command (exact, contains, startswith)."""
    text = message_content.strip().lower()
    commands = await async_get_custom_commands(guild_id)
    for cmd in commands:
        trigger = cmd["trigger"].lower()
        mtype = cmd.get("match_type", "exact")
        if mtype == "exact" and text == trigger:
            return cmd
        elif mtype == "startswith" and text.startswith(trigger):
            return cmd
        elif mtype == "contains" and trigger in text:
            return cmd
    return None

async def async_add_custom_command(guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, creator_id: str = "") -> int:
    async with _connect_async() as db:
        cursor = await db.execute("""
            INSERT INTO custom_commands (guild_id, trigger, match_type, response_text, embed_json, is_enabled, uses_count, creator_id)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?)
        """, (guild_id, trigger.strip().lower(), match_type, response_text, embed_json, creator_id))
        await db.commit()
        lastrowid = cursor.lastrowid
    await cache.adelete(_custom_cmds_cache_key(guild_id))
    return lastrowid

async def async_delete_custom_command(cmd_id: int, guild_id: str) -> None:
    async with _connect_async() as db:
        await db.execute("DELETE FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id))
        await db.commit()
    await cache.adelete(_custom_cmds_cache_key(guild_id))

async def async_increment_custom_command_usage(cmd_id: int) -> None:
    async with _connect_async() as db:
        await db.execute("UPDATE custom_commands SET uses_count = uses_count + 1 WHERE id = ?", (cmd_id,))
        await db.commit()

async def async_count_user_custom_commands(guild_id: str, user_id: str) -> int:
    """Đếm số lượng lệnh tùy biến do một người dùng cụ thể tạo ra trong guild."""
    async with _connect_async() as db:
        async with db.execute("SELECT COUNT(*) FROM custom_commands WHERE guild_id = ? AND creator_id = ?", (guild_id, user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def async_count_guild_custom_commands(guild_id: str) -> int:
    """Đếm tổng số lượng lệnh tùy biến trong toàn guild."""
    async with _connect_async() as db:
        async with db.execute("SELECT COUNT(*) FROM custom_commands WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

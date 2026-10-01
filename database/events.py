"""
events.py — Giveaway, nhắc hẹn, kết hôn/tương tác fun, sinh nhật, phòng voice tạm.

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

async def async_create_giveaway(guild_id: str, channel_id: str, message_id: str, host_id: str, prize: str, winners_count: int, end_at: int, req_role_id: str = None, req_account_age_days: int = 0):
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days))
        await db.commit()

async def async_get_giveaway(message_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def async_update_giveaway(message_id: str, participants_json: str = None, ended: int = None):
    async with _connect_async() as db:
        if participants_json is not None and ended is not None:
            await db.execute("UPDATE giveaways SET participants_json = ?, ended = ? WHERE message_id = ?", (participants_json, ended, message_id))
        elif participants_json is not None:
            await db.execute("UPDATE giveaways SET participants_json = ? WHERE message_id = ?", (participants_json, message_id))
        elif ended is not None:
            await db.execute("UPDATE giveaways SET ended = ? WHERE message_id = ?", (ended, message_id))
        await db.commit()

async def async_get_active_giveaways() -> list:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE ended = 0") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def async_add_reminder(user_id: str, guild_id: str, channel_id: str, reason: str, remind_at: int) -> int:
    """Add a new reminder for user."""
    async with _connect_async() as db:
        cur = await db.execute("""
            INSERT INTO reminders (user_id, guild_id, channel_id, reason, remind_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, channel_id, reason, remind_at))
        await db.commit()
        return cur.lastrowid

async def async_get_due_reminders(now_ts: int) -> list:
    """Fetch all reminders that are due to be triggered (remind_at <= now_ts)."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM reminders WHERE remind_at <= ? ORDER BY remind_at ASC LIMIT 50", (now_ts,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def async_delete_reminder(reminder_id: int):
    """Delete a reminder by ID after triggering or user cancellation."""
    async with _connect_async() as db:
        await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()

async def async_get_user_reminders(user_id: str, guild_id: str = None) -> list:
    """Fetch active upcoming reminders for a user."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        if guild_id:
            query = "SELECT * FROM reminders WHERE user_id = ? AND guild_id = ? ORDER BY remind_at ASC LIMIT 20"
            params = (user_id, guild_id)
        else:
            query = "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC LIMIT 20"
            params = (user_id,)
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def async_get_marriage(guild_id: str, user_id: str) -> dict | None:
    """Get the marriage record for a user (either as user1 or user2)."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_marriages WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (guild_id, user_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def async_create_marriage(guild_id: str, user1_id: str, user2_id: str) -> int:
    """Create a marriage between two users. Returns the new ID."""
    async with _connect_async() as db:
        cur = await db.execute("""
            INSERT INTO user_marriages (guild_id, user1_id, user2_id)
            VALUES (?, ?, ?)
        """, (guild_id, user1_id, user2_id))
        await db.commit()
        return cur.lastrowid

async def async_delete_marriage(guild_id: str, user_id: str) -> bool:
    """Delete a marriage involving user_id."""
    async with _connect_async() as db:
        cur = await db.execute(
            "DELETE FROM user_marriages WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (guild_id, user_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0

async def async_add_love_points(guild_id: str, user_id: str, points: int = 1):
    """Increment love_points for a marriage."""
    async with _connect_async() as db:
        await db.execute(
            "UPDATE user_marriages SET love_points = love_points + ? WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (points, guild_id, user_id, user_id),
        )
        await db.commit()

def get_marriages_count_sync(guild_id: str) -> int:
    """Sync — count marriages in guild (for dashboard)."""
    with _connect_sync() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_marriages WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row[0] if row else 0

async def async_increment_fun_interaction(guild_id: str, user_id: str, target_id: str, action: str) -> int:
    """Tăng số lần tương tác giữa user và target cho một action. Trả về số mới.

    `last_used` được cập nhật trong cùng câu lệnh để `async_prune_old_data` có thể
    dọn các tương tác cũ (bảng này chỉ đếm "gần đây").
    """
    now = time.time()
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO fun_interactions (guild_id, user_id, target_id, action, count, last_used)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, target_id, action)
            DO UPDATE SET count = count + 1, last_used = excluded.last_used
        """, (guild_id, user_id, target_id, action, now))
        await db.commit()
        async with db.execute("""
            SELECT count FROM fun_interactions
            WHERE guild_id = ? AND user_id = ? AND target_id = ? AND action = ?
        """, (guild_id, user_id, target_id, action)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 1

async def async_get_fun_interaction_count(guild_id: str, user_id: str, target_id: str, action: str) -> int:
    """Get interaction count between user and target for a given action."""
    async with _connect_async() as db:
        async with db.execute("""
            SELECT count FROM fun_interactions
            WHERE guild_id = ? AND user_id = ? AND target_id = ? AND action = ?
        """, (guild_id, user_id, target_id, action)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def async_set_birthday(user_id: str, day: int, month: int, year: int | None = None):
    """Set or update a user's birthday."""
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO user_birthdays (user_id, day, month, year, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET day=excluded.day, month=excluded.month, year=excluded.year, updated_at=CURRENT_TIMESTAMP
        """, (user_id, day, month, year))
        await db.commit()

async def async_get_birthday(user_id: str) -> dict | None:
    """Get a user's birthday."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_birthdays WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def async_remove_birthday(user_id: str) -> bool:
    """Remove a user's birthday."""
    async with _connect_async() as db:
        cur = await db.execute("DELETE FROM user_birthdays WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0

async def async_get_birthdays_today(day: int, month: int) -> list:
    """Get all users whose birthday is today."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_birthdays WHERE day = ? AND month = ?", (day, month)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def async_get_upcoming_birthdays(current_month: int, current_day: int, limit: int = 10) -> list:
    """Get upcoming birthdays sorted by nearest date."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        # Sort by how far the birthday is from today (wrapping around year)
        async with db.execute("""
            SELECT *, 
                CASE 
                    WHEN (month > ? OR (month = ? AND day >= ?)) THEN (month - ?) * 31 + (day - ?)
                    ELSE (month + 12 - ?) * 31 + (day - ?)
                END AS distance
            FROM user_birthdays
            ORDER BY distance ASC
            LIMIT ?
        """, (current_month, current_month, current_day, current_month, current_day, current_month, current_day, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def async_get_birthday_settings(guild_id: str) -> dict:
    """Get birthday settings for a guild."""
    defaults = {
        "guild_id": guild_id, "enabled": 1, "channel_id": None,
        "role_id": None, "message_template": None,
        "gift_coins": 500, "gift_xp": 200,
    }
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM birthday_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return defaults

async def async_upsert_birthday_settings(guild_id: str, **fields):
    """Insert or update birthday settings."""
    async with _connect_async() as db:
        await db.execute("INSERT OR IGNORE INTO birthday_settings (guild_id) VALUES (?)", (guild_id,))
        if fields:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            await db.execute(
                f"UPDATE birthday_settings SET {set_clause} WHERE guild_id = ?",
                [*fields.values(), guild_id],
            )
        await db.commit()

def get_birthday_settings_sync(guild_id: str) -> dict:
    """Sync — get birthday settings (for dashboard)."""
    defaults = {
        "guild_id": guild_id, "enabled": 1, "channel_id": None,
        "role_id": None, "message_template": None,
        "gift_coins": 500, "gift_xp": 200,
    }
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM birthday_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            return _row_to_dict(row)
    return defaults

def upsert_birthday_settings_sync(guild_id: str, **fields):
    """Sync — upsert birthday settings (for dashboard)."""
    with _connect_sync() as conn:
        conn.execute("INSERT OR IGNORE INTO birthday_settings (guild_id) VALUES (?)", (guild_id,))
        if fields:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE birthday_settings SET {set_clause} WHERE guild_id = ?",
                [*fields.values(), guild_id],
            )
        conn.commit()

def get_birthdays_this_month_count(guild_id: str, month: int) -> int:
    """Sync — count members with birthdays this month who are in the guild (approximation)."""
    with _connect_sync() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_birthdays WHERE month = ?", (month,)
        ).fetchone()
        return row[0] if row else 0

def get_tempvoice_settings(guild_id: str) -> dict:
    """Sync — Get tempvoice settings."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {"guild_id": guild_id, "enabled": 0, "hub_channel_id": "", "category_id": "", "name_template": "🔊 Phòng của {user}", "default_limit": 0}
        return _row_to_dict(row)

def update_tempvoice_settings(guild_id: str, enabled: int, hub_channel_id: str, category_id: str, name_template: str = "🔊 Phòng của {user}", default_limit: int = 0) -> None:
    """Sync — Update tempvoice settings."""
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO tempvoice_settings (guild_id, enabled, hub_channel_id, category_id, name_template, default_limit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled=excluded.enabled,
                hub_channel_id=excluded.hub_channel_id,
                category_id=excluded.category_id,
                name_template=excluded.name_template,
                default_limit=excluded.default_limit
        """, (guild_id, enabled, hub_channel_id, category_id, name_template, default_limit))
        conn.commit()

def get_active_temp_channels(guild_id: str) -> list:
    """Sync — List currently active temporary voice channels."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tempvoice_active WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]

async def async_get_tempvoice_settings(guild_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {"guild_id": guild_id, "enabled": 0, "hub_channel_id": "", "category_id": "", "name_template": "🔊 Phòng của {user}", "default_limit": 0}
            return dict(row)

async def async_add_active_temp_channel(channel_id: str, guild_id: str, owner_id: str) -> None:
    async with _connect_async() as db:
        await db.execute("""
            INSERT OR REPLACE INTO tempvoice_active (channel_id, guild_id, owner_id, is_locked)
            VALUES (?, ?, ?, 0)
        """, (channel_id, guild_id, owner_id))
        await db.commit()

async def async_remove_active_temp_channel(channel_id: str) -> None:
    async with _connect_async() as db:
        await db.execute("DELETE FROM tempvoice_active WHERE channel_id = ?", (channel_id,))
        await db.commit()

async def async_get_active_temp_channel(channel_id: str) -> dict | None:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tempvoice_active WHERE channel_id = ?", (channel_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def async_update_temp_channel_lock(channel_id: str, is_locked: int) -> None:
    async with _connect_async() as db:
        await db.execute("UPDATE tempvoice_active SET is_locked = ? WHERE channel_id = ?", (is_locked, channel_id))
        await db.commit()

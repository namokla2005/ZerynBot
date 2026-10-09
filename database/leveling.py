"""
leveling.py — Cấu hình leveling, XP người dùng, level roles và bảng xếp hạng.

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

_DEFAULT_LEVELING = {
    "message_xp_min": 15,
    "message_xp_max": 25,
    "voice_xp": 10,
    "announce_channel_id": "current",
    "announce_message": "🎉 Chúc mừng {user} đã đạt cấp **{level}**!",
    "stack_rewards": 0
}

def get_leveling_settings(guild_id: str) -> dict:
    cache_key = f"leveling:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            result = dict(row)
        else:
            result = dict(_DEFAULT_LEVELING)
            
    cache.set(cache_key, result, ttl=300)
    return result

def set_leveling_settings(guild_id: str, settings: dict):
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO leveling_settings (guild_id, message_xp_min, message_xp_max, voice_xp, announce_channel_id, announce_message, stack_rewards)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                message_xp_min=excluded.message_xp_min,
                message_xp_max=excluded.message_xp_max,
                voice_xp=excluded.voice_xp,
                announce_channel_id=excluded.announce_channel_id,
                announce_message=excluded.announce_message,
                stack_rewards=excluded.stack_rewards
        """, (
            guild_id,
            int(settings.get("message_xp_min", 15)),
            int(settings.get("message_xp_max", 25)),
            int(settings.get("voice_xp", 10)),
            settings.get("announce_channel_id"),
            settings.get("announce_message", _DEFAULT_LEVELING["announce_message"]),
            int(settings.get("stack_rewards", 0))
        ))
        conn.commit()
    cache.delete(f"leveling:{guild_id}")

def get_level_roles(guild_id: str) -> dict:
    """Return dict mapping level (int) to role_id (str)"""
    with _connect_sync() as conn:
        rows = conn.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)).fetchall()
        return {row[0]: row[1] for row in rows}

def set_level_roles(guild_id: str, roles: dict):
    """roles is a dict of {level: role_id}"""
    with _connect_sync() as conn:
        conn.execute("DELETE FROM level_roles WHERE guild_id = ?", (guild_id,))
        for level_str, role_id in roles.items():
            if not role_id:
                continue
            try:
                level = int(level_str)
                conn.execute("INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (guild_id, level, role_id))
            except ValueError:
                pass
        conn.commit()

async def async_get_leveling_settings(guild_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return dict(_DEFAULT_LEVELING)

async def async_get_level_roles(guild_id: str) -> dict:
    async with _connect_async() as db:
        async with db.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def async_get_user_level(guild_id: str, user_id: str) -> dict:
    cache_key = f"level:{guild_id}:{user_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
            else:
                result = {"guild_id": guild_id, "user_id": user_id, "xp": 0, "level": 0, "last_message_at": 0, "last_voice_xp_at": 0}
                
    await cache.aset(cache_key, result, ttl=120) # 2 mins TTL
    return result

async def async_update_user_xp(guild_id: str, user_id: str, xp: int, level: int, last_message_at: float = None, last_voice_xp_at: float = None):
    async with _connect_async() as db:
        query = "INSERT INTO user_levels (guild_id, user_id, xp, level"
        values = [guild_id, user_id, xp, level]
        updates = ["xp = excluded.xp", "level = excluded.level"]
        
        if last_message_at is not None:
            query += ", last_message_at"
            values.append(last_message_at)
            updates.append("last_message_at = excluded.last_message_at")
            
        if last_voice_xp_at is not None:
            query += ", last_voice_xp_at"
            values.append(last_voice_xp_at)
            updates.append("last_voice_xp_at = excluded.last_voice_xp_at")
            
        query += ") VALUES (" + ", ".join(["?"] * len(values)) + ") ON CONFLICT(guild_id, user_id) DO UPDATE SET " + ", ".join(updates)
        
        await db.execute(query, tuple(values))
        await db.commit()
    await cache.adelete(f"level:{guild_id}:{user_id}")

async def async_add_user_xp(guild_id: str, user_id: str, xp_delta: int, *, level_from_xp,
                            last_message_at: float = None, last_voice_xp_at: float = None) -> dict:
    """Cộng XP NGUYÊN TỬ: đọc -> tính -> ghi trong cùng một write-transaction.

    `async_update_user_xp` ghi giá trị TUYỆT ĐỐI mà caller tự tính từ một SELECT trước
    đó (và `async_get_user_level` còn cache row 120 giây), nên khi loop cấp XP voice chạy
    song song với XP tin nhắn thì hai bên đè lên nhau: XP của một tin nhắn biến mất,
    không có lỗi nào được log. `BEGIN IMMEDIATE` giành write-lock trước khi đọc nên
    không writer nào xen được giữa chừng.

    `level_from_xp` được truyền vào để công thức level chỉ sống ở MỘT nơi trong cog.
    Trả về {old_xp, xp, old_level, level} để caller quyết định thông báo level-up.
    """
    async with _connect_async() as db:
        await db.execute("BEGIN IMMEDIATE")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT xp, level FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()

        old_xp = int(row["xp"]) if row else 0
        old_level = int(row["level"]) if row else 0
        new_xp = max(0, old_xp + int(xp_delta))
        new_level = int(level_from_xp(new_xp))

        cols = ["guild_id", "user_id", "xp", "level"]
        vals = [guild_id, user_id, new_xp, new_level]
        updates = ["xp = excluded.xp", "level = excluded.level"]
        if last_message_at is not None:
            cols.append("last_message_at")
            vals.append(last_message_at)
            updates.append("last_message_at = excluded.last_message_at")
        if last_voice_xp_at is not None:
            cols.append("last_voice_xp_at")
            vals.append(last_voice_xp_at)
            updates.append("last_voice_xp_at = excluded.last_voice_xp_at")

        # Tên cột là hằng số nội bộ, không đến từ input.
        await db.execute(
            f"INSERT INTO user_levels ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(guild_id, user_id) DO UPDATE SET {', '.join(updates)}",
            tuple(vals),
        )
        await db.commit()

    await cache.adelete(f"level:{guild_id}:{user_id}")
    return {"old_xp": old_xp, "xp": new_xp, "old_level": old_level, "level": new_level}


async def async_reset_user_xp(guild_id: str, user_id: str):
    async with _connect_async() as db:
        await db.execute("DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()
    await cache.adelete(f"level:{guild_id}:{user_id}")

async def async_get_top_users(guild_id: str, limit: int = 10) -> list:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, xp, level FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def async_get_user_rank(guild_id: str, user_id: str) -> int:
    async with _connect_async() as db:
        # Get rank based on XP
        async with db.execute("SELECT COUNT(*) + 1 FROM user_levels WHERE guild_id = ? AND xp > (SELECT xp FROM user_levels WHERE guild_id = ? AND user_id = ?)", (guild_id, guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return 1

async_get_user_xp = async_get_user_level

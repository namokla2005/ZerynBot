"""
embeds.py — Embed đã lưu của dashboard (sync + async).

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

def get_saved_embeds(guild_id: str) -> List[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM saved_embeds WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        ).fetchall()
    result = []
    for row in rows:
        d = _row_to_dict(row)
        try:
            d["embed_data"] = json.loads(d["embed_json"])
        except Exception:
            d["embed_data"] = {}
        result.append(d)
    return result

def save_embed(guild_id: str, name: str, embed_data: Dict) -> int:
    with _connect_sync() as conn:
        cur = conn.execute(
            "INSERT INTO saved_embeds (guild_id, name, embed_json) VALUES (?, ?, ?)",
            (guild_id, name, json.dumps(embed_data, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid

def delete_embed(embed_id: int, guild_id: str):
    with _connect_sync() as conn:
        conn.execute(
            "DELETE FROM saved_embeds WHERE id = ? AND guild_id = ?",
            (embed_id, guild_id),
        )
        conn.commit()

async def async_get_saved_embeds(guild_id: str) -> list[dict]:
    """Lấy danh sách tất cả embed đã lưu của server cho bot (async, chống IDOR)."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, guild_id, name, embed_json, created_at FROM saved_embeds WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,)
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["embed_data"] = json.loads(d["embed_json"])
                except Exception:
                    d["embed_data"] = {}
                result.append(d)
            return result

async def async_get_saved_embed_by_name(guild_id: str, name: str) -> dict | None:
    """Tìm embed đã lưu theo tên cụ thể của server (chống IDOR)."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, guild_id, name, embed_json, created_at FROM saved_embeds WHERE guild_id = ? AND name = ?",
            (guild_id, name.strip())
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["embed_data"] = json.loads(d["embed_json"])
            except Exception:
                d["embed_data"] = {}
            return d

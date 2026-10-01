"""
music.py — Playlist, cache metadata bài hát trên đĩa và thống kê nhạc.

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

def get_playlists(guild_id: str) -> List[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? ORDER BY id DESC", (guild_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tracks"] = get_playlist_tracks(d["id"])
            result.append(d)
        return result

def get_playlist(playlist_id: int) -> Optional[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def get_playlist_by_name(guild_id: str, name: str) -> Optional[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    with _connect_sync() as conn:
        cursor = conn.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        conn.commit()
        return cursor.lastrowid

def delete_playlist(playlist_id: int, guild_id: str):
    with _connect_sync() as conn:
        conn.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        conn.commit()

def add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    with _connect_sync() as conn:
        pos_row = conn.execute("SELECT MAX(position) FROM music_playlist_tracks WHERE playlist_id = ?", (playlist_id,)).fetchone()
        pos = (pos_row[0] or 0) + 1 if pos_row else 1
        
        cursor = conn.execute(
            """INSERT INTO music_playlist_tracks 
               (playlist_id, title, url, duration, webpage_url, thumbnail, uploader, position) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                track.get("title", "Unknown"),
                track.get("url", ""),
                track.get("duration", 0),
                track.get("webpage_url", ""),
                track.get("thumbnail", ""),
                track.get("uploader") or track.get("channel", "—"),
                pos
            )
        )
        conn.commit()
        return cursor.lastrowid

def delete_track_from_playlist(track_id: int):
    with _connect_sync() as conn:
        conn.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        conn.commit()

def get_playlist_of_track(track_id: int) -> Optional[Dict]:
    """Trả về playlist (gồm guild_id, creator_id) chứa track — dùng kiểm quyền trước khi xóa."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT p.* FROM music_playlists p
               JOIN music_playlist_tracks t ON t.playlist_id = p.id
               WHERE t.id = ?""",
            (track_id,),
        ).fetchone()
        return dict(row) if row else None

def get_playlist_tracks(playlist_id: int) -> List[Dict]:
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)).fetchall()
        return [dict(r) for r in rows]

async def async_get_playlists(guild_id: str) -> List[Dict]:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlists WHERE guild_id = ? ORDER BY id DESC", (guild_id,)) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tracks"] = await async_get_playlist_tracks(d["id"])
            result.append(d)
        return result

async def async_get_playlist_by_name(guild_id: str, name: str) -> Optional[Dict]:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)) as cur:
            row = await cur.fetchone()
        if row:
            d = dict(row)
            d["tracks"] = await async_get_playlist_tracks(d["id"])
            return d
        return None

async def async_get_song_cache(cache_key: str, ttl: int = 21600) -> Optional[Any]:
    """Trả về info dict đã lưu (JSON) nếu chưa quá TTL và stream chưa hết hạn, ngược lại None."""
    try:
        async with _connect_async() as db:
            async with db.execute(
                "SELECT payload, created_at FROM music_song_cache WHERE cache_key = ?",
                (cache_key,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        payload, created_at = row
        if created_at and (time.time() - float(created_at)) > ttl:
            return None
        data = json.loads(payload)
        # Kiểm tra stream_expire động: nếu stream URL đã hết hạn hoặc sắp chết (< 30s) -> bỏ qua cache
        if isinstance(data, dict):
            exp = data.get("stream_expire")
            if exp and float(exp) <= (time.time() + 30):
                return None
        return data
    except Exception:
        return None

async def async_set_song_cache(cache_key: str, info: Any, expire_ts: Optional[float] = None) -> None:
    """Lưu info dict vào disk cache (JSON), hỗ trợ expire_ts tùy chọn."""
    try:
        if isinstance(info, dict) and expire_ts:
            info["stream_expire"] = float(expire_ts)
        async with _connect_async() as db:
            await db.execute(
                "INSERT INTO music_song_cache (cache_key, payload, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, created_at = excluded.created_at",
                (cache_key, json.dumps(info, ensure_ascii=False, default=str), time.time()),
            )
            await db.commit()
    except Exception as exc:
        # Ghi cache thất bại không được làm hỏng việc phát nhạc — chỉ ghi log.
        logger.debug(f"[MusicCache] set_song_cache error (key={cache_key[:32]}): {exc}")

async def async_delete_song_cache(cache_key: str) -> None:
    """Xóa entry trong music_song_cache khi force_refresh (giải phóng disk space)."""
    try:
        async with _connect_async() as db:
            await db.execute("PRAGMA busy_timeout = 15000")
            await db.execute("DELETE FROM music_song_cache WHERE cache_key = ?", (cache_key,))
            await db.commit()
    except Exception as exc:
        logger.debug(f"[MusicCache] delete_song_cache error (key={cache_key[:32]}): {exc}")

async def async_create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    async with _connect_async() as db:
        cursor = await db.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        await db.commit()
        return cursor.lastrowid

async def async_delete_playlist(playlist_id: int, guild_id: str):
    async with _connect_async() as db:
        await db.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        await db.commit()

async def async_add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    async with _connect_async() as db:
        async with db.execute("SELECT MAX(position) FROM music_playlist_tracks WHERE playlist_id = ?", (playlist_id,)) as cur:
            pos_row = await cur.fetchone()
        pos = (pos_row[0] or 0) + 1 if pos_row else 1
        
        cursor = await db.execute(
            """INSERT INTO music_playlist_tracks 
               (playlist_id, title, url, duration, webpage_url, thumbnail, uploader, position) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                track.get("title", "Unknown"),
                track.get("url", ""),
                track.get("duration", 0),
                track.get("webpage_url", ""),
                track.get("thumbnail", ""),
                track.get("uploader") or track.get("channel", "—"),
                pos
            )
        )
        await db.commit()
        return cursor.lastrowid

async def async_delete_track_from_playlist(track_id: int):
    async with _connect_async() as db:
        await db.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        await db.commit()

async def async_get_playlist_tracks(playlist_id: int) -> List[Dict]:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def async_get_top_played_songs(guild_id: str, limit: int = 10) -> list[dict]:
    """Top bài hát được nghe nhiều nhất trong server (Bot).

    Trả về: [{"title": <tên bài>, "play_count": <số lần nghe>}, ...]
    """
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT event_label as title, SUM(count) as play_count
            FROM guild_stats
            WHERE guild_id = ? AND event_type = 'music_play'
            GROUP BY event_label
            ORDER BY play_count DESC
            LIMIT ?
        """, (guild_id, limit)) as cur:
            rows = await cur.fetchall()
            return [_row_to_dict(row) for row in rows]

def get_top_played_songs(guild_id: str, limit: int = 10) -> list[dict]:
    """Top bài hát được nghe nhiều nhất trong server (Dashboard, sync)."""
    try:
        with _connect_sync() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT event_label as title, SUM(count) as play_count
                FROM guild_stats
                WHERE guild_id = ? AND event_type = 'music_play'
                GROUP BY event_label
                ORDER BY play_count DESC
                LIMIT ?
            """, (guild_id, limit))
            return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.debug(f"[Database] get_top_played_songs error: {e}")
        return []

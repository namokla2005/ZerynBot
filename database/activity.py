"""
activity.py — Activity log, sự kiện gần đây, hệ thống hỗ trợ 24/7 (support threads).

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

def log_activity(
    action: str,
    event_type: str = "command",
    guild_id: str = None,
    guild_name: str = None,
    user_id: str = None,
    user_name: str = None,
    avatar_url: str = None,
    channel_name: str = None,
    details: str = None,
) -> None:
    """Sync — Ghi nhận 1 sự kiện vào bảng activity_logs."""
    try:
        with _connect_sync(timeout=10.0) as conn:
            conn.execute(
                """
                INSERT INTO activity_logs (
                    guild_id, guild_name, user_id, user_name, avatar_url,
                    channel_name, event_type, action, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id) if guild_id else None,
                    guild_name,
                    str(user_id) if user_id else None,
                    user_name,
                    avatar_url,
                    channel_name,
                    event_type,
                    action,
                    details,
                    time.time()
                )
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"[Database] log_activity error: {e}")

async def async_log_activity(
    action: str,
    event_type: str = "command",
    guild_id: str = None,
    guild_name: str = None,
    user_id: str = None,
    user_name: str = None,
    avatar_url: str = None,
    channel_name: str = None,
    details: str = None,
) -> None:
    """Async — Ghi nhận 1 sự kiện vào bảng activity_logs (cho Discord Bot)."""
    try:
        async with _connect_async(timeout=10.0) as db:
            await db.execute(
                """
                INSERT INTO activity_logs (
                    guild_id, guild_name, user_id, user_name, avatar_url,
                    channel_name, event_type, action, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id) if guild_id else None,
                    guild_name,
                    str(user_id) if user_id else None,
                    user_name,
                    avatar_url,
                    channel_name,
                    event_type,
                    action,
                    details,
                    time.time()
                )
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"[Database] async_log_activity error: {e}")

def _format_activity_rows(rows) -> list:
    """Format row dicts with human-readable created_at_formatted."""
    formatted = []
    for r in rows:
        d = dict(r)
        ts = d.get("created_at")
        if isinstance(ts, (int, float)):
            d["created_at_formatted"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        else:
            d["created_at_formatted"] = str(ts or "")
        formatted.append(d)
    return formatted

def get_recent_guild_events(guild_id: str, limit: int = 15) -> list:
    """Sync — Lấy tối đa 15 lệnh/sự kiện gần nhất của một server."""
    if not guild_id:
        return []
    try:
        with _connect_sync(timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, guild_id, guild_name, user_id, user_name, avatar_url,
                       channel_name, event_type, action, details, created_at
                FROM activity_logs
                WHERE guild_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(guild_id), limit)
            ).fetchall()
            return _format_activity_rows(rows)
    except Exception as e:
        logger.debug(f"[Database] get_recent_guild_events error: {e}")
        return []

async def async_get_recent_guild_events(guild_id: str, limit: int = 15) -> list:
    """Async — Lấy tối đa 15 lệnh/sự kiện gần nhất của một server."""
    if not guild_id:
        return []
    try:
        async with _connect_async(timeout=10.0) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, guild_id, guild_name, user_id, user_name, avatar_url,
                       channel_name, event_type, action, details, created_at
                FROM activity_logs
                WHERE guild_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(guild_id), limit)
            ) as cur:
                rows = await cur.fetchall()
                return _format_activity_rows(rows)
    except Exception as e:
        logger.debug(f"[Database] async_get_recent_guild_events error: {e}")
        return []

def get_system_activity_logs(limit: int = 50, days_ttl: int = 7) -> list:
    """Sync — Lấy log hoạt động thời gian thực (tự động xóa bản ghi cũ hơn 7 ngày)."""
    try:
        cutoff = time.time() - (days_ttl * 86400)
        with _connect_sync(timeout=10.0) as conn:
            # Tự động dọn rác các phiên cũ hơn 7 ngày
            conn.execute("DELETE FROM activity_logs WHERE created_at < ?", (cutoff,))
            conn.commit()

            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, guild_id, guild_name, user_id, user_name, avatar_url,
                       channel_name, event_type, action, details, created_at
                FROM activity_logs
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (cutoff, limit)
            ).fetchall()
            return _format_activity_rows(rows)
    except Exception as e:
        logger.debug(f"[Database] get_system_activity_logs error: {e}")
        return []

async def async_get_system_activity_logs(limit: int = 50, days_ttl: int = 7) -> list:
    """Async — Lấy log hoạt động thời gian thực.

    Đường ĐỌC không được ghi: trước đây mỗi lượt poll của /admin chạy một câu DELETE
    để dọn log cũ, tức là dashboard giành write-lock của SQLite liên tục chỉ để đọc.
    Việc dọn dữ liệu thuộc về `async_prune_old_data` (job bảo trì).
    """
    try:
        cutoff = time.time() - (days_ttl * 86400)
        async with _connect_async(timeout=10.0) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, guild_id, guild_name, user_id, user_name, avatar_url,
                       channel_name, event_type, action, details, created_at
                FROM activity_logs
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (cutoff, limit)
            ) as cur:
                rows = await cur.fetchall()
                return _format_activity_rows(rows)
    except Exception as e:
        logger.debug(f"[Database] async_get_system_activity_logs error: {e}")
        return []

def get_or_create_support_thread(user_id: str, user_name: str, user_avatar: str = "") -> dict:
    """Lấy hoặc tạo phiên hỗ trợ 24/7 cho người dùng (UUID v4 chống IDOR)."""
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT * FROM support_threads 
            WHERE user_id = ? AND status != 'resolved'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (str(user_id),)
        ).fetchone()

        if row:
            if user_name != row["user_name"] or (user_avatar and user_avatar != row["user_avatar"]):
                cur.execute(
                    "UPDATE support_threads SET user_name = ?, user_avatar = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (user_name, user_avatar or row["user_avatar"], row["id"])
                )
                conn.commit()
            return dict(row)

        new_thread_id = uuid.uuid4().hex
        # ON CONFLICT DO NOTHING + đọc lại: hai phiên mở cùng lúc chỉ tạo được một
        # thread 'open' nhờ index UNIQUE một phần idx_support_threads_one_open
        # (khai báo trong database/schema.py). Không còn cửa sổ race giữa SELECT và INSERT.
        cur.execute(
            """
            INSERT INTO support_threads (thread_id, user_id, user_name, user_avatar, status, last_message, last_sender, unread_admin, unread_user)
            VALUES (?, ?, ?, ?, 'open', '', 'user', 0, 0)
            ON CONFLICT DO NOTHING
            """,
            (new_thread_id, str(user_id), user_name, user_avatar or "")
        )
        conn.commit()
        row = cur.execute(
            """
            SELECT * FROM support_threads
            WHERE user_id = ? AND status != 'resolved'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (str(user_id),)
        ).fetchone()
        return dict(row) if row else {}

def get_support_thread(thread_id: str, user_id: str = None) -> Optional[dict]:
    """Lấy thông tin thread theo UUID (kiểm tra quyền sở hữu user_id nếu được truyền)."""
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if user_id:
            row = cur.execute(
                "SELECT * FROM support_threads WHERE thread_id = ? AND user_id = ?",
                (thread_id, str(user_id))
            ).fetchone()
        else:
            row = cur.execute(
                "SELECT * FROM support_threads WHERE thread_id = ?",
                (thread_id,)
            ).fetchone()
        return dict(row) if row else None

def get_support_messages(thread_id: str, after_id: int = 0, limit: int = 50) -> list:
    """Lấy danh sách tin nhắn theo phân trang an toàn (id > after_id)."""
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, thread_id, sender_type, sender_id, sender_name, content, created_at
            FROM support_messages
            WHERE thread_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (thread_id, after_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

def add_support_message(thread_id: str, sender_type: str, sender_id: str, sender_name: str, content: str) -> dict:
    """Lưu tin nhắn vào thread và cập nhật trạng thái thread tức thì (<5ms commit)."""
    clean_content = content.strip()
    if not clean_content:
        return {}

    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute(
            """
            INSERT INTO support_messages (thread_id, sender_type, sender_id, sender_name, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (thread_id, sender_type, str(sender_id), sender_name, clean_content)
        )
        msg_id = cur.lastrowid

        snippet = clean_content[:120] + ("..." if len(clean_content) > 120 else "")
        if sender_type == "user":
            cur.execute(
                """
                UPDATE support_threads 
                SET last_message = ?, last_sender = 'user', unread_admin = unread_admin + 1, updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (snippet, thread_id)
            )
        else:
            cur.execute(
                """
                UPDATE support_threads 
                SET last_message = ?, last_sender = ?, unread_user = unread_user + 1, updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (snippet, sender_type, thread_id)
            )
        conn.commit()

        row = cur.execute("SELECT * FROM support_messages WHERE id = ?", (msg_id,)).fetchone()
        return dict(row) if row else {}

def atomic_escalate_support_thread(thread_id: str) -> bool:
    """
    Atomic Check-and-Set: Đánh dấu thread cần nhân viên hỗ trợ (status='escalated').
    Chỉ thành công (trả về True) nếu chưa escalate trong vòng 5 phút qua.
    Triệt tiêu 100% race condition và spam Discord API.
    """
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            UPDATE support_threads 
            SET last_escalated_at = CURRENT_TIMESTAMP, status = 'escalated', updated_at = CURRENT_TIMESTAMP
            WHERE thread_id = ? 
            AND (last_escalated_at IS NULL OR last_escalated_at < datetime('now', '-5 minutes'))
            """,
            (thread_id,)
        )
        updated = cur.rowcount > 0
        conn.commit()
        return updated

def get_all_support_threads(status_filter: str = None) -> list:
    """Lấy danh sách tất cả support threads cho trang Admin Messenger."""
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if status_filter and status_filter in ("open", "escalated", "resolved"):
            rows = cur.execute(
                """
                SELECT * FROM support_threads 
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT 100
                """,
                (status_filter,)
            ).fetchall()
        else:
            rows = cur.execute(
                """
                SELECT * FROM support_threads 
                ORDER BY CASE WHEN status = 'escalated' THEN 0 WHEN status = 'open' THEN 1 ELSE 2 END,
                         updated_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [dict(r) for r in rows]

def update_support_thread_status(thread_id: str, status: str) -> bool:
    """Admin cập nhật trạng thái thread ('open', 'escalated', 'resolved')."""
    if status not in ("open", "escalated", "resolved"):
        return False
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        cur = conn.cursor()
        cur.execute(
            "UPDATE support_threads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (status, thread_id)
        )
        conn.commit()
        return cur.rowcount > 0

def mark_support_thread_read(thread_id: str, by_admin: bool = False) -> None:
    """Xóa badge tin nhắn chưa đọc."""
    with _connect_sync() as conn:
        conn.execute("PRAGMA busy_timeout=15000;")
        cur = conn.cursor()
        if by_admin:
            cur.execute("UPDATE support_threads SET unread_admin = 0 WHERE thread_id = ?", (thread_id,))
        else:
            cur.execute("UPDATE support_threads SET unread_user = 0 WHERE thread_id = ?", (thread_id,))
        conn.commit()

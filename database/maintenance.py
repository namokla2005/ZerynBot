"""
maintenance.py — WAL checkpoint, job bảo trì, prune dữ liệu cũ và VACUUM có điều kiện.

Tách từ `database.py` (Giai đoạn 3.3).
"""

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from cache import cache

from .conn import (
    VACUUM_FREELIST_THRESHOLD,
    _connect_async,
    _connect_sync,
    _row_to_dict,
    get_db_connection,
    get_db_path,
)

logger = logging.getLogger("ZerynBot.Database")

def wal_checkpoint() -> str:
    """Sync — Checkpoint and truncate WAL file to keep database file size minimal."""
    with _connect_sync(timeout=20.0) as conn:
        res = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        conn.commit()
        return f"WAL Checkpoint TRUNCATE: {res}"

async def async_wal_checkpoint() -> str:
    """Async — Checkpoint and truncate WAL file."""
    async with _connect_async(timeout=20.0) as db:
        async with db.execute("PRAGMA wal_checkpoint(TRUNCATE);") as cur:
            res = await cur.fetchone()
            return f"WAL Checkpoint TRUNCATE: {res}"

def snapshot_database(dest_path: str) -> int:
    """Đồng nhất bản sao DB đang chạy sang `dest_path` (SQLite online backup API).

    KHÔNG copy file `bot.db` trực tiếp: trang đã commit vẫn nằm trong `bot.db-wal`
    (không được zip kèm) và `wal_checkpoint(TRUNCATE)` có thể trả về sớm khi WAL
    đang bận → bản sao torn, restore mất giao dịch economy/level.
    Trả về kích thước file snapshot (byte).
    """
    src = sqlite3.connect(get_db_path(), timeout=30.0)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    return os.path.getsize(dest_path)

async def async_get_maintenance_job(job_key: str) -> float:
    """Trả về timestamp lần chạy gần nhất của một job bảo trì (mặc định 0)."""
    async with _connect_async() as db:
        async with db.execute(
            "SELECT last_run_at FROM maintenance_jobs WHERE job_key = ?", (job_key,)
        ) as cur:
            row = await cur.fetchone()
    return float(row[0]) if row else 0.0

async def async_set_maintenance_job(job_key: str, ts: float = None) -> None:
    """Ghi nhận thời điểm chạy một job bảo trì (chống chạy lặp trong ngày)."""
    if ts is None:
        ts = time.time()
    async with _connect_async() as db:
        await db.execute(
            "INSERT INTO maintenance_jobs (job_key, last_run_at) VALUES (?, ?) "
            "ON CONFLICT(job_key) DO UPDATE SET last_run_at = excluded.last_run_at",
            (job_key, ts),
        )
        await db.commit()

async def async_prune_old_data(
    stats_days: int = 60,
    warnings_days: int = 2,
    interactions_days: int = 60,
    reminders_days: int = 30,
    song_cache_days: int = 7,
    activity_days: int = 7,
) -> dict:
    """
    Dọn dữ liệu cũ để giữ DB gọn (chỉ ghi đúng các bảng tích luỹ theo thời gian):
    - guild_stats      : > stats_days ngày
    - automod_warnings : > warnings_days ngày (cảnh cáo chỉ có ý nghĩa trong 24h)
    - fun_interactions : > interactions_days ngày
    - reminders        : > reminders_days ngày (reminder đã cũ)
    - music_song_cache : > song_cache_days ngày (mặc định 7 ngày)
    - activity_logs    : > activity_days ngày (mặc định 7 ngày, phiên cũ biến mất)
    KHÔNG đụng user_levels / economy_users (dữ liệu member, phải giữ).

    Trả về dict {table: số dòng đã xoá}.
    """
    async with _connect_async() as db:
        deleted = {}

        async def _delete(table: str, where: str, params: tuple):
            async with db.execute(
                f"DELETE FROM {table} WHERE {where}", params
            ) as cur:
                # aiosqlite cursor.rowcount khả dụng sau execute
                deleted[table] = cur.rowcount
            await db.commit()

        try:
            await _delete(
                "guild_stats",
                "date_hour < datetime('now', ?) ",
                (f"-{stats_days} days",),
            )
        except Exception as exc:
            logger.warning(f"[Prune] guild_stats error: {exc}")

        try:
            await _delete(
                "automod_warnings",
                "created_at <= datetime('now', ?) ",
                (f"-{warnings_days} days",),
            )
        except Exception as exc:
            logger.warning(f"[Prune] automod_warnings error: {exc}")

        try:
            # Trước đây `interactions_days` được khai báo + ghi trong docstring nhưng
            # KHÔNG có lệnh dọn nào cho fun_interactions → bảng phình mãi.
            interactions_cutoff = time.time() - (interactions_days * 86400)
            await _delete(
                "fun_interactions",
                "COALESCE(last_used, 0) < ?",
                (interactions_cutoff,),
            )
        except Exception as exc:
            logger.warning(f"[Prune] fun_interactions error: {exc}")

        try:
            # `reminders.remind_at` là INTEGER epoch giây (schema.py). So sánh nó với
            # `datetime('now', ...)` là so số với chuỗi — SQLite xếp INTEGER luôn nhỏ
            # hơn TEXT nên vị từ LUÔN đúng và xóa sạch mọi reminder, kể cả chưa tới hạn.
            reminders_cutoff = time.time() - (reminders_days * 86400)
            await _delete(
                "reminders",
                "remind_at < ?",
                (reminders_cutoff,),
            )
        except Exception as exc:
            logger.warning(f"[Prune] reminders error: {exc}")

        try:
            cutoff = time.time() - (song_cache_days * 86400)
            await _delete(
                "music_song_cache",
                "created_at < ?",
                (cutoff,),
            )
        except Exception as exc:
            logger.warning(f"[Prune] music_song_cache error: {exc}")

        try:
            activity_cutoff = time.time() - (activity_days * 86400)
            await _delete(
                "activity_logs",
                "created_at < ?",
                (activity_cutoff,),
            )
        except Exception as exc:
            logger.warning(f"[Prune] activity_logs error: {exc}")

        try:
            # Dọn dẹp ai_activity_logs: xóa các log cũ hơn 2 ngày theo timestamp, an toàn tuyệt đối
            await _delete(
                "ai_activity_logs",
                "created_at < datetime('now', '-2 days')",
                (),
            )
        except Exception as exc:
            logger.warning(f"[Prune] ai_activity_logs error: {exc}")

    return deleted

async def async_vacuum_db(force: bool = False) -> None:
    """
    Dọn page rác và (chỉ khi cần) VACUUM để trả dung lượng đĩa cho SQLite.

    Trên điện thoại, VACUUM viết lại TOÀN BỘ file DB (giữ lock lâu, tốn I/O thẻ
    nhớ) trong khi phần lớn lần prune chỉ xoá vài dòng → mặc định chỉ VACUUM khi
    tỉ lệ page rác >= VACUUM_FREELIST_THRESHOLD. ``PRAGMA optimize`` luôn chạy vì
    rất nhẹ và giúp query planner chọn index tốt hơn.

    Lưu ý: cố ý KHÔNG dùng _connect_async ở đây — VACUUM cần temp_store mặc định
    (file) thay vì MEMORY để tránh dồn toàn bộ DB vào RAM máy 6GB.
    """
    try:
        async with aiosqlite.connect(get_db_path(), timeout=30.0) as db:
            if not force:
                freelist = pages = 0
                async with db.execute("PRAGMA freelist_count;") as cur:
                    row = await cur.fetchone()
                    freelist = row[0] if row else 0
                async with db.execute("PRAGMA page_count;") as cur:
                    row = await cur.fetchone()
                    pages = row[0] if row else 0
                ratio = (freelist / pages) if pages else 0.0
                if ratio < VACUUM_FREELIST_THRESHOLD:
                    logger.info(
                        "[Database] Bỏ qua VACUUM: %d/%d page rác (%.1f%% < %d%%).",
                        freelist, pages, ratio * 100, int(VACUUM_FREELIST_THRESHOLD * 100),
                    )
                    await db.execute("PRAGMA optimize;")
                    return

            await db.execute("PRAGMA optimize;")
            await db.execute("VACUUM")
    except Exception as exc:
        logger.warning(f"[Database] VACUUM error: {exc}")

"""
conn.py — Tầng kết nối SQLite dùng chung cho cả package `database`.

Đây là NƠI DUY NHẤT giữ `DB_PATH`. Mọi module con import `_connect_sync` /
`_connect_async` / `get_db_path` từ đây, nên test (và CLI) chỉ cần gọi
`database.set_db_path(...)` một lần là toàn bộ package dùng DB mới — không thể
xảy ra chuyện module con giữ bản sao DB_PATH rồi ghi nhầm vào DB production.
"""

import os
import sqlite3  # Core SQLite engine
import logging
import sys
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict

import aiosqlite

logger = logging.getLogger("ZerynBot.Database")

# ─── Path setup ────────────────────────────────────────────────────────────────
# conn.py nằm ở v2/database/conn.py → BASE_DIR phải là v2/ (2 cấp dirname)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "bot.db")

# ─── PRAGMA tuning cho thiết bị RAM thấp (Tecno Pova 2 — 6GB) ───────────────────
# Các PRAGMA dưới đây là PER-CONNECTION (SQLite không lưu vào file DB), nên mọi
# kết nối đều phải đi qua helper bên dưới mới có hiệu lực. Package có ~190 chỗ
# mở kết nối → tập trung về 2 helper thay vì gọi sqlite/aiosqlite trực tiếp.
DB_CACHE_SIZE_KB = -8000            # ≈ 8MB page cache (mặc định SQLite chỉ ~2MB)
DB_MMAP_BYTES = 64 * 1024 * 1024    # 64MB memory-map (virtual, không chiếm RAM thật)
DB_BUSY_TIMEOUT_MS = 15000
VACUUM_FREELIST_THRESHOLD = 0.15    # chỉ VACUUM khi >= 15% page là rác

_DB_PRAGMA_SCRIPT = (
    f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};"
    "PRAGMA synchronous=NORMAL;"
    f"PRAGMA cache_size={DB_CACHE_SIZE_KB};"
    "PRAGMA temp_store=MEMORY;"
    f"PRAGMA mmap_size={DB_MMAP_BYTES};"
)

def get_db_path() -> str:
    """Trả về đường dẫn file DB hiện hành.

    LUÔN đọc qua hàm này ở mọi nơi mở kết nối: sau khi tách `database.py`
    thành package, biến `DB_PATH` chỉ còn tồn tại ở MỘT chỗ (module gốc) nên
    test/bot không thể vô tình trỏ sang DB thật chỉ vì module con giữ bản sao.
    """
    return DB_PATH

def set_db_path(path: str) -> None:
    """Đổi file DB cho toàn bộ package (test, CLI, multi-DB).

    Đây là API DUY NHẤT nên dùng. Ngoài việc đổi `conn.DB_PATH`, hàm còn đồng
    bộ thuộc tính `database.DB_PATH` (nếu package đã import) để code cũ đọc
    `database.DB_PATH` vẫn thấy giá trị đúng — tránh hai nguồn sự thật.
    """
    global DB_PATH
    DB_PATH = str(path)
    pkg = sys.modules.get(__package__ or "database")
    if pkg is not None:
        setattr(pkg, "DB_PATH", DB_PATH)

def _row_to_dict(row: sqlite3.Row) -> Dict:
    return dict(row)

def _connect_sync(timeout: float = 15.0):
    """Mở kết nối SQLite (sync) đã áp PRAGMA tối ưu.

    DB_PATH được đọc tại thời điểm gọi (không cache) để giữ nguyên khả năng
    monkeypatch database.DB_PATH trong test.
    """
    conn = sqlite3.connect(get_db_path(), timeout=timeout)
    try:
        conn.executescript(_DB_PRAGMA_SCRIPT)
    except Exception:
        pass
    return conn

@asynccontextmanager
async def _connect_async(timeout: float = 15.0):
    """Async context manager mở aiosqlite connection + áp PRAGMA tối ưu.

    Dùng executescript để chỉ tốn 1 lần chuyển thread của aiosqlite thay vì 5.
    """
    async with aiosqlite.connect(get_db_path(), timeout=timeout) as db:
        try:
            await db.executescript(_DB_PRAGMA_SCRIPT)
        except Exception:
            pass
        yield db

@contextmanager
def get_db_connection():
    """Context manager mở và đóng tường minh kết nối SQLite, an toàn 100% không rò rỉ file descriptors."""
    conn = None
    try:
        conn = _connect_sync()   # helper đã set busy_timeout/synchronous/cache_size...
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

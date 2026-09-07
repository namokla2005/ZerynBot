"""
cache.py — Pure Python In-Memory RAM Cache Manager (True LRU).
Provides both sync and async methods for Flask and discord.py respectively.
Zero external dependencies (no Redis server required).

Eviction policy (true LRU):
- Uses ``OrderedDict`` so every get/set moves the key to the most-recently-used end.
- When capacity is exceeded, the LEAST-recently-used (oldest) key is evicted first
  (``popitem(last=False)``) instead of blindly dropping the first 20%.
"""
import fnmatch
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("Cache")


class MemoryCache:
    """High-performance, thread-safe, in-memory TTL LRU cache."""

    def __init__(self, max_size: int = 10000):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_size = max_size
        self.enabled = True
        self._cleanup_task = None
        self._schedule_periodic_cleanup()
        logger.info("✅  In-Memory RAM Cache initialized (LRU, max_size=%d)", self._max_size)

    def _schedule_periodic_cleanup(self):
        """Lên lịch dọn dẹp key hết hạn sau 5 phút."""
        self._cleanup_task = threading.Timer(300, self._periodic_cleanup)
        self._cleanup_task.daemon = True
        self._cleanup_task.start()

    def _periodic_cleanup(self):
        """Dọn key expired định kỳ mỗi 5 phút để tránh tích lũy RAM."""
        try:
            now = time.time()
            with self._lock:
                expired = [k for k, (_, exp) in self._store.items() if exp < now]
                for k in expired:
                    self._store.pop(k, None)
        except Exception:
            logger.exception("[Cache] Periodic cleanup error")
        finally:
            self._schedule_periodic_cleanup()

    def _cleanup_expired(self):
        """Dọn key đã hết hạn rồi, nếu vẫn vượt capacity thì evict LRU."""
        now = time.time()
        if len(self._store) > self._max_size:
            expired = [k for k, (_, exp) in self._store.items() if exp < now]
            for k in expired:
                self._store.pop(k, None)
            # Nếu vẫn vượt max_size → evict LRU (entry cũ nhất) cho tới khi đủ chỗ
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)  # pop oldest

    def _touch(self, key: str):
        """Move key to the most-recently-used end (OrderedDict semantics)."""
        if key in self._store:
            self._store.move_to_end(key)

    # ─── SYNC METHODS ────────────────────────────────────────────────────────
    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            val, expire_at = entry
            if time.time() > expire_at:
                self._store.pop(key, None)
                return None
            self._touch(key)  # LRU: vừa dùng → đưa lên cuối
            return val

    def set(self, key: str, value: Any, ttl: int = 300):
        with self._lock:
            self._cleanup_expired()
            self._store[key] = (value, time.time() + ttl)
            self._touch(key)  # vừa ghi → coi là recently used
            self._cleanup_expired()

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

    # ─── ASYNC METHODS ───────────────────────────────────────────────────────
    async def aget(self, key: str) -> Any | None:
        return self.get(key)

    async def aset(self, key: str, value: Any, ttl: int = 300):
        self.set(key, value, ttl)

    async def adelete(self, key: str):
        self.delete(key)

    async def adelete_pattern(self, pattern: str):
        """Xóa tất cả key khớp pattern fnmatch (vd: 'settings:*')."""
        with self._lock:
            matching_keys = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in matching_keys:
                self._store.pop(k, None)

    async def aclear(self):
        self.clear()


# Global instance
cache = MemoryCache()

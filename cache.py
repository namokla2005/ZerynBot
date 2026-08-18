"""
cache.py — Pure Python In-Memory RAM Cache Manager.
Provides both sync and async methods for Flask and discord.py respectively.
Zero external dependencies (no Redis server required).
"""
import time
import json
import fnmatch
import logging
import threading
import asyncio
from typing import Any

logger = logging.getLogger("Cache")


class MemoryCache:
    """High-performance, thread-safe, in-memory TTL cache using Python dictionary."""

    def __init__(self, max_size: int = 3000):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()
        self._max_size = max_size
        self.enabled = True
        logger.info("✅  In-Memory RAM Cache initialized (Zero Redis dependency)")

    def _cleanup_expired(self):
        """Internal cleanup of expired keys if cache exceeds capacity."""
        now = time.time()
        if len(self._store) > self._max_size:
            expired = [k for k, (v, exp) in self._store.items() if exp < now]
            for k in expired:
                self._store.pop(k, None)
            # If still over max_size, evict oldest 20%
            if len(self._store) > self._max_size:
                keys_to_remove = list(self._store.keys())[: int(self._max_size * 0.2)]
                for k in keys_to_remove:
                    self._store.pop(k, None)

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
            return val

    def set(self, key: str, value: Any, ttl: int = 300):
        with self._lock:
            self._cleanup_expired()
            self._store[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

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
            matching_keys = [k for k in self._store.keys() if fnmatch.fnmatch(k, pattern)]
            for k in matching_keys:
                self._store.pop(k, None)


# Global instance
cache = MemoryCache()

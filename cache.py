"""
cache.py — Redis cache wrapper with fallback.
Provides both sync and async methods for Flask and discord.py respectively.
If Redis is down or REDIS_URL is empty, it silently falls back to doing nothing (cache miss).
"""
import json
import logging
from typing import Any
import config

logger = logging.getLogger("Cache")


class CacheManager:
    def __init__(self):
        self.enabled = False
        self.sync_client = None
        self.async_client = None

        if config.REDIS_URL:
            try:
                import redis
                import redis.asyncio as aioredis
                self.sync_client = redis.from_url(
                    config.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                self.async_client = aioredis.from_url(
                    config.REDIS_URL,
                    decode_responses=True,
                    max_connections=5,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                self.sync_client.ping()
                self.enabled = True
                logger.info("✅  Redis cache enabled")
            except Exception as e:
                logger.warning(f"⚠️  Redis connection failed (fallback to direct DB): {e}")
                self.enabled = False

    # ─── SYNC METHODS ────────────────────────────────────────────────────────
    def get(self, key: str):
        if not self.enabled:
            return None
        try:
            val = self.sync_client.get(key)
            return json.loads(val) if val else None
        except Exception as e:
            logger.debug(f"[Cache] get failed for key={key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = 300):
        if not self.enabled:
            return
        try:
            self.sync_client.set(key, json.dumps(value), ex=ttl)
        except Exception as e:
            logger.debug(f"[Cache] set failed for key={key}: {e}")

    def delete(self, key: str):
        if not self.enabled:
            return
        try:
            self.sync_client.delete(key)
        except Exception as e:
            logger.debug(f"[Cache] delete failed for key={key}: {e}")

    # ─── ASYNC METHODS ───────────────────────────────────────────────────────
    async def aget(self, key: str):
        if not self.enabled:
            return None
        try:
            val = await self.async_client.get(key)
            return json.loads(val) if val else None
        except Exception as e:
            logger.debug(f"[Cache] aget failed for key={key}: {e}")
            return None

    async def aset(self, key: str, value: Any, ttl: int = 300):
        if not self.enabled:
            return
        try:
            await self.async_client.set(key, json.dumps(value), ex=ttl)
        except Exception as e:
            logger.debug(f"[Cache] aset failed for key={key}: {e}")

    async def adelete(self, key: str):
        if not self.enabled:
            return
        try:
            await self.async_client.delete(key)
        except Exception as e:
            logger.debug(f"[Cache] adelete failed for key={key}: {e}")

    async def adelete_pattern(self, pattern: str):
        """Xóa tất cả key khớp pattern (dùng SCAN thay KEYS để tránh làm ngắt/treo Redis server)."""
        if not self.enabled:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self.async_client.scan(cursor, match=pattern, count=100)
                if keys:
                    await self.async_client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug(f"[Cache] adelete_pattern failed for pattern={pattern}: {e}")


# Global instance
cache = CacheManager()

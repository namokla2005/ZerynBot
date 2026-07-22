"""
cache.py — Redis cache wrapper with fallback.
Provides both sync and async methods for Flask and discord.py respectively.
If Redis is down or REDIS_URL is empty, it silently falls back to doing nothing (cache miss).
"""
import json
import logging
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
                self.sync_client = redis.from_url(config.REDIS_URL, decode_responses=True)
                self.async_client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
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
        except Exception:
            return None

    def set(self, key: str, value: any, ttl: int = 300):
        if not self.enabled:
            return
        try:
            self.sync_client.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass

    def delete(self, key: str):
        if not self.enabled:
            return
        try:
            self.sync_client.delete(key)
        except Exception:
            pass

    # ─── ASYNC METHODS ───────────────────────────────────────────────────────
    async def aget(self, key: str):
        if not self.enabled:
            return None
        try:
            val = await self.async_client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None

    async def aset(self, key: str, value: any, ttl: int = 300):
        if not self.enabled:
            return
        try:
            await self.async_client.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass

    async def adelete(self, key: str):
        if not self.enabled:
            return
        try:
            await self.async_client.delete(key)
        except Exception:
            pass

# Global instance
cache = CacheManager()

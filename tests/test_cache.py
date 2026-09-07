"""Tests cho cache.py — In-Memory RAM Cache (TTL, sync/async, delete pattern)."""

from cache import cache


def test_set_get_delete_sync():
    cache.set("t:basic", {"v": 1}, ttl=60)
    assert cache.get("t:basic") == {"v": 1}
    cache.delete("t:basic")
    assert cache.get("t:basic") is None


def test_ttl_expired_sync():
    cache.set("t:expired", "x", ttl=-1)  # hết hạn ngay
    assert cache.get("t:expired") is None


def test_get_missing_key():
    assert cache.get("t:does-not-exist") is None


async def test_async_roundtrip():
    await cache.aset("t:async", [1, 2, 3], ttl=60)
    assert await cache.aget("t:async") == [1, 2, 3]
    await cache.adelete("t:async")
    assert await cache.aget("t:async") is None


async def test_async_ttl_expired():
    await cache.aset("t:async-expired", "x", ttl=-1)
    assert await cache.aget("t:async-expired") is None


async def test_delete_pattern():
    await cache.aset("settings:1", "a", ttl=60)
    await cache.aset("settings:2", "b", ttl=60)
    await cache.aset("other:1", "c", ttl=60)
    await cache.adelete_pattern("settings:*")  # fnmatch pattern
    assert await cache.aget("settings:1") is None
    assert await cache.aget("settings:2") is None
    assert await cache.aget("other:1") == "c"  # key khác pattern vẫn còn
    await cache.adelete("other:1")


def test_lru_eviction():
    """True LRU: khi đầy, entry 'cũ nhất' (ít được dùng nhất) bị evict trước."""
    from cache import MemoryCache
    c = MemoryCache(max_size=3)

    c.set("a", 1, ttl=60)
    c.set("b", 2, ttl=60)
    c.set("c", 3, ttl=60)

    # Dùng 'a' → 'a' giờ là recently used; thứ tự LRU: b, c, a
    assert c.get("a") == 1

    # Thêm 'd' → vượt capacity (4 > 3) → evict 'b' (LRU nhất)
    c.set("d", 4, ttl=60)

    assert c.get("b") is None, "b là least-recently-used → phải bị evict"
    assert c.get("c") == 3
    assert c.get("a") == 1
    assert c.get("d") == 4

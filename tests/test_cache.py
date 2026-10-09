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


def test_settings_cache_ttl_is_short_across_processes():
    """TTL config phải ngắn vì cache KHÔNG dùng chung giữa bot và dashboard.

    Dashboard goi cache.delete("settings:<gid>") sau khi luu, nhung no chi xoa trong
    PID cua no. TTL chinh la "do tre" lon nhat ma bot con ap dung cau hinh cu — 300s
    nghia la chu server tat automod tren web va bot con phat thanh vien them 5 phut.
    """
    from cache import GLOBAL_SETTINGS_TTL, SETTINGS_TTL

    assert SETTINGS_TTL <= 60, f"settings TTL {SETTINGS_TTL}s qua dai giua 2 tien trinh"
    assert GLOBAL_SETTINGS_TTL <= 120, f"global TTL {GLOBAL_SETTINGS_TTL}s qua dai"


def test_no_hardcoded_300s_ttl_left_in_database_layer():
    """TTL config phai di qua hang so tap trung, khong so hardcode roi rac."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "database"
    offenders = []
    for py in root.glob("*.py"):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"ttl=300", line):
                offenders.append(f"{py.name}:{n}")
    assert not offenders, f"con TTL 300s hardcode: {offenders}"

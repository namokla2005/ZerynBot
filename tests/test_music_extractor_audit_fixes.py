"""Offline extraction/cache audit regressions; no provider or network calls."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

import music.config as C
import music.extractor as E
import database.music as D


class RamCache:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def aget(self, key):
        return self.values.get(key)

    async def aset(self, key, value, ttl=600):
        self.values[key] = value
        self.ttls[key] = ttl

    async def adelete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def offline(monkeypatch):
    ram = RamCache()
    async def miss(*args, **kwargs):
        return None
    monkeypatch.setattr(E, "cache", ram)
    monkeypatch.setattr(E, "async_get_song_cache", miss)
    monkeypatch.setattr(E, "async_delete_song_cache", miss)
    monkeypatch.setattr(E, "async_set_song_cache", miss)
    if hasattr(E, "async_set_song_cache_batch"):
        monkeypatch.setattr(E, "async_set_song_cache_batch", miss)
    monkeypatch.setattr(E, "get_source_mode", lambda: "compat")
    monkeypatch.setattr(E, "source_cache_tag", lambda: "compat-n-0")
    monkeypatch.setattr(E, "_is_safe_remote_url", lambda q: True)
    return ram


def song(expire=None):
    return {"id": "AbCdEf12345", "title": "Track", "duration": 100,
            "webpage_url": "https://www.youtube.com/watch?v=AbCdEf12345",
            "url": "https://cdn.invalid/audio?Token=Secret",
            "stream_expire": expire or time.time() + 3600,
            "acodec": "opus", "vcodec": "none"}


def test_case_sensitive_url_keys_and_canonical_aliases():
    upper = "https://example.com/Audio?Token=ABC"
    lower = "https://example.com/audio?Token=abc"
    assert E._song_info_cache_key(upper) != E._song_info_cache_key(lower)
    assert E._song_info_cache_key("LOUD Search") == E._song_info_cache_key("loud search")
    assert E._song_info_cache_key("HTTPS://EXAMPLE.COM/Audio?Token=ABC") == E._song_info_cache_key(upper)
    assert E._song_info_cache_key("https://youtu.be/AbCdEf12345?si=trash") == E._song_info_cache_key("https://www.youtube.com/watch?v=AbCdEf12345")
    assert E._song_info_cache_key("AbCdEf12345") != E._song_info_cache_key("aBcDeF12345")


def test_dns_validation_off_event_loop_before_ram_hit(offline, monkeypatch):
    async def run():
        query = "https://example.com/Track"
        offline.values[E._song_info_cache_key(query)] = song()
        thread_ids = []
        def validate(q):
            thread_ids.append(threading.get_ident())
            return False
        monkeypatch.setattr(E, "_is_safe_remote_url", validate)
        assert await E.extract_info(query) is None
        assert thread_ids and all(t != threading.get_ident() for t in thread_ids)
    asyncio.run(run())


def test_malformed_url_returns_safe_failure(offline, monkeypatch):
    async def run():
        monkeypatch.setattr(E, "_is_safe_remote_url", lambda query: False)
        assert await E.extract_info("http://[invalid") is None
        assert await E.extract_metadata("http://[invalid") is None
    asyncio.run(run())


def test_expiring_ram_hit_is_reextracted(offline, monkeypatch):
    async def run():
        offline.values[E._song_info_cache_key("expired")] = song(time.time() + 10)
        calls = []
        monkeypatch.setattr(E, "_extract_sync", lambda *a: calls.append(a) or song())
        assert await E.extract_info("expired")
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("disk", [False, True])
def test_ram_ttl_respects_stream_lifetime(offline, monkeypatch, disk):
    async def run():
        payload = song(time.time() + 90)
        if disk:
            async def hit(*a, **k):
                return payload
            monkeypatch.setattr(E, "async_get_song_cache", hit)
        else:
            monkeypatch.setattr(E, "_extract_sync", lambda *a: payload)
        assert await E.extract_info("short lifetime")
        assert 0 < offline.ttls[E._song_info_cache_key("short lifetime")] <= 60
    asyncio.run(run())


@pytest.mark.parametrize("metadata", [False, True])
def test_singleflight_survives_canceled_waiter(offline, monkeypatch, metadata):
    async def run():
        started, release = threading.Event(), threading.Event()
        calls = []
        def blocking(*args):
            calls.append(args)
            started.set()
            release.wait(2)
            return song()
        monkeypatch.setattr(E, "_extract_metadata_sync" if metadata else "_extract_sync", blocking)
        extract = E.extract_metadata if metadata else E.extract_info
        first = asyncio.create_task(extract("coalesce"))
        second = asyncio.create_task(extract("COALESCE"))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            release.set()
            assert await second
            assert len(calls) == 1
            await asyncio.sleep(0)
            assert not E._inflight
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
    asyncio.run(run())


def test_worker_capacity_retained_after_timeout_and_cancellation(offline, monkeypatch):
    async def run():
        release = threading.Event()
        active = 0
        peak = 0
        lock = threading.Lock()
        def blocking(*args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            release.wait(2)
            with lock:
                active -= 1
            return song()
        monkeypatch.setattr(E, "_extract_sync", blocking)
        monkeypatch.setattr(E, "_EXTRACT_REQUEST_TIMEOUT", .08, raising=False)
        tasks = [asyncio.create_task(E.extract_info(f"blocked {i}")) for i in range(12)]
        try:
            await asyncio.sleep(.04)
            tasks[0].cancel()
            await asyncio.sleep(.15)
            # Deadline returns safe failure without admitting more real workers.
            assert all(t.done() for t in tasks)
            assert peak <= 4
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            if hasattr(E, "close_extractor_resources"):
                await E.close_extractor_resources()
    asyncio.run(run())


def test_autoplay_uses_same_bounded_worker_pool(offline, monkeypatch):
    async def run():
        release = threading.Event()
        entered = []
        def blocking(*args):
            entered.append(args)
            release.wait(2)
            return song()
        monkeypatch.setattr(E, "_extract_sync", blocking)
        monkeypatch.setattr(E, "_find_related_track_sync", blocking)
        tasks = [asyncio.create_task(E.extract_info(f"pool {i}")) for i in range(4)]
        related = None
        try:
            for _ in range(100):
                if len(entered) == 4:
                    break
                await asyncio.sleep(.005)
            related = asyncio.create_task(E.find_related_track("title", "artist"))
            await asyncio.sleep(.03)
            assert len(entered) == 4
            tasks[0].cancel()
            await asyncio.sleep(.03)
            assert len(entered) == 4
        finally:
            release.set()
            await asyncio.gather(*tasks, *([related] if related else []), return_exceptions=True)
            if hasattr(E, "close_extractor_resources"):
                await E.close_extractor_resources()
    asyncio.run(run())


def test_generic_job_has_deadline_and_safe_failure(offline, monkeypatch):
    async def run():
        release = threading.Event()
        monkeypatch.setattr(E, "_EXTRACT_REQUEST_TIMEOUT", .03)
        def blocking(value):
            release.wait(2)
            return value
        try:
            assert await E.run_extraction_job(blocking, 123) is None
            assert len(C._extraction_runtime.workers) == 1
        finally:
            release.set()
            await E.close_extractor_resources()
        # The 30ms fault-injection deadline applies to the blocked job above,
        # not Windows scheduling/thread startup in this independent success check.
        monkeypatch.setattr(E, "_EXTRACT_REQUEST_TIMEOUT", .3)
        assert await E.run_extraction_job(lambda value: value, 456) == 456
        def failed():
            raise ValueError("signed URL secret")
        assert await E.run_extraction_job(failed) is None
        await E.close_extractor_resources()
    asyncio.run(run())


def test_cache_rechecked_after_worker_admission(offline, monkeypatch):
    async def run():
        for _ in range(4):
            await E._extract_semaphore.acquire()
        calls = []
        monkeypatch.setattr(E, "_extract_sync", lambda *args: calls.append(args) or song())
        task = asyncio.create_task(E.extract_info("late cache"))
        try:
            await asyncio.sleep(.03)
            offline.values[E._song_info_cache_key("late cache")] = song()
        finally:
            for _ in range(4):
                E._extract_semaphore.release()
        assert await task
        assert calls == []
        await E.close_extractor_resources()
    asyncio.run(run())


def test_pending_flights_are_capped_and_deadline_cleans_map(offline, monkeypatch):
    async def run():
        release = threading.Event()
        monkeypatch.setattr(E, "_MAX_INFLIGHT", 2)
        monkeypatch.setattr(E, "_EXTRACT_REQUEST_TIMEOUT", .06)
        monkeypatch.setattr(E, "_extract_sync", lambda *args: release.wait(2) and song())
        first = asyncio.create_task(E.extract_info("first pending"))
        second = asyncio.create_task(E.extract_info("second pending"))
        try:
            await asyncio.sleep(.02)
            assert len(E._inflight) == 2
            assert await E.extract_info("third rejected") is None
            assert await first is None
            assert await second is None
            await asyncio.sleep(0)
            assert not E._inflight
        finally:
            release.set()
            await E.close_extractor_resources()
    asyncio.run(run())


def test_slow_dns_is_bounded_and_does_not_block_loop(offline, monkeypatch):
    async def run():
        release = threading.Event()
        entered = []
        def dns(query):
            entered.append(query)
            release.wait(2)
            return False
        monkeypatch.setattr(E, "_is_safe_remote_url", dns)
        monkeypatch.setattr(E, "_EXTRACT_REQUEST_TIMEOUT", .06)
        tasks = [asyncio.create_task(E.extract_info(f"https://public.invalid/Track{i}")) for i in range(8)]
        try:
            ticks = 0
            for _ in range(8):
                await asyncio.sleep(.01)
                ticks += 1
            assert ticks == 8
            assert len(entered) <= 4
            assert await asyncio.gather(*tasks) == [None] * 8
        finally:
            release.set()
            await E.close_extractor_resources()
    asyncio.run(run())


def test_replacement_generations_progress_with_old_workers_and_global_limit(offline, monkeypatch):
    import importlib
    async def run():
        runtime = C._extraction_runtime
        releases = [threading.Event() for _ in range(4)]
        entered = [threading.Event() for _ in range(4)]
        tasks, drains = [], []
        active = peak = 0
        lock = threading.Lock()
        def blocking(index):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            entered[index].set()
            releases[index].wait(3)
            with lock:
                active -= 1
            return index
        monkeypatch.setattr(E, "_EXTRACT_CLOSE_TIMEOUT", .03)
        monkeypatch.setattr(E, "_extract_sync", lambda *args: song())
        monkeypatch.setattr(E, "_extract_metadata_sync", lambda *args: song())
        pool = None
        try:
            for generation in range(3):
                task = asyncio.create_task(E.run_extraction_job(blocking, generation))
                tasks.append(task)
                for _ in range(100):
                    if entered[generation].is_set():
                        break
                    await asyncio.sleep(.005)
                assert entered[generation].is_set()
                pool = pool or runtime.executor
                assert runtime.executor is pool
                await asyncio.wait_for(E.close_extractor_resources(), timeout=.3)
                drains.append(runtime.close_task)
                assert not runtime.closing
                assert len(runtime.workers) == generation + 1
                importlib.reload(C)
                assert C._extraction_runtime is runtime
                assert C._extract_semaphore is E._extract_semaphore
                # All public APIs must work on free slots before any old worker exits.
                assert await E.run_extraction_job(lambda: "replacement") == "replacement"
                assert await E.extract_info(f"replacement stream {generation}")
                assert await E.extract_metadata(f"replacement metadata {generation}")
            tasks.append(asyncio.create_task(E.run_extraction_job(blocking, 3)))
            for _ in range(100):
                if entered[3].is_set():
                    break
                await asyncio.sleep(.005)
            assert entered[3].is_set()
            assert peak == 4
            assert len([t for t in threading.enumerate() if t.name.startswith("music-extract")]) <= 4
            fifth_entered = threading.Event()
            fifth = asyncio.create_task(E.run_extraction_job(lambda: fifth_entered.set() or "fifth"))
            tasks.append(fifth)
            await asyncio.sleep(.03)
            assert not fifth_entered.is_set()
            releases[0].set()
            assert await asyncio.wait_for(fifth, timeout=.3) == "fifth"
            assert peak == 4
            assert runtime.executor is pool
        finally:
            for release in releases:
                release.set()
            await asyncio.gather(*tasks, *drains, return_exceptions=True)
            await E.close_extractor_resources()
        assert runtime.executor is None
        assert not runtime.workers
        assert not runtime.closing
    asyncio.run(run())


def test_old_drain_cannot_close_replacement_pool_or_session(offline, monkeypatch):
    async def run():
        runtime = C._extraction_runtime
        release, entered = threading.Event(), threading.Event()
        def blocking():
            entered.set()
            release.wait(3)
        monkeypatch.setattr(E, "_EXTRACT_CLOSE_TIMEOUT", .3)
        closed = []
        async def close():
            closed.append(True)
        session = SimpleNamespace(closed=False, close=close)
        task = asyncio.create_task(E.run_extraction_job(blocking))
        unloading = None
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            assert entered.is_set()
            pool = runtime.executor
            before_close = runtime.generation
            unloading = asyncio.create_task(E.close_extractor_resources())
            for _ in range(100):
                if (runtime.generation > before_close
                        and runtime.close_generation == runtime.generation and not runtime.closing):
                    break
                await asyncio.sleep(.001)
            assert not unloading.done()  # Old drain is genuinely still waiting.
            assert await E.run_extraction_job(lambda: "replacement") == "replacement"
            monkeypatch.setattr(E.aiohttp, "ClientSession", lambda **kwargs: session)
            assert await E._get_spotify_session() is session
            generation = runtime.generation
            release.set()
            await asyncio.wait_for(unloading, timeout=.3)
            # All native jobs are finished: the generation guard, not a busy-worker
            # check, must prevent the old drain from retiring the replacement pool.
            assert not runtime.workers
            assert runtime.executor is pool
            assert runtime.spotify_session is session
            assert E._spotify_session is session
            assert runtime.generation == generation
            assert not runtime.closing
            assert closed == []
            assert await E.run_extraction_job(lambda: "still live") == "still live"
        finally:
            release.set()
            await asyncio.gather(task, *([unloading] if unloading else []), return_exceptions=True)
            await E.close_extractor_resources()
        assert closed == [True]
    asyncio.run(run())


def test_cookie_renewal_recreates_and_closes_thread_instance(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("first", encoding="utf-8")
    monkeypatch.setattr(C, "_COOKIE_FILE", str(cookie))
    monkeypatch.setattr(C, "_thread_local", threading.local())
    made = []
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            self.closed = False
            made.append(self)
        def close(self):
            self.closed = True
    monkeypatch.setattr(C.yt_dlp, "YoutubeDL", FakeYDL)
    first = C._get_ydl_primary()
    tag = C.source_cache_tag()
    cookie.write_text("second contents", encoding="utf-8")
    second = C._get_ydl_primary()
    assert first is not second
    assert first.closed
    assert second.opts["cookiefile"] == str(cookie)
    assert tag != C.source_cache_tag()
    assert C._get_ydl_primary() is second


def test_cookie_rollover_does_not_save_stale_cookiejar(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    def content(value):
        return f"# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t2147483647\tsession\t{value}\n"
    cookie.write_text(content("old"), encoding="utf-8")
    monkeypatch.setattr(C, "_COOKIE_FILE", str(cookie))
    monkeypatch.setattr(C, "_thread_local", threading.local())
    first = C._get_ydl_primary()
    assert next(iter(first.cookiejar)).value == "old"
    refreshed = content("fresh-cookie")
    cookie.write_text(refreshed, encoding="utf-8")
    second = C._get_ydl_primary()
    try:
        assert cookie.read_text(encoding="utf-8") == refreshed
        assert next(iter(second.cookiejar)).value == "fresh-cookie"
    finally:
        second.params["cookiefile"] = None
        second.close()


def test_disk_batch_deduplicates_one_transaction(monkeypatch):
    class DB:
        def __init__(self):
            self.rows, self.commits = [], 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def executemany(self, sql, rows):
            self.rows.extend(rows)
        async def commit(self):
            self.commits += 1
    db = DB()
    monkeypatch.setattr(D, "_connect_async", lambda: db)
    asyncio.run(D.async_set_song_cache_batch(["a", "a", "b"], song()))
    assert [row[0] for row in db.rows] == ["a", "b"]
    assert db.commits == 1


def test_fresh_alias_writes_are_one_distinct_batch(offline, monkeypatch):
    async def run():
        batches = []
        async def batch(keys, info, expire_ts=None):
            batches.append(list(keys))
        monkeypatch.setattr(E, "async_set_song_cache_batch", batch, raising=False)
        monkeypatch.setattr(E, "_extract_sync", lambda *a: song())
        await E.extract_info("https://www.youtube.com/watch?v=AbCdEf12345")
        assert len(batches) == 1
        assert len(batches[0]) == len(set(batches[0]))
    asyncio.run(run())


def test_spotify_close_failure_does_not_orphan_executor(offline, monkeypatch):
    async def run():
        assert await E.run_extraction_job(lambda: 1) == 1
        async def failed_close():
            raise OSError("synthetic transport close failure")
        monkeypatch.setattr(E, "_spotify_session", SimpleNamespace(closed=False, close=failed_close))
        await E.close_extractor_resources()
        assert C._extraction_runtime.executor is None
        assert not C._extraction_runtime.closing
    asyncio.run(run())


def test_config_reload_preserves_global_capacity_and_runtime(offline, monkeypatch):
    import importlib
    async def run():
        runtime, capacity = E._extraction_runtime, E._extract_semaphore
        thread_local = C._thread_local
        release = threading.Event()
        entered = []
        def blocking():
            entered.append(threading.get_ident())
            release.wait(3)
        tasks = [asyncio.create_task(E.run_extraction_job(blocking)) for _ in range(4)]
        fifth = None
        try:
            for _ in range(100):
                if len(entered) == 4:
                    break
                await asyncio.sleep(.005)
            assert len(entered) == 4
            importlib.reload(C)
            assert C._extraction_runtime is runtime
            assert C._extract_semaphore is capacity
            assert C._thread_local is thread_local
            importlib.reload(E)
            assert E._extraction_runtime is runtime
            assert E._extract_semaphore is capacity
            fifth_entered = threading.Event()
            fifth = asyncio.create_task(E.run_extraction_job(lambda: fifth_entered.set() or "fifth"))
            await asyncio.sleep(.03)
            assert not fifth_entered.is_set()
            assert len(runtime.workers) == 4
            release.set()
            assert await asyncio.wait_for(fifth, timeout=.3) == "fifth"
        finally:
            release.set()
            await asyncio.gather(*tasks, *([fifth] if fifth else []), return_exceptions=True)
            await E.close_extractor_resources()
    asyncio.run(run())


def test_reload_preserves_worker_and_spotify_ownership(offline, monkeypatch):
    import importlib
    async def run():
        release, entered = threading.Event(), threading.Event()
        closed = []
        async def close():
            closed.append(True)
        session = SimpleNamespace(closed=False, close=close)
        C._extraction_runtime.spotify_session = session
        def blocking():
            entered.set()
            release.wait(2)
        job = asyncio.create_task(E.run_extraction_job(blocking))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            runtime = C._extraction_runtime
            assert len(runtime.workers) == 1
            importlib.reload(E)
            assert E._extraction_runtime is runtime
            assert await E._get_spotify_session() is session
            release.set()
            await E.close_extractor_resources()
            await asyncio.gather(job, return_exceptions=True)
            assert closed == [True]
            assert runtime.executor is None
            assert not runtime.workers
        finally:
            release.set()
            await asyncio.gather(job, return_exceptions=True)
            await E.close_extractor_resources()
    asyncio.run(run())


def test_shutdown_closes_spotify_and_is_repeatable(offline, monkeypatch):
    async def run():
        closed = []
        async def close():
            closed.append(True)
        session = SimpleNamespace(closed=False, close=close)
        monkeypatch.setattr(E, "_spotify_session", session)
        await E.close_extractor_resources()
        await E.close_extractor_resources()
        assert closed == [True]
        assert E._spotify_session is None
        assert not E._inflight
        # A reloaded cog may lazily start a new generation after shutdown.
        monkeypatch.setattr(E, "_extract_sync", lambda *a: song())
        assert await E.extract_info("after reload")
        await E.close_extractor_resources()
    asyncio.run(run())

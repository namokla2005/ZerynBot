"""P1-2 — Music: reconnect phải resume, skip không bị recovery đè,
after-play không bị nuốt, và URL private bị chặn trước yt-dlp.
"""
import asyncio
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot"), os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_phase5c_music_watchdog as hw  # noqa: E402


class ReconnectPlayer:
    def __init__(self):
        self._is_reconnecting = False
        self.resumed = 0

    def set_reconnecting(self, status):
        self._is_reconnecting = bool(status)

    async def resume_after_reconnect(self):
        self.resumed += 1


def test_schedule_reconnect_sets_flag_and_runs_resume():
    from music import cog_voice as cv

    async def run():
        player = ReconnectPlayer()
        cog = object.__new__(cv.VoiceLifecycleMixin)
        cog._players = {7: player}
        cog._reconnect_tasks = {}
        cog.bot = types.SimpleNamespace(loop=asyncio.get_running_loop())

        cog._schedule_reconnect_task(7, player)
        assert player._is_reconnecting is True, "schedule đã xoá cờ trước khi task chạy"
        task = cog._reconnect_tasks[7]
        await asyncio.wait_for(task, timeout=1.0)
        assert player.resumed == 1, "resume_after_reconnect không được gọi"
        assert player._is_reconnecting is False

    asyncio.run(run())


def test_skip_during_recovery_does_not_replay_old_track():
    async def run():
        P = hw._harness()
        player, vc = await hw._player(playing=False)
        played = []
        player.current = hw._track(P, title="A")
        player.queue = [hw._track(P, title="B")]

        async def fake_play(track, seek_offset=0):
            played.append(track.title)
            player.current = track

        player._play = fake_play
        task = asyncio.create_task(
            player._handle_after_play_async(error=True, elapsed=5, track=player.current)
        )
        await asyncio.sleep(0.1)      # recovery đang trong backoff 2s
        player.skip()                 # user bấm skip, hàng đợi tiến sang B
        await task
        assert played == ["B"], f"recovery phát đè bài mới: {played}"

    asyncio.run(run())


def test_after_play_during_recovery_is_processed_after_flags_clear():
    async def run():
        P = hw._harness()
        player, vc = await hw._player(playing=True)
        played = []
        player.current = hw._track(P, title="A")
        player.queue = [hw._track(P, title="B")]

        async def fake_play(track, seek_offset=0):
            played.append(track.title)
            player.current = track

        player._play = fake_play
        player._recovering = True
        player.start_time = time.time() - 200
        vc._p = False                 # stream đã EOF trong cửa sổ recovery
        player._after_play(error=None)
        assert player._pending_end is not None, "end event bị nuốt"
        player._recovering = False
        await player._drain_pending_end()
        assert played == ["B"], f"after-play không được xử lý: {played}"

    asyncio.run(run())


def test_extract_sync_blocks_private_url(monkeypatch):
    import music.extractor as ex

    called = []

    class FakeYDL:
        def extract_info(self, *args, **kwargs):
            called.append(args)
            return {"title": "should-not-happen"}

    monkeypatch.setattr(ex, "_get_ydl", lambda: FakeYDL())
    assert ex._extract_sync("http://127.0.0.1:1/secret") is None
    assert called == [], "URL private vẫn được đưa vào yt-dlp"


def test_extract_metadata_blocks_private_url(monkeypatch):
    import music.extractor as ex

    called = []

    class FakeYDL:
        def extract_info(self, *args, **kwargs):
            called.append(args)
            return {"title": "should-not-happen"}

    monkeypatch.setattr(ex, "_get_ydl_flat", lambda: FakeYDL())
    assert ex._extract_metadata_sync("http://169.254.169.254/latest/meta-data") is None
    assert called == []


def test_extract_sync_still_allows_public_url(monkeypatch):
    import music.extractor as ex
    import dashboard.auth as da

    called = []

    class FakeYDL:
        def extract_info(self, *args, **kwargs):
            called.append(args)
            return {"title": "ok", "webpage_url": "https://youtu.be/abc"}

    monkeypatch.setattr(ex, "_get_ydl", lambda: FakeYDL())
    monkeypatch.setattr(da, "is_safe_http_url", lambda url: True)

    info = ex._extract_sync("https://www.youtube.com/watch?v=abc")
    assert info and info["title"] == "ok"
    assert called

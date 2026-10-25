"""P4-B — _play trả trạng thái để không mất track, ffmpeg probe nền, lofi direct stream."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot"), os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_phase5c_music_watchdog as hw  # noqa: E402


def test_play_returns_false_when_voice_is_gone():
    async def run():
        P = hw._harness()
        player, vc = await hw._player(playing=False)
        vc._c = False
        assert await player._play(hw._track(P)) is False

    asyncio.run(run())


def test_dispatch_requeues_track_when_play_rejects_it():
    async def run():
        P = hw._harness()
        player, vc = await hw._player(playing=False)
        player.queue = [hw._track(P, title="A")]

        async def reject(track, seek_offset=0):
            return False

        player._play = reject
        await player._dispatch_next_async()
        assert [t.title for t in player.queue] == ["A"], "track bị pop rồi mất"

    asyncio.run(run())


def test_dispatch_does_not_requeue_after_manual_stop():
    async def run():
        P = hw._harness()
        player, vc = await hw._player(playing=False)
        player.queue = [hw._track(P, title="A")]

        async def reject(track, seek_offset=0):
            return False

        player._play = reject
        player._manual_stopped = True
        await player._dispatch_next_async()
        assert player.queue == []

    asyncio.run(run())


def test_track_has_direct_stream_flag():
    P = hw._harness()
    t = hw._track(P)
    assert t.is_direct_stream is False


def test_source_guards_for_lazy_probe_and_lofi():
    cfg = open(os.path.join(ROOT, "bot", "music", "config.py"), encoding="utf-8").read()
    player = open(os.path.join(ROOT, "bot", "music", "player.py"), encoding="utf-8").read()
    cog = open(os.path.join(ROOT, "bot", "cogs", "music.py"), encoding="utf-8").read()

    assert 'name="ffmpeg-probe"' in cfg
    assert "def get_ffmpeg_before" in cfg
    assert "get_ffmpeg_before()" in player
    assert "is_direct_stream" in player
    assert "track.is_direct_stream = True" in cog

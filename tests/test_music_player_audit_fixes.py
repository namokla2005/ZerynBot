"""Offline regression coverage for the approved player lifecycle audit."""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from music import player as P


class Source:
    def __init__(self, *args, **kwargs):
        self.cleanup_calls = 0
        self._process = None

    def read(self):
        return b"audio"

    def cleanup(self):
        self.cleanup_calls += 1

    def is_opus(self):
        return True


class Voice:
    def __init__(self):
        self.connected = True
        self.playing = False
        self.source = None
        self.played = []
        self.stop_calls = 0
        self.disconnect_calls = 0

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return False

    def play(self, source, after=None):
        self.source = source
        self.played.append((source, after))
        self.playing = True

    def stop(self):
        self.stop_calls += 1
        self.playing = False

    async def disconnect(self, force=False):
        self.disconnect_calls += 1
        self.connected = False


def track(title="A", ready=True, **extra):
    info = {"title": title, "webpage_url": "https://example.com/song", "duration": 200}
    if ready:
        info.update(stream_url="https://cdn.example/audio", is_opus=True)
    info.update(extra)
    return P.Track(info)


@pytest.fixture
async def harness(monkeypatch):
    vc = Voice()
    cog = SimpleNamespace(_drop=lambda gid: None, _cancel_reconnect_task=lambda gid: None)
    guild = SimpleNamespace(id=42, voice_client=None, me=None)
    player = P.MusicPlayer(guild, None, vc, cog)
    monkeypatch.setattr(P.discord, "FFmpegOpusAudio", Source)
    monkeypatch.setattr(P.discord, "FFmpegPCMAudio", Source)
    monkeypatch.setattr(P.discord.opus, "is_loaded", lambda: True)
    import database
    stats = AsyncMock()
    monkeypatch.setattr(database, "async_increment_stat", stats)
    monkeypatch.setattr(P, "async_increment_stat", stats)
    player._send_now_playing = AsyncMock()
    player._schedule_preload = lambda: None
    yield player, vc, stats
    player._cancel_stall_watchdog()
    player._reset_inactivity_timer()
    for task in (player._preload_task, player._end_drain):
        if task and not task.done():
            task.cancel()
    await asyncio.sleep(0)


async def test_concurrent_normal_adds_preserve_first_track(harness, monkeypatch):
    player, vc, _ = harness
    entered, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"stream_url": "https://cdn.example/audio", "is_opus": True}

    monkeypatch.setattr(P, "extract_info", extract)
    a, b = track(ready=False), track("B")
    first = asyncio.create_task(player.add_and_play(a))
    await entered.wait()
    second = asyncio.create_task(player.add_and_play(b))
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert player.current is a
    assert player.queue == [b]
    assert len(vc.played) == 1


async def test_add_during_direct_play_waits_then_queues(harness, monkeypatch):
    player, vc, _ = harness
    entered, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"stream_url": "https://cdn.example/audio", "is_opus": True}

    monkeypatch.setattr(P, "extract_info", extract)
    a, b = track(ready=False), track("B")
    first = asyncio.create_task(player._play(a))
    await entered.wait()
    second = asyncio.create_task(player.add_and_play(b))
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert player.current is a and player.queue == [b]
    assert len(vc.played) == 1


async def test_force_play_remains_replacement(harness):
    player, vc, _ = harness
    await player.add_and_play(track())
    b = track("B")
    await player.add_and_play(b, force_play=True)
    assert player.current is b and len(vc.played) == 2


async def test_stop_during_extraction_cannot_start_orphan_audio(harness, monkeypatch):
    player, vc, stats = harness
    entered, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"stream_url": "https://cdn.example/audio", "is_opus": True}

    monkeypatch.setattr(P, "extract_info", extract)
    playing = asyncio.create_task(player._play(track(ready=False)))
    await entered.wait()
    await player.stop()
    release.set()
    await playing
    await asyncio.sleep(0)
    assert not vc.played and player.current is None
    stats.assert_not_awaited()


async def test_stop_bounds_source_cleanup_and_still_disconnects(harness, monkeypatch):
    player, vc, _ = harness
    entered = asyncio.Event()
    release = asyncio.Event()
    real_to_thread = asyncio.to_thread

    async def fake_to_thread(func, *args, **kwargs):
        if func == vc.source.cleanup:
            entered.set()
            await release.wait()
        else:
            return await real_to_thread(func, *args, **kwargs)

    vc.source = Source()
    vc.playing = True
    monkeypatch.setattr(P, "STALL_CLEANUP_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(P.asyncio, "to_thread", fake_to_thread)
    stopping = asyncio.create_task(player.stop())
    await entered.wait()
    try:
        done, _ = await asyncio.wait({stopping}, timeout=0.15)
        assert stopping in done, "source cleanup must not hold stop forever"
        assert not vc.connected and vc.stop_calls >= 1
    finally:
        release.set()
        await stopping


async def test_source_cleanup_timeout_keeps_stop_retryable(harness, monkeypatch):
    player, vc, _ = harness
    vc.source = Source()
    monkeypatch.setattr(P, "STALL_CLEANUP_TIMEOUT_SECONDS", 0.01)

    async def slow_cleanup(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(P.asyncio, "to_thread", slow_cleanup)
    await player.stop()
    assert not vc.connected
    assert not player._cleanup_done
    monkeypatch.setattr(P.asyncio, "to_thread", AsyncMock())
    await player.stop()
    assert player._cleanup_done


async def test_force_replaying_same_track_counts_new_listen(harness):
    player, _, stats = harness
    t = track()
    await player.add_and_play(t)
    await player.add_and_play(t, force_play=True)
    await asyncio.sleep(0)
    assert stats.await_count == 2


async def test_cancelled_stop_finishes_disconnect_and_drop(harness, monkeypatch):
    player, vc, _ = harness
    entered, release = asyncio.Event(), asyncio.Event()
    dropped = []
    player.cog._drop = dropped.append
    vc.source = Source()

    async def cleanup(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(P.asyncio, "to_thread", cleanup)
    stopping = asyncio.create_task(player.stop())
    await entered.wait()
    stopping.cancel()
    release.set()
    await asyncio.gather(stopping, return_exceptions=True)
    for _ in range(20):
        if dropped:
            break
        await asyncio.sleep(0.01)
    assert not vc.connected and dropped == [42]


async def test_partial_stop_can_retry_disconnect(harness):
    player, vc, _ = harness
    original = vc.disconnect

    async def fail_once(force=False):
        vc.disconnect = original
        raise RuntimeError("temporary disconnect failure")

    vc.disconnect = fail_once
    await player.stop()
    assert not player._cleanup_done
    await player.stop()
    assert not vc.connected and player._cleanup_done


async def test_stop_does_not_cancel_its_reconnect_caller(harness):
    player, vc, _ = harness
    tasks = {}
    player.cog._reconnect_tasks = tasks

    def cancel(gid):
        task = tasks.pop(gid, None)
        if task:
            task.cancel()

    player.cog._cancel_reconnect_task = cancel

    async def reconnect():
        await player.stop()
        return "stopped"

    task = asyncio.create_task(reconnect())
    tasks[42] = task
    assert await task == "stopped"
    assert not vc.connected


async def test_stop_does_not_cancel_wait_for_reconnect_owner(harness):
    player, _, _ = harness
    tasks = {}
    player.cog._reconnect_tasks = tasks

    def cancel(gid):
        task = tasks.pop(gid, None)
        if task:
            task.cancel()

    player.cog._cancel_reconnect_task = cancel

    async def reconnect():
        await player.stop()

    async def wrapper():
        child = asyncio.create_task(reconnect())
        child._music_voice_owner = asyncio.current_task()
        await child
        return "stopped"

    task = asyncio.create_task(wrapper())
    tasks[42] = task
    assert await task == "stopped"


async def test_skip_during_dispatch_extraction_does_not_requeue_skipped_song(harness, monkeypatch):
    player, _, _ = harness
    entered, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"stream_url": "https://cdn.example/audio", "is_opus": True}

    monkeypatch.setattr(P, "extract_info", extract)
    a, b = track(ready=False), track("B")
    player.queue.extend([a, b])
    dispatch = asyncio.create_task(player._dispatch_next_async())
    await entered.wait()
    player.skip()
    await asyncio.sleep(0)
    release.set()
    await dispatch
    await asyncio.sleep(0.01)
    assert player.current is b
    assert a not in player.queue


async def test_zero_frame_clock_never_falls_back_to_wall_time(harness):
    player, _, _ = harness
    player.current = track()
    player.start_time = time.time() - 100
    player._bind_audio_clock(Source())
    assert player.get_audio_position() == 0


async def test_stale_source_read_does_not_advance_active_clock(harness):
    player, _, _ = harness
    old, new = Source(), Source()
    player._bind_audio_clock(old)
    player._bind_audio_clock(new, 10)
    for _ in range(100):
        old.read()
    assert player.get_audio_position() == 10
    assert player._audio_frames == 0


@pytest.mark.parametrize("active", [None, Source()])
async def test_zombie_eof_is_rejected_before_recovery_buffering(harness, active):
    player, _, _ = harness
    player.current = track()
    player._recovering = True
    player._active_source = active
    player._after_play(Source(), None)
    assert player._pending_end is None


async def test_stall_finally_drains_new_source_eof(harness):
    player, vc, _ = harness
    player.current = track()
    player._bind_audio_clock(Source())
    handled = []

    async def replay(t, seek_offset=0):
        new = Source()
        player._bind_audio_clock(new)
        vc.playing = False
        player._after_play(new, None)

    async def handle(error, elapsed, t):
        handled.append(t)

    player._play = replay
    player._handle_after_play_async = handle
    await player._handle_stream_stall()
    await asyncio.sleep(0)
    assert handled == [player.current]
    assert player._end_drain is not None and player._end_drain.done()


async def test_nested_buffered_eofs_exhaust_recovery_then_play_next(harness, monkeypatch):
    player, vc, _ = harness
    a, b = track(), track("B")
    monkeypatch.setattr(P, "extract_info", AsyncMock(return_value={
        "stream_url": "https://cdn.example/refreshed", "is_opus": True,
    }))
    real_sleep = asyncio.sleep

    async def fast_backoff(delay):
        await real_sleep(0 if delay == 2 else delay)

    monkeypatch.setattr(P.asyncio, "sleep", fast_backoff)
    await player._play(a)
    player.queue.append(b)

    async def eof_during_recovery():
        if player.current is a:
            # Late callbacks from replaced sources must not consume another retry.
            for _, stale_after in vc.played[:-1]:
                stale_after(None)
            vc.playing = False
            vc.played[-1][1](None)

    player._send_now_playing = eof_during_recovery
    player._recovering = True
    vc.playing = False
    vc.played[-1][1](None)
    player._recovering = False
    player._drain_pending_end_soon()
    await asyncio.wait_for(asyncio.shield(player._end_drain), timeout=1)
    for _ in range(20):
        await real_sleep(0)
        if player.current is b:
            break
    assert player.current is b and vc.playing, "nested recovery EOF stranded B in queue"
    assert player.queue == []
    assert len(vc.played) == 4, "initial A + two retries + B, without zombie retries"
    assert a.recovery_attempts == 2
    assert player._pending_end is None
    assert player._end_drain.done()


async def test_end_drain_preserves_event_until_recovery_finishes(harness):
    player, vc, _ = harness
    a, b = track(duration=4), track("B")
    await player._play(a)
    player.queue.append(b)
    for _ in range(200):
        vc.source.read()
    player._recovering = True
    vc.playing = False
    vc.played[-1][1](None)
    await player._drain_pending_end()
    assert player._pending_end is not None
    player._recovering = False
    player._drain_pending_end_soon()
    await asyncio.wait_for(player._end_drain, timeout=1)
    assert player.current is b and vc.playing
    assert player._pending_end is None


async def test_skip_in_recovery_counts_next_listening_occurrence(harness, monkeypatch):
    player, vc, stats = harness
    a, b = track(), track("B")
    await player._play(a)
    player.queue.append(b)
    entered, release, b_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_sleep = asyncio.sleep
    started_during_recovery = []

    async def controlled_backoff(delay):
        if delay == 2:
            entered.set()
            await release.wait()
        else:
            await real_sleep(delay)

    async def now_playing():
        if player.current is b:
            started_during_recovery.append(player._recovering)
            b_started.set()

    player._send_now_playing = now_playing
    monkeypatch.setattr(P.asyncio, "sleep", controlled_backoff)
    vc.playing = False
    recovery = asyncio.create_task(player._handle_after_play_async(None, 5, a))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        player.skip()
        await asyncio.wait_for(b_started.wait(), timeout=1)
        await real_sleep(0)
        assert started_during_recovery == [True]
        assert len(vc.played) == 2 and player.current is b
        assert [call.args[2] for call in stats.await_args_list] == ["A", "B"]
    finally:
        release.set()
        await recovery


@pytest.mark.parametrize("flag", ["_recovering", "_is_reconnecting"])
@pytest.mark.parametrize("same_track", [False, True])
async def test_force_replacement_during_recovery_counts_new_occurrence(harness, flag, same_track):
    player, vc, stats = harness
    a = track()
    await player._play(a)
    replacement = a if same_track else track("B")
    setattr(player, flag, True)
    await player.add_and_play(replacement, force_play=True)
    await asyncio.sleep(0)
    assert len(vc.played) == 2 and player.current is replacement
    assert stats.await_count == 2
    assert [call.args[2] for call in stats.await_args_list] == ["A", replacement.title]


async def test_waiting_force_replacements_keep_distinct_occurrences(harness, monkeypatch):
    player, vc, stats = harness
    a = track(ready=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def extract(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"stream_url": "https://cdn.example/audio", "is_opus": True}

    monkeypatch.setattr(P, "extract_info", extract)
    initial = asyncio.create_task(player.add_and_play(a))
    await asyncio.wait_for(entered.wait(), timeout=1)
    player._recovering = True
    first_force = asyncio.create_task(player.add_and_play(a, force_play=True))
    second_force = asyncio.create_task(player.add_and_play(a, force_play=True))
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(initial, first_force, second_force), timeout=1)
    await asyncio.sleep(0)
    assert len(vc.played) == 3
    assert stats.await_count == 3


@pytest.mark.parametrize("flag", ["_recovering", "_is_reconnecting"])
async def test_same_occurrence_resume_after_source_invalidation_does_not_recount(harness, flag):
    player, vc, stats = harness
    a = track()
    await player._play(a)
    player._active_source = None
    vc.playing = False
    setattr(player, flag, True)
    await player._play(a)
    await asyncio.sleep(0)
    assert len(vc.played) == 2
    assert stats.await_count == 1


@pytest.mark.parametrize("loop_mode", [1, 2])
async def test_repeated_track_in_normal_loop_counts_new_occurrence(harness, loop_mode):
    player, vc, stats = harness
    a = track()
    await player._play(a)
    player.loop_mode = loop_mode
    vc.playing = False
    await player._handle_after_play_async(None, 200, a)
    await asyncio.sleep(0)
    assert player.current is a and len(vc.played) == 2
    assert stats.await_count == 2


async def test_live_stall_restarts_at_live_edge(harness):
    player, _, _ = harness
    player.current = track(is_live=True)
    player._bind_audio_clock(Source(), 80)
    replay = AsyncMock()
    player._play = replay
    await player._handle_stream_stall()
    replay.assert_awaited_once_with(player.current, seek_offset=0)


async def test_after_callback_uses_audio_position(harness):
    player, _, _ = harness
    player.current = track()
    player.start_time = time.time() - 100
    src = Source()
    player._bind_audio_clock(src, 7)
    handled = AsyncMock()
    player._handle_after_play_async = handled
    player._after_play(src, None)
    await asyncio.sleep(0.01)
    assert handled.await_args.args[1] == 7


async def test_reconnect_resumes_from_audio_not_wall_position(harness, monkeypatch):
    player, _, _ = harness
    player.current = track()
    player.start_time = time.time() - 100
    player._bind_audio_clock(Source(), 7)
    player._is_reconnecting = True
    replay = AsyncMock()
    player._play = replay
    real_sleep = asyncio.sleep

    async def quick_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(P.asyncio, "sleep", quick_sleep)
    await player.resume_after_reconnect()
    replay.assert_awaited_once_with(player.current, seek_offset=7)


async def test_metadata_track_uses_cache_but_recovery_forces_refresh(harness, monkeypatch):
    player, _, _ = harness
    extract = AsyncMock(return_value={"stream_url": "https://cdn.example/audio", "is_opus": True})
    monkeypatch.setattr(P, "extract_info", extract)
    t = track(ready=False)
    await player._play(t)
    assert extract.await_args.kwargs["force_refresh"] is False
    player._recovering = True
    t.recovery_attempts = 1
    t.stream_url = None
    await player._play(t)
    assert extract.await_args.kwargs["force_refresh"] is True


async def test_metadata_url_failure_falls_back_to_title(harness, monkeypatch):
    player, vc, _ = harness
    extract = AsyncMock(side_effect=[None, {"stream_url": "https://cdn.example/audio", "is_opus": True}])
    monkeypatch.setattr(P, "extract_info", extract)
    t = track("saved song", ready=False)
    await player._play(t)
    assert vc.played and player.current is t
    assert [call.args[0] for call in extract.await_args_list] == [t.url, t.title]


@pytest.mark.parametrize("mode", ["play", "preload"])
@pytest.mark.parametrize("duration", [215, 0])
async def test_metadata_resolution_hydrates_authoritative_playback_fields(harness, monkeypatch, mode, duration):
    player, vc, _ = harness
    requester = SimpleNamespace(id=99)
    saved = track("saved title", ready=False, duration=0)
    saved.requester = requester
    assert saved.is_live is True
    resolved = {
        "stream_url": "https://cdn.example/resolved", "is_opus": True,
        "title": "actual title", "duration": duration, "is_live": False,
        "uploader": "actual artist", "thumbnail": "https://img.example/actual.jpg",
        "webpage_url": "https://example.com/canonical-song",
    }
    extract = AsyncMock(return_value=resolved)
    monkeypatch.setattr(P, "extract_info", extract)
    if mode == "play":
        extract.side_effect = [None, resolved]  # broken saved URL, successful title fallback
        await player._play(saved)
        assert vc.played
        assert [call.args[0] for call in extract.await_args_list] == ["https://example.com/song", "saved title"]
    else:
        saved.recovery_attempts = 1
        player.queue.append(saved)
        await player._preload_next()
    assert saved.title == "actual title"
    assert saved.duration == duration and saved.is_live is False
    assert saved.uploader == "actual artist"
    assert saved.thumbnail == "https://img.example/actual.jpg"
    assert saved.url == "https://example.com/canonical-song"
    assert saved.stream_url == resolved["stream_url"] and saved.is_opus is True
    assert saved.requester is requester and saved.is_direct_stream is False
    assert saved.recovery_attempts == (0 if mode == "play" else 1)
    assert extract.await_args_list[0].kwargs.get("force_refresh", False) is False
    if mode == "play":
        extract.side_effect = None
        extract.reset_mock()
        saved.recovery_attempts = 1
        saved.stream_url = None
        player._recovering = True
        await player._play(saved, seek_offset=10)
        extract.assert_awaited_once_with("https://example.com/canonical-song", force_refresh=True)


async def test_direct_radio_keeps_its_metadata_and_stream_without_extraction(harness, monkeypatch):
    player, _, _ = harness
    radio = track("direct radio", duration=None, is_live=True)
    radio.is_direct_stream = True
    radio.stream_expire = float("inf")
    extract = AsyncMock()
    monkeypatch.setattr(P, "extract_info", extract)
    await player._preload_next(radio)
    await player._play(radio)
    extract.assert_not_awaited()
    assert radio.title == "direct radio" and radio.duration is None
    assert radio.is_live is True and radio.is_direct_stream is True
    assert radio.stream_url == "https://cdn.example/audio"


async def test_old_stop_does_not_disconnect_replacement_adopted_client(harness):
    player, vc, _ = harness
    vc.source = Source()
    vc.playing = True
    player.guild.voice_client = vc
    replacement = SimpleNamespace(vc=vc)
    player.cog._get = lambda gid: replacement
    await player.stop()
    assert vc.connected and vc.playing
    assert vc.source.cleanup_calls == 0
    assert vc.stop_calls == vc.disconnect_calls == 0


async def test_stop_marks_in_progress_before_cog_drop(harness):
    player, _, _ = harness
    states = []
    player.cog._drop = lambda gid: states.append(getattr(player, "_is_stopping", False))
    await player.stop()
    assert states == [True]
    assert not player._is_stopping


async def test_stop_does_not_drop_replacement_player(harness):
    player, _, _ = harness
    dropped = []
    player.cog._get = lambda gid: object()
    player.cog._drop = dropped.append
    cancelled = []
    player.cog._cancel_reconnect_task = cancelled.append
    await player.stop()
    assert dropped == []
    assert cancelled == []


async def test_stats_only_count_successful_new_occurrences(harness):
    player, _, stats = harness
    t = track()
    await player._play(t)
    await player._play(t, seek_offset=20)
    player._recovering = True
    await player._play(t, seek_offset=0)
    player._recovering = False
    await asyncio.sleep(0)
    assert stats.await_count == 1
    # Loop-one is a new listening occurrence, even for the same Track instance.
    player.loop_mode = 1
    await player._handle_after_play_async(None, 200, t)
    await asyncio.sleep(0)
    assert stats.await_count == 2


async def test_seek_to_zero_does_not_count_another_listen(harness):
    player, _, stats = harness
    t = track()
    await player._play(t)
    await player._play(t, seek_offset=0)
    await asyncio.sleep(0)
    assert stats.await_count == 1


async def test_autoplay_uses_shared_extraction_worker(harness, monkeypatch):
    from music import extractor
    player, _, _ = harness
    player.current = track()
    jobs = []

    async def worker(func, *args):
        jobs.append((func, args))
        return {"title": "related", "webpage_url": "https://example.com/related"}

    monkeypatch.setattr(extractor, "run_extraction_job", worker, raising=False)
    # Existing implementation must stay offline even before shared-worker routing.
    monkeypatch.setattr(P, "_find_related_track_sync", lambda *args: None)
    player._play = AsyncMock()
    await player._handle_autoplay()
    assert len(jobs) == 1 and jobs[0][0] is P._find_related_track_sync
    assert player._play.await_args.args[0].title == "related"


async def test_threaded_startup_eof_recovers_exact_track_before_play_returns(harness, monkeypatch):
    player, vc, stats = harness
    a, b, c = track(), track("B"), track("C")
    await player._play(a)
    player.start_time = time.time() - 600
    player.pause_start, player.total_paused_time = 123.0, 17.0
    stale_after = vc.played[0][1]
    player.queue.extend([b, c])
    real_sleep = asyncio.sleep
    observed, thread_errors = [], []

    async def fast_backoff(delay):
        await real_sleep(0 if delay == 2 else delay)

    monkeypatch.setattr(P.asyncio, "sleep", fast_backoff)
    monkeypatch.setattr(P, "extract_info", AsyncMock(return_value={
        "stream_url": "https://cdn.example/refreshed", "is_opus": True,
    }))

    def play_with_immediate_eof(source, after=None):
        Voice.play(vc, source, after)
        if len(vc.played) <= 4:  # B and its two allowed retries; C stays audible.
            def audio_thread():
                try:
                    stale_after(None)
                    observed.append((player.current, player.get_audio_position(),
                                     time.time() - player.start_time,
                                     player.pause_start, player.total_paused_time))
                    vc.playing = False
                    after(None)
                except BaseException as exc:
                    thread_errors.append(exc)
            worker = threading.Thread(target=audio_thread)
            worker.start()
            worker.join(timeout=1)
            assert not worker.is_alive(), "startup callback must finish before play returns"

    vc.play = play_with_immediate_eof
    c_started = asyncio.Event()

    async def now_playing():
        if player.current is c:
            c_started.set()

    player._send_now_playing = now_playing
    await player._dispatch_next_async()
    waiter = asyncio.create_task(c_started.wait())
    try:
        done, _ = await asyncio.wait({waiter}, timeout=1)
        assert waiter in done, "B startup EOF captured A and stranded queued C"
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    await real_sleep(0)
    assert not thread_errors
    assert len(observed) == 3 and all(row[0] is b for row in observed)
    assert all(row[1] == 0 and 0 <= row[2] < 5 and row[3:] == (0.0, 0.0) for row in observed)
    assert player.current is c and vc.playing and player.queue == []
    assert len(vc.played) == 5 and b.recovery_attempts == 2 and a.recovery_attempts == 0
    assert player._pending_end is None
    assert [call.args[2] for call in stats.await_args_list] == ["A", "B", "C"]


@pytest.mark.parametrize("same_track", [False, True])
async def test_rejected_threaded_startup_rolls_back_state_and_ignores_its_eof(harness, same_track):
    player, vc, stats = harness
    a = track()
    await player._play(a)
    for _ in range(500):
        vc.source.read()
    player.pause_start, player.total_paused_time = 123.0, 17.0
    previous = (player.current, player.start_time, player.pause_start,
                player.total_paused_time, player.get_audio_position(), player._counted_occurrence)
    replacement = a if same_track else track("B")
    handled = AsyncMock()
    player._handle_after_play_async = handled
    player._report_play_failure = AsyncMock()
    failed_sources, thread_errors = [], []

    def reject_after_startup_eof(source, after=None):
        vc.source = source
        vc.playing = False
        failed_sources.append(source)
        def audio_thread():
            try:
                after(None)
            except BaseException as exc:
                thread_errors.append(exc)
        worker = threading.Thread(target=audio_thread)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        raise RuntimeError("voice rejected startup")

    vc.play = reject_after_startup_eof
    await player._play(replacement, seek_offset=60)
    await asyncio.sleep(0.01)
    assert not thread_errors
    assert (player.current, player.start_time, player.pause_start,
            player.total_paused_time, player.get_audio_position(), player._counted_occurrence) == previous
    assert player._active_source is None and player._pending_end is None
    assert failed_sources[0].cleanup_calls == 1
    handled.assert_not_awaited()
    assert stats.await_count == 1


async def test_queued_old_source_eof_cannot_end_same_track_force_replacement(harness):
    player, vc, stats = harness
    a = track()
    await player._play(a)
    handled = AsyncMock()
    player._handle_after_play_async = handled
    vc.playing = False
    vc.played[-1][1](None)  # Valid when queued, stale when the event loop handles it.
    await player.add_and_play(a, force_play=True)
    await asyncio.sleep(0.01)
    handled.assert_not_awaited()
    assert len(vc.played) == 2 and vc.playing and player.current is a
    assert stats.await_count == 2


async def test_failed_voice_play_does_not_increment_stats(harness):
    player, vc, stats = harness
    def fail(*args, **kwargs):
        raise RuntimeError("voice play rejected")
    vc.play = fail
    player._report_play_failure = AsyncMock()
    await player._play(track())
    await asyncio.sleep(0)
    stats.assert_not_awaited()
    assert player._active_source is None


async def test_preload_reuses_same_head_job_and_stop_joins_it(harness, monkeypatch):
    player, _, _ = harness
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def extract(*args, **kwargs):
        calls.append(args)
        entered.set()
        await release.wait()

    monkeypatch.setattr(P, "extract_info", extract)
    player.queue.append(track(ready=False))
    # Restore the production scheduler disabled by the generic playback harness.
    player._schedule_preload = P.MusicPlayer._schedule_preload.__get__(player)
    player._schedule_preload()
    await entered.wait()
    first = player._preload_task
    player.queue.append(track("B", ready=False))
    player._schedule_preload()
    try:
        assert player._preload_task is first
        assert len(calls) == 1
    finally:
        await player.stop()
        release.set()
        await asyncio.gather(first, return_exceptions=True)
    assert first.done()


async def test_raw_pcm_is_not_reported_as_opus_copy(harness, monkeypatch):
    player, vc, _ = harness
    class PCM(Source):
        def is_opus(self):
            return False
    monkeypatch.setattr(P.discord, "FFmpegPCMAudio", PCM)
    t = track(is_opus=False)
    await player._play(t)
    player.text_channel = SimpleNamespace(send=AsyncMock())
    player.now_playing_msg = SimpleNamespace(edit=AsyncMock())
    captured = []
    monkeypatch.setattr(P, "async_get_guild_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(P, "MusicControlView", lambda *args: None)
    monkeypatch.setattr(P, "_make_np_embed", lambda *args, **kw: captured.append(kw["is_opus_copy"]))
    await P.MusicPlayer._send_now_playing(player)
    await player.update_now_playing()
    assert captured == [False, False]

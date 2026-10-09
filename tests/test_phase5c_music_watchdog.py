"""Tests Phase 5c — stream watchdog, dong ho audio that, fast-fail, hang doi, FFmpeg probe.

Nguyen tac: do HIEU UNG quan sat duoc (cat FFmpeg, seek toi vi tri thuc, khong quay
vong lap vo han, list hang doi giu nguyen object), khong doc co noi bo.
"""
import asyncio
import json
import os
import time

import pytest


def _harness():
    import os
    import sys

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (ROOT, os.path.join(ROOT, "bot")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import music.player as P

    return P


class FakeVC:
    def __init__(self, playing=True, paused=False, connected=True):
        self._p, self._pa, self._c = playing, paused, connected
        self.stop_calls = 0
        self.played = []
        self.disconnected = False

    def is_playing(self):
        return self._p

    def is_paused(self):
        return self._pa

    def is_connected(self):
        return self._c

    def stop(self):
        self.stop_calls += 1
        self._p = self._pa = False

    def play(self, source, after=None):
        self.played.append((source, after))
        self._p = True

    async def disconnect(self, force=False):
        self.disconnected = True
        self._c = False


class FakeGuild:
    id = 424242
    voice_client = None
    me = None

    async def change_voice_state(self, channel=None, self_deaf=False):
        pass


class FakeCog:
    def __init__(self):
        self.dropped = []

    def _drop(self, gid):
        self.dropped.append(gid)

    def _cancel_reconnect_task(self, gid):
        pass


async def _player(playing=True, paused=False):
    """MusicPlayer that khong the thieu event loop dang chay (no tu tim loop qua vc.client)."""
    P = _harness()
    vc = FakeVC(playing=playing, paused=paused)
    vc.client = type("C", (), {"loop": asyncio.get_running_loop()})()
    return P.MusicPlayer(FakeGuild(), None, vc, cog=FakeCog()), vc


class FakeSource:
    """Nguon phat mo phong: moi lan read() tra 1 frame, het thi tra b'' (EOF)."""

    def __init__(self, frames=10**9, stalled_after=None):
        self.frames_left = frames
        self.stalled_after = stalled_after
        self.cleanup_calls = 0
        self.read_calls = 0

    def read(self, *args):
        self.read_calls += 1
        if self.stalled_after is not None and self.read_calls > self.stalled_after:
            return b""
        if self.frames_left <= 0:
            return b""
        self.frames_left -= 1
        return b"\x00" * 3840

    def cleanup(self):
        self.cleanup_calls += 1

    def is_opus(self):
        return True


def _pcm_source():
    """FakeSource hop le cho PCMVolumeTransformer (no doi AudioSource va khong duoc la opus)."""
    import discord

    class PcmFake(discord.AudioSource):
        def __init__(self):
            self.cleanup_calls = 0

        def read(self):
            return b"\x00" * 3840

        def is_opus(self):
            return False

        def cleanup(self):
            self.cleanup_calls += 1

    return PcmFake()


def _track(P, **kw):
    info = {"title": "bai nhac", "webpage_url": "https://youtu.be/abc", "duration": 200}
    info.update(kw)
    return P.Track(info)


# ─── 1. Dong ho audio dem theo frame DOC DUOC, khong theo dong ho tuong ─────────

async def test_audio_clock_counts_real_frames_not_wall_clock():
    P = _harness()
    player, vc = await _player()
    src = FakeSource()
    player._bind_audio_clock(src, start_offset=10)

    for _ in range(100):
        src.read()

    assert player.get_audio_position() == 12, "100 frame x 20ms + offset 10s = 12s"

    # `get_elapsed()` van tang theo time.time() — day chinh la ly do can dong ho thu hai
    player.current = _track(P)
    player.start_time = time.time() - 500
    assert player.get_elapsed() == 500
    assert player.get_audio_position() == 12


async def test_bind_clock_keeps_source_type_and_volume_intact():
    """Khong duoc proxy hoa source: `isinstance(vc.source, PCMVolumeTransformer)` va
    `.volume` duoc cog nhac dung de hien che do opus-copy va doi am luong."""
    import discord

    P = _harness()
    player, vc = await _player()
    inner = _pcm_source()
    wrapped = discord.PCMVolumeTransformer(inner, volume=0.5)
    player._bind_audio_clock(wrapped, 0)

    assert isinstance(wrapped, discord.PCMVolumeTransformer)
    wrapped.volume = 0.9
    assert wrapped.volume == 0.9
    assert wrapped.read() == b"\x00" * 3840, "audio phai di qua con duoc volume (0 * 0.9 = 0)"
    assert player._audio_frames == 1


# ─── 2. Watchdog cat FFmpeg treo va phat lai tu VI TRI THUC ────────────────────

async def test_watchdog_detects_stalled_stream_and_seeks_to_real_position(monkeypatch):
    P = _harness()
    monkeypatch.setattr(P, "STALL_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(P, "STALL_TIMEOUT_SECONDS", 0.05)

    player, vc = await _player()
    track = _track(P)
    track.stream_url = "https://cdn/that-het-han"
    player.current = track
    src = FakeSource(stalled_after=20)
    player._bind_audio_clock(src, start_offset=0)
    for _ in range(20):          # nguoi dung moi nghe duoc 0.4s
        src.read()
    player.start_time = time.time() - 100   # dong ho tuong da chay 100s
    player._last_data_mono = time.monotonic() - 0.2

    replays = []

    async def fake_play(t, seek_offset=0):
        replays.append((t, seek_offset))

    player._play = fake_play
    player._start_stall_watchdog()
    await asyncio.wait_for(player._watchdog_task, timeout=2)

    assert replays, "watchdog phai phat lai bai dang treo"
    played_track, seek = replays[0]
    assert played_track is track
    assert seek != 100, f"khong duoc seek theo dong ho tuong (nhay qua 100s nhac), nhan {seek}s"
    assert seek < 10, f"seek phai theo vi tri audio thuc (~0s), nhan {seek}s"
    assert vc.stop_calls == 1, "phai cat audio player dang ket"
    assert src.cleanup_calls == 1, (
        "audio thread ket trong read() nen after()/cleanup() khong tu chay — phai tu don ffmpeg"
    )
    assert track.stream_url is None, "buoc extract lai URL/token moi"
    assert track.recovery_attempts == 1


async def test_watchdog_gives_up_after_two_stalls(monkeypatch):
    P = _harness()
    monkeypatch.setattr(P, "STALL_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(P, "STALL_TIMEOUT_SECONDS", 0.05)

    player, vc = await _player()
    track = _track(P)
    track.recovery_attempts = 2
    player.current = track
    src = FakeSource(stalled_after=0)
    player._bind_audio_clock(src, 0)
    player._last_data_mono = time.monotonic() - 0.2

    skipped = []

    async def fake_report(t, reason_key="music.cannot_decode"):
        skipped.append(t)

    async def fake_play(*a, **k):
        skipped.append("PLAY")

    player._report_play_failure = fake_report
    player._play = fake_play
    player._start_stall_watchdog()
    await asyncio.wait_for(player._watchdog_task, timeout=2)

    assert skipped == [track], "treo qua 2 lan phai bo bai, khong treo may mai"


async def test_watchdog_does_not_fire_while_paused(monkeypatch):
    """Pause la co che hop le: discord.py gui silence va KHONG doc source → phai reset
    moc thoi gian, neu khong moi lan pause 30s se bi tinh la treo va cat bai hat."""
    P = _harness()
    monkeypatch.setattr(P, "STALL_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(P, "STALL_TIMEOUT_SECONDS", 0.05)

    player, vc = await _player(playing=False, paused=True)
    player.current = _track(P)
    src = FakeSource(stalled_after=0)
    player._bind_audio_clock(src, 0)
    player._last_data_mono = time.monotonic() - 5

    stalls = []
    real_handle = player._handle_stream_stall

    async def spy():
        stalls.append(True)
        await real_handle()

    player._handle_stream_stall = spy
    player._start_stall_watchdog()
    await asyncio.sleep(0.12)
    player._cancel_stall_watchdog()

    assert not stalls, "pause khong duoc kich hoat recovery"
    assert vc.stop_calls == 0
    assert src.cleanup_calls == 0
    assert player._last_data_mono > time.monotonic() - 0.5, "pause phai refresh moc thoi gian stall"


async def test_watchdog_exits_when_nothing_is_playing(monkeypatch):
    P = _harness()
    monkeypatch.setattr(P, "STALL_CHECK_SECONDS", 0.01)
    player, vc = await _player(playing=False, paused=False)
    player.current = _track(P)
    player._bind_audio_clock(FakeSource(stalled_after=0), 0)
    player._last_data_mono = time.monotonic() - 99

    player._start_stall_watchdog()
    await asyncio.wait_for(player._watchdog_task, timeout=2)
    assert vc.stop_calls == 0, "nguon da dung thi after() lo, watchdog phai thoat"


async def test_stall_recovery_backs_off_when_another_track_started():
    """Race duoc gate Model 2 chi ra: trong luc `await cleanup()` (toi da 5s), /play hoac
    /skip cua nguoi dung da giao source moi. Khoi phuc cua watchdog phai NHUONG, khong
    cat de bai dang phat."""
    P = _harness()
    player, vc = await _player()
    track = _track(P)
    player.current = track
    stale = FakeSource(stalled_after=0)
    competitor = FakeSource()
    real_cleanup = stale.cleanup

    def cleanup_and_takeover():
        player._active_source = competitor   # _play() cua lenh khac vua giao nguon moi
        real_cleanup()

    stale.cleanup = cleanup_and_takeover

    plays, reports = [], []

    async def fake_play(*a, **k):
        plays.append(a)

    async def fake_report(*a, **k):
        reports.append(a)

    player._play = fake_play
    player._report_play_failure = fake_report
    player._bind_audio_clock(stale, 0)

    await player._handle_stream_stall()

    assert not plays and not reports, "phai nhan lai cho stream moi, khong duoc cat de"
    assert player._recovering is False, "khong duoc de _recovering treo sau khi nhuong"
    assert vc.stop_calls == 1, "stream treo van phai bi cat"


async def test_stall_cleanup_timeout_does_not_freeze_recovery(monkeypatch):
    """FFmpeg keo dai trong D-state (kernel Android): cleanup() khong bao gio ve.
    Phai co tran thoi gian, neu khong `_recovering` o True mai mai = player chai
    va moi sau do bi chan."""
    P = _harness()
    monkeypatch.setattr(P, "STALL_CLEANUP_TIMEOUT_SECONDS", 0.05)
    player, vc = await _player()
    player.current = _track(P)

    class WedgedSource(FakeSource):
        def cleanup(self):
            self.cleanup_calls += 1
            time.sleep(1.0)   # gia lap ke ket vinh vien

    src = WedgedSource(stalled_after=0)
    plays = []

    async def fake_play(t, seek_offset=0):
        plays.append(seek_offset)

    player._play = fake_play
    player._bind_audio_clock(src, 0)

    t0 = time.monotonic()
    await asyncio.wait_for(player._handle_stream_stall(), timeout=0.8)
    assert time.monotonic() - t0 < 0.8, "cleanup ket khong duoc keo dai khung recovery"
    assert plays, "van phai phat lai bai sau khi bo qua cleanup"
    assert player._recovering is False


# ─── 3. after-callback zombie cua source da bi cat phai bi bo ──────────────────

async def test_zombie_after_callback_from_old_source_is_ignored():
    P = _harness()
    player, vc = await _player()
    player.current = _track(P)
    old_src, new_src = FakeSource(), FakeSource()
    player._active_source = new_src

    handled = []

    async def spy(error, elapsed, track):
        handled.append(track)

    player._handle_after_play_async = spy

    player._after_play(old_src, None)
    await asyncio.sleep(0.05)
    assert not handled, "callback cua source da bi thay the khong duoc tinh la bai moi ket thuc"

    player._after_play(new_src, None)
    await asyncio.sleep(0.05)
    assert handled, "callback cua source hien hanh van phai duoc xu ly"


async def test_after_play_still_accepts_bare_error_call():
    """Duong goi kieu cu `after(error)` (khong bind source) phai con chay — _recovering
    va reconnect cũ vẫn gọi thẳng callback này ở một số nhánh."""
    P = _harness()
    player, vc = await _player()
    player.current = _track(P)
    handled = []

    async def spy(error, elapsed, track):
        handled.append(track)

    player._handle_after_play_async = spy
    player._after_play(None)          # bound_source=None → khong co guard
    await asyncio.sleep(0.05)
    assert handled, "goi kieu cu bi bo song → khong the phat hien ket thuc bai"


async def test_partial_callback_wired_in_play():
    """`vc.play()` phai duoc truyen after da bind source, neu khong guard zombie vo hieu hoa."""
    P = _harness()
    player, vc = await _player()
    src = FakeSource()
    vc.play(src, after=lambda error=None: None)
    assert vc.played and vc.played[0][0] is src


async def test_play_arms_watchdog_and_bound_callback(monkeypatch, temp_db):
    """Wiring that = _play() THAT su phai: gan audio clock, bat watchdog, va sau callback
    da bind source. Test watchdog o tren goi thang `_start_stall_watchdog()` nen khong
    phat hien neu chuoi noi `_play()` bi cat — day la noi khoa chu cham.
    """
    import functools

    import discord

    P = _harness()
    player, vc = await _player()

    class FakeFFmpeg:
        def __init__(self, url, **kw):
            self.url = url
            self.kw = kw
            self._process = None
            self.read_calls = 0

        def read(self, *a):
            self.read_calls += 1
            return b"\x00" * 3840

        def is_opus(self):
            return True

        def cleanup(self):
            pass

    monkeypatch.setattr(discord, "FFmpegOpusAudio", FakeFFmpeg)
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeFFmpeg)
    monkeypatch.setattr(discord.opus, "is_loaded", lambda: True)
    monkeypatch.setattr(P, "extract_info", lambda *a, **k: asyncio.sleep(0, result=None))

    async def fake_stat(*a, **k):
        return None

    import database

    monkeypatch.setattr(database, "async_increment_stat", fake_stat)

    track = _track(P)
    track.stream_url = "https://cdn/audio.webm"
    track.stream_expire = time.time() + 3600
    track.is_opus = True
    player.volume = 1.0
    player._send_now_playing = lambda: asyncio.sleep(0)

    await player._play(track)

    assert vc.played, "_play() phai giao source cho voice client"
    source, after = vc.played[0]
    assert player._watchdog_task is not None, "_play() phai gan stream watchdog"
    assert player._active_source is source, "nguon dang phat phai duoc ghi de phan biet zombie"
    assert isinstance(after, functools.partial), "after phai duoc bind voi source hien tai"
    assert after.args == (source,), f"after duoc bind sai: {after.args}"

    before = player._audio_frames
    source.read()
    assert player._audio_frames == before + 1, "dong ho audio phai gan vao chinh source that"

    player._cancel_stall_watchdog()


# ─── 4. Fast-fail: bai chet tuc thi khong duoc quay vo han ─────────────────────

async def test_loop_one_stops_replaying_instantly_dead_track():
    """duration=None + EOF ngay → is_premature False, con `_play()` reset
    `_consecutive_errors` moi vong → ban cu phat lai MAI mot bai hong."""
    P = _harness()
    player, vc = await _player()
    track = _track(P, duration=None)
    player.current = track
    player.loop_mode = 1

    replays = []

    async def fake_play(t, seek_offset=0):
        replays.append(t)
        player._consecutive_errors = 0   # dung nhu _play() that

    dispatched = []

    async def fake_report(t, reason_key="music.cannot_decode"):
        dispatched.append(t)

    player._play = fake_play
    player._report_play_failure = fake_report

    for _ in range(3):
        await player._handle_after_play_async(None, 2, track)

    assert len(replays) == 2, f"chi duoc thu lai FAST_FAIL_LIMIT-1 lan, nhan {len(replays)}"
    assert dispatched == [track], "phai bao bai hong chu khong im lang"
    assert player.loop_mode == 0, "phai tat loop khi bi loi quay vong"
    assert player._fast_fails == 0


async def test_short_legit_track_is_not_counted_as_fast_fail():
    P = _harness()
    player, vc = await _player()
    track = _track(P, duration=4)
    player.current = track
    player.loop_mode = 1
    replays = []

    async def fake_play(t, seek_offset=0):
        replays.append(t)

    player._play = fake_play
    for _ in range(4):
        await player._handle_after_play_async(None, 4, track)

    assert len(replays) == 4, "bai 4 giay phat tron ven la hop le, khong duoc bo"
    assert player.loop_mode == 1
    assert player._fast_fails == 0


async def test_long_normal_play_resets_fast_fail_counter():
    P = _harness()
    player, vc = await _player()
    track = _track(P)
    player.current = track
    player._fast_fails = 2

    async def fake_play(t, seek_offset=0):
        return None

    player._play = fake_play
    await player._handle_after_play_async(None, 120, track)
    assert player._fast_fails == 0


# ─── 5. Hang doi: xoa/cat phai giu nguyen list object ──────────────────────────

async def test_queue_helpers_preserve_list_identity():
    P = _harness()
    player, vc = await _player()
    original_list = player.queue
    for i in range(5):
        player.queue.append(_track(P, title=f"b{i}"))

    assert player.truncate_queue_to(3) is not None
    assert player.queue is original_list, "/jump khong duoc thay list moi"
    assert [x.title for x in player.queue] == ["b2", "b3", "b4"]

    assert player.remove_track_at(1).title == "b2"
    assert player.queue is original_list
    assert player.clear_queue() == 2
    assert player.queue is original_list
    assert player.queue == []


async def test_queue_helpers_reject_out_of_range_without_mutating():
    P = _harness()
    player, vc = await _player()
    player.queue.append(_track(P, title="only"))
    assert player.remove_track_at(0) is None
    assert player.remove_track_at(2) is None
    assert player.truncate_queue_to(0) is None
    assert player.truncate_queue_to(99) is None
    assert [x.title for x in player.queue] == ["only"]
    assert player.clear_queue() == 1
    assert player.clear_queue() == 0, "don hang doi rong phai tra 0, khong am"


async def test_alias_of_queue_still_sees_mutations():
    """Chung minh ly do ton tai cua slice assignment: ai giu tham chieu list (embed dang
    build / task nap ngam) thi thao tac van nhin thay, khong ghi vao list cu moi."""
    P = _harness()
    player, vc = await _player()
    for i in range(3):
        player.queue.append(_track(P, title=f"x{i}"))
    alias = player.queue

    player.truncate_queue_to(2)

    assert [t.title for t in alias] == ["x1", "x2"], "alias phai phan anh ket qua cut"


def test_no_code_rebinds_player_queue():
    """Cam kieu `player.queue = <list moi>` trong toan bot/ — cog nhac tung lam the o
    `/jump`, mo cua cho loi 'ghi vao list co moi' khi co them cho giu tham chieu.
    Moi thao tac xoa/cat phai dung helper cua MusicPlayer."""
    import os
    import re
    from pathlib import Path

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pattern = re.compile(r"\bqueue\s*=\s*(?!=)")
    offenders = []
    for py in sorted((Path(ROOT) / "bot").rglob("*.py")):
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        for n, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{rel}:{n}: {line.strip()[:90]}")
    assert not offenders, f"rebind hang doi (phai dung remove_track_at/clear_queue/truncate_queue_to): {offenders}"


# ─── 6. FFmpeg option probe ────────────────────────────────────────────────────

def test_ffmpeg_before_matches_legacy_string_for_modern_builds():
    import music.config as C

    legacy = (
        "-loglevel error "
        "-nostdin "
        "-rw_timeout 10000000 "
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_on_network_error 1 "
        "-reconnect_on_http_error 5xx "
        "-reconnect_delay_max 2 "
        "-fflags +genpts "
        "-probesize 512K "
        "-analyzeduration 500000 "
        '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36\""
    )
    assert C.build_ffmpeg_before(True) == legacy, "build >= 5.0 dung dung cau hinh dang chay on dinh"


def test_ffmpeg_before_drops_flags_ffmpeg_4_would_reject():
    import music.config as C

    old = C.build_ffmpeg_before(False)
    assert "-reconnect_on_network_error" not in old
    assert "-reconnect_on_http_error" not in old
    for must in ("-reconnect 1", "-reconnect_streamed 1", "-rw_timeout 10000000", "-user_agent"):
        assert must in old
    assert old.endswith('"')


@pytest.mark.parametrize(
    "banner,expected",
    [
        ("ffmpeg version n6.1.1 Copyright (c) 2000-2023", 6),
        ("ffmpeg version 4.4.4-0+deb11u1ubuntu1", 4),
        ("ffmpeg version 5.1.2-7build3", 5),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse_ffmpeg_major(banner, expected):
    import music.config as C

    assert C.parse_ffmpeg_major(banner) == expected


def test_stall_threshold_cannot_be_configured_into_a_hammer():
    """ENV la dau vao tu nguoi dung: `MUSIC_STALL_TIMEOUT=0` se cat moi bai hat ngay
    luc mo stream, nen config phai kep ve muc an toan."""
    import importlib

    import music.config as C

    os.environ["MUSIC_STALL_TIMEOUT"] = "0"
    os.environ["MUSIC_STALL_CHECK_INTERVAL"] = "0.001"
    try:
        importlib.reload(C)
        assert C.STALL_TIMEOUT_SECONDS >= 10.0, "nguong stall khong duoc xuong duoi 10s"
        assert C.STALL_CHECK_SECONDS >= 1.0, "chu ki kiem tra khong duoc xuong duoi 1s"
    finally:
        os.environ.pop("MUSIC_STALL_TIMEOUT", None)
        os.environ.pop("MUSIC_STALL_CHECK_INTERVAL", None)
        importlib.reload(C)


def test_probe_failure_falls_back_to_safe_flags(monkeypatch):
    """Khong probe duoc (thieu ffmpeg, timeout) → dung bo co nen, chu KHONG duoc gui
    co ma FFmpeg se reject — uu tien playback chay duoc hon la reconnect thong minh."""
    import subprocess

    import music.config as C

    def boom(*a, **k):
        raise OSError("ffmpeg not found")

    monkeypatch.setattr(subprocess, "run", boom)
    assert C.ffmpeg_http_reconnect_supported() is False

    class R4:
        stdout = "ffmpeg version 4.3.5 Copyright"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R4())
    assert C.ffmpeg_http_reconnect_supported() is False

    class R6:
        stdout = "ffmpeg version n6.0 Copyright"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R6())
    assert C.ffmpeg_http_reconnect_supported() is True


# ─── 7. extract_metadata cache ban gon thay vi dict tho ────────────────────────

async def test_extract_metadata_caches_compact_dict(temp_db, monkeypatch):
    import music.extractor as E
    from cache import cache

    raw = {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "thumbnails": [
            {"url": f"https://i.ytimg.com/vi/x/q{w}.jpg", "width": w} for w in (120, 320, 480, 1280)
        ],
        "description": "x" * 4000,
        "formats": [{"abr": 128, "url": "https://u?" + "y" * 200} for _ in range(12)],
        "heatmap": [{"x": i} for i in range(100)],
        "duration": 213,
        "channel": "Rick Astley",
    }
    monkeypatch.setattr(E, "_extract_metadata_sync", lambda q: dict(raw))
    query = f"https://youtu.be/compact-{int(time.time() * 1000)}"

    out = await E.extract_metadata(query)

    assert out["title"] == "Never Gonna Give You Up"
    assert out["uploader"] == "Rick Astley", "channel phai duon vao uploader cho caller"
    assert out["thumbnail"] == "https://i.ytimg.com/vi/x/q1280.jpg", "van chon thumbnail lon nhat"
    assert out["webpage_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    for junk in ("thumbnails", "formats", "description", "heatmap"):
        assert junk not in out, f"{junk} van nam trong RAM cache 24h"

    cached = await cache.aget(f"song_meta:{query}")
    assert cached == out, "ban cache phai la ban gon, khong phai dict tho"
    assert len(json.dumps(out)) * 20 < len(json.dumps(raw)), "muc tieu: giam dang ke RAM moi metadata"


async def test_extract_metadata_returns_none_on_failure(temp_db, monkeypatch):
    import music.extractor as E

    monkeypatch.setattr(E, "_extract_metadata_sync", lambda q: None)
    assert await E.extract_metadata("https://youtu.be/khong-ton-tai") is None

"""
test_music_behavior.py — Lưới an toàn HÀNH VI cho cog nhạc (Giai đoạn 3).

Mục đích: khoá hành vi của các hàm thuần + MusicPlayer TRƯỚC khi tách
`bot/cogs/music.py` (3025 dòng) thành package `bot/music/`. Nếu refactor làm
đổi hành vi, nhóm test này phải đỏ NGAY TẠI LOCAL, thay vì nổ trên Termux.

Toàn bộ test ở đây chạy offline: không mạng, không voice client thật, không
Discord API. Chỉ dùng object giả cho `vc` / `guild` / `cog`.
"""
import asyncio
import json
import os
import sys
import time

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE_DIR, os.path.join(BASE_DIR, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _M():
    import cogs.music as m

    return m


# ─── Object giả (không cần discord thật) ───────────────────────────────────────

class _FakeSource:
    def __init__(self, volume: float = 1.0):
        self.volume = volume


class _FakeVC:
    def __init__(self, *, playing=False, paused=False, connected=True, source=None):
        self._playing = playing
        self._paused = paused
        self._connected = connected
        self.source = source
        self.stop_calls = 0
        self.disconnected = False

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    def is_connected(self):
        return self._connected

    def stop(self):
        self.stop_calls += 1
        self._playing = False
        self._paused = False

    async def disconnect(self, force=False):
        self.disconnected = True
        self._connected = False


class _FakeGuild:
    def __init__(self, guild_id: int = 424242):
        self.id = guild_id
        self.voice_client = None
        self.me = None
        self.left_voice = False

    async def change_voice_state(self, channel=None):
        self.left_voice = True


class _FakeCog:
    def __init__(self):
        self.dropped = []
        self.cancelled_reconnect = []

    def _drop(self, guild_id):
        self.dropped.append(guild_id)

    def _cancel_reconnect_task(self, guild_id):
        self.cancelled_reconnect.append(guild_id)


def _make_player(*, vc=None, cog=None, guild=None):
    """Dựng MusicPlayer thật (chạy trong event loop) với vc/guild giả."""
    m = _M()
    vc = vc or _FakeVC()
    guild = guild or _FakeGuild()
    loop = asyncio.get_running_loop()
    vc.client = type("C", (), {"loop": loop})()
    return m.MusicPlayer(guild, None, vc, cog=cog)


# ─── Hợp đồng re-export (bắt buộc sau khi tách package) ────────────────────────

PUBLIC_SURFACE = [
    # Hằng số người dùng/test bên ngoài đang đọc
    "YDL_OPTS", "YDL_OPTS_FLAT", "_COOKIE_FILE",
    "FFMPEG_BEFORE", "FFMPEG_OPTS_COPY", "FFMPEG_OPTS_ENCODE",
    "MAX_PLAYERS", "MAX_BG_LOAD", "MAX_QUEUE_SIZE",
    # Hàm extractor
    "clean_youtube_query", "extract_info", "extract_metadata",
    "_fmt_duration", "_clean_song_title", "_is_duplicate_song",
    "_get_stream_url", "_get_stream_acodec", "_get_best_thumbnail",
    "_extract_stream_expire", "_compact_song_info", "_get_ydl", "_get_ydl_flat",
    "_lower_process_priority",
    # Class / view
    "Track", "MusicPlayer", "Music",
    "_make_progress_bar", "_format_queue_duration", "_make_np_embed",
    "MusicControlView", "RemoveSongView", "RemoveSongSelect",
    "SearchSelect", "SearchSelectView", "LyricsPaginatorView",
    "_chunk_lyrics", "_clean_track_title", "_parse_time_str",
]


def test_public_surface_reexported():
    """Sau khi tách package, các tên này PHẢI được re-export ở cogs.music."""
    m = _M()
    missing = [name for name in PUBLIC_SURFACE if not hasattr(m, name)]
    assert not missing, f"cogs.music thiếu tên công khai: {missing}"


def test_setup_callable_and_is_package_facade():
    """Cog loader gọi setup(); facade phải giữ nó callable."""
    m = _M()
    assert callable(m.setup)


# ─── Extractor: hành vi thuần ──────────────────────────────────────────────────

def test_fmt_duration():
    m = _M()
    assert m._fmt_duration(None) == "🔴 LIVE"
    assert m._fmt_duration(0) == "🔴 LIVE"
    assert m._fmt_duration(-5) == "🔴 LIVE"
    assert m._fmt_duration(59) == "00:59"
    assert m._fmt_duration(60) == "01:00"
    assert m._fmt_duration(3661) == "01:01:01"


def test_clean_youtube_query_keeps_only_video_id():
    m = _M()
    dirty = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123&si=tracking_tok"
    assert m.clean_youtube_query(dirty) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert m.clean_youtube_query("https://youtu.be/dQw4w9WgXcQ?si=x") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # Truy vấn tìm kiếm thường không bị đụng tới
    assert m.clean_youtube_query("  never gonna give you up  ") == "never gonna give you up"


def test_get_stream_url_prefers_progressive_opus():
    m = _M()
    hls_opus = {"url": "https://cdn/x.m3u8?expire=1", "protocol": "m3u8_native", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 128}
    prog_opus = {"url": "https://cdn/a.webm?expire=2", "protocol": "https", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 130}
    prog_m4a = {"url": "https://cdn/b.m4a?expire=3", "protocol": "https", "ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 129}
    info = {"formats": [hls_opus, prog_m4a, prog_opus]}
    assert m._get_stream_url(info) == prog_opus["url"]
    # Không có opus progressive → chọn audio-only progressive bất kỳ thay vì HLS
    assert m._get_stream_url({"formats": [hls_opus, prog_m4a]}) == prog_m4a["url"]


def test_get_stream_url_skips_storyboard_and_video_only():
    m = _M()
    info = {
        "formats": [
            {"url": "https://cdn/sb/storyboard.jpg", "ext": "mhtml", "acodec": "none", "vcodec": "none"},
            {"url": "https://cdn/video.mp4", "ext": "mp4", "acodec": "none", "vcodec": "avc1"},
            {"url": "https://cdn/audio.webm", "ext": "webm", "acodec": "opus", "vcodec": "none", "protocol": "https"},
        ]
    }
    assert m._get_stream_url(info) == "https://cdn/audio.webm"
    assert m._get_stream_url({"formats": []}) is None
    assert m._get_stream_url({}) is None


def test_get_stream_url_never_returns_webpage_url():
    """Regress: không bao giờ trả về link trang YouTube (gây treo FFmpeg)."""
    m = _M()
    info = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "formats": []}
    assert m._get_stream_url(info) is None


def test_get_best_thumbnail_prefers_widest():
    m = _M()
    info = {
        "thumbnails": [
            {"url": "https://i/small.jpg", "width": 120},
            {"url": "https://i/big.jpg", "width": 1280},
        ]
    }
    assert m._get_best_thumbnail(info) == "https://i/big.jpg"
    assert m._get_best_thumbnail({"thumbnail": "https://i/direct.jpg"}) == "https://i/direct.jpg"
    assert m._get_best_thumbnail({}) == ""


def test_extract_stream_expire_sources():
    m = _M()
    # 1. Từ query ?expire=
    assert m._extract_stream_expire("https://cdn/x?expire=1700000000&y=1", {}) == 1700000000.0
    # 2. Từ info["stream_expire"]
    assert m._extract_stream_expire("https://cdn/x", {"stream_expire": 1700000123}) == 1700000123.0
    # 3. Từ formats khớp url
    info = {"formats": [{"url": "https://cdn/x", "expire": 1700000456}]}
    assert m._extract_stream_expire("https://cdn/x", info) == 1700000456.0
    # 4. Fallback ~5.5h trong tương lai (không phải 0)
    fallback = m._extract_stream_expire("https://cdn/x", {})
    assert fallback > time.time() + 3600
    # Không có stream_url → 0.0
    assert m._extract_stream_expire(None, {}) == 0.0


def test_compact_song_info_is_small_and_lossless_for_playback():
    m = _M()
    formats = [
        {"url": f"https://cdn/v{i}.mp4", "ext": "mp4", "acodec": "none", "vcodec": "avc1", "width": 1920, "height": 1080, "tbr": 4000 + i}
        for i in range(50)
    ]
    formats.append({"url": "https://cdn/audio.webm?expire=1700000000", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 130, "protocol": "https"})
    big_info = {
        "id": "abc12345678",
        "title": "Bài hát thử nghiệm",
        "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
        "url": "https://www.youtube.com/watch?v=abc12345678",
        "duration": 215,
        "uploader": "Kênh Test",
        "thumbnail": "https://i.ytimg.com/vi/abc12345678/maxresdefault.jpg",
        "formats": formats,
        "captions": {f"lang{i}": {"url": "https://x"} for i in range(30)},
        "heatmap": [{"start_time": i, "value": 0.5} for i in range(200)],
        "live_status": "not_live",
    }
    compact = m._compact_song_info(big_info)
    assert compact["id"] == "abc12345678"
    assert compact["title"] == "Bài hát thử nghiệm"
    assert compact["duration"] == 215
    assert compact["stream_url"] == "https://cdn/audio.webm?expire=1700000000"
    assert compact["acodec"] == "opus"
    assert compact["is_opus"] is True
    assert compact["is_live"] is False
    assert compact["thumbnail"].startswith("https://")
    # Không mang theo formats/captions/heatmap → payload < 1KB
    assert "formats" not in compact and "captions" not in compact and "heatmap" not in compact
    assert len(json.dumps(compact, ensure_ascii=False)) < 1024


def test_clean_song_title_and_duplicate_detection():
    m = _M()
    assert m._clean_song_title("Song Name (Official Music Video)") == "song name"
    assert m._clean_song_title("Song Name [Lyrics]", lowercase=False) == "Song Name"
    assert m._is_duplicate_song("Shape of You (Official Video)", "Shape of You")
    assert m._is_duplicate_song("A", "B") is False


def test_clean_track_title_for_lyrics():
    m = _M()
    assert m._clean_track_title("Song Name (Official Audio) | Kênh Music") == "Song Name"
    assert m._clean_track_title("Song Name 4K HD") == "Song Name"
    # Không làm rỗng tiêu đề
    assert m._clean_track_title("(Official Audio)") == "(Official Audio)"


def test_parse_time_str():
    m = _M()
    assert m._parse_time_str("90") == 90
    assert m._parse_time_str("1:30") == 90
    assert m._parse_time_str("01:02:03") == 3723
    assert m._parse_time_str("abc") is None
    assert m._parse_time_str("1:xx") is None


def test_chunk_lyrics_pages():
    m = _M()
    assert m._chunk_lyrics("") == [""]
    pages = m._chunk_lyrics("\n".join(f"line {i}" for i in range(200)), max_chars=100)
    assert len(pages) > 1
    assert all(len(p) <= 120 for p in pages)
    assert "line 0" in pages[0]


def test_progress_bar_shapes():
    m = _M()
    live = m._make_progress_bar(10, None)
    assert live.count("━") == 45
    assert "zerynbot" in live
    full = m._make_progress_bar(100, 100)
    assert "━" * 45 in full
    half = m._make_progress_bar(50, 100)
    assert half.count("━") == 45  # thanh luôn đủ 45 ký tự, chỉ khác phần bold
    # Không vỡ khi total nhỏ hơn elapsed hoặc elapsed âm
    assert m._make_progress_bar(-5, 100).count("━") == 45
    assert m._make_progress_bar(999, 100).count("━") == 45


def test_format_queue_duration():
    m = _M()

    def _track(duration):
        return m.Track({"title": "t", "duration": duration, "webpage_url": "https://x"})

    assert m._format_queue_duration([], None) == "0s"
    assert m._format_queue_duration([_track(120)], None) == "2m 0s"
    assert m._format_queue_duration([_track(3600)], None) == "1h 0m"
    assert m._format_queue_duration([_track(None)], None) == "LIVE"
    # Cộng dồn cả bài đang phát
    assert m._format_queue_duration([_track(60)], _track(60)) == "2m 0s"


# ─── Track ─────────────────────────────────────────────────────────────────────

def test_track_from_compact_info():
    m = _M()
    info = {
        "title": "Bài Test",
        "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
        "stream_url": "https://cdn/audio.webm?expire=1700000000",
        "stream_expire": 1700000000,
        "duration": 200,
        "uploader": "Uploader",
        "thumbnail": "https://i/t.jpg",
        "is_opus": True,
    }
    t = m.Track(info, requester=None)
    assert t.title == "Bài Test"
    assert t.url == "https://www.youtube.com/watch?v=abc12345678"
    assert t.stream_url == "https://cdn/audio.webm?expire=1700000000"
    assert t.is_opus is True
    assert t.duration_str == "03:20"
    assert t.requester_mention == "Không rõ"
    assert t.is_stream_expired is True  # expire 1700000000 đã ở quá khứ


def test_track_rejects_webpage_stream_url():
    """Regress: Track không được coi link youtube là stream_url."""
    m = _M()
    t = m.Track({"title": "x", "stream_url": "https://www.youtube.com/watch?v=abc12345678"})
    assert t.stream_url is None
    assert t.is_stream_expired is True


def test_track_live_detection():
    m = _M()
    assert m.Track({"title": "l", "duration": 0}).is_live is True
    assert m.Track({"title": "l", "is_live": True}).is_live is True
    assert m.Track({"title": "l", "duration": 120}).is_live is False


# ─── MusicPlayer: hành vi thuần ────────────────────────────────────────────────

def test_player_record_played_history_capped():
    async def _scenario():
        p = _make_player()
        for i in range(35):
            p._record_played(f"Bài {i}")
        assert len(p._played_history) == 30
        assert len(p._played_history_set) == 30
        # history_set lưu dạng chữ thường để tra cứu O(1)
        assert "bài 0" not in p._played_history_set
        assert "bài 34" in p._played_history_set
        # Tên trùng không làm hỏng set
        p._record_played("Bài 34")
        assert len(p._played_history) == 30

    asyncio.run(_scenario())


def test_player_shuffle_keeps_same_tracks():
    async def _scenario():
        p = _make_player()
        p.queue = [_M().Track({"title": f"t{i}", "duration": 10}) for i in range(20)]
        before = [t.title for t in p.queue]
        p.shuffle()
        assert sorted(t.title for t in p.queue) == sorted(before)
        # Hàng đợi 0-1 bài thì không đổi
        p.queue = [p.queue[0]]
        p.shuffle()
        assert len(p.queue) == 1

    asyncio.run(_scenario())


def test_player_set_volume_clamped():
    async def _scenario():
        p = _make_player()
        p.set_volume(0.0)
        assert p.volume == 0.01
        p.set_volume(9.0)
        assert p.volume == 1.5
        p.set_volume(0.75)
        assert p.volume == 0.75

    asyncio.run(_scenario())


def test_player_skip_sets_flag_and_stops_voice():
    async def _scenario():
        cog = _FakeCog()
        vc = _FakeVC(playing=True)
        p = _make_player(vc=vc, cog=cog)
        p.skip()
        assert p._skipped is True
        assert p._is_reconnecting is False
        assert vc.stop_calls == 1
        assert cog.cancelled_reconnect == [p.guild.id]

    asyncio.run(_scenario())


def test_player_get_elapsed_pause_and_play():
    async def _scenario():
        p = _make_player()
        assert p.get_elapsed() == 0  # chưa có bài
        p.current = _M().Track({"title": "x", "duration": 100})
        p.start_time = time.time() - 12
        assert 11 <= p.get_elapsed() <= 13
        # Khi pause, elapsed đóng băng theo pause_start
        p.vc._paused = True
        p.pause_start = p.start_time + 5
        assert p.get_elapsed() == 5

    asyncio.run(_scenario())


def test_player_stop_cleans_everything():
    async def _scenario():
        cog = _FakeCog()
        vc = _FakeVC(playing=True)
        guild = _FakeGuild()
        p = _make_player(vc=vc, cog=cog, guild=guild)
        p.queue = [_M().Track({"title": "a", "duration": 10})]
        p.current = _M().Track({"title": "b", "duration": 10})
        p.loop_mode = 2
        p.autoplay = True
        p._record_played("b")

        await p.stop()

        assert p._manual_stopped is True
        assert p.queue == []
        assert p.current is None
        assert p.loop_mode == 0
        assert p.autoplay is False
        assert p._played_history == [] and p._played_history_set == set()
        assert vc.disconnected is True
        assert cog.dropped == [p.guild.id]

    asyncio.run(_scenario())


def test_stop_from_inactivity_task_still_runs_full_cleanup():
    """Regression (Giai đoạn 3 audit): `_inactivity_countdown()` gọi `await self.stop()`,
    mà `stop()` gọi `_reset_inactivity_timer()` — nếu hàm đó tự huỷ chính task đang chạy
    thì CancelledError bắn vào await kế tiếp giữa `stop()`: bot kẹt voice vĩnh viễn,
    embed NP không xoá, `_drop()` không chạy (zombie player ăn slot MAX_PLAYERS)."""

    class _AwaitVC(_FakeVC):
        """disconnect() phải treo lơ lửng thật thì mới đủ điều kiện bị CancelledError."""

        async def disconnect(self, force=False):
            await asyncio.sleep(0)
            await super().disconnect(force=force)

    async def _scenario():
        cog = _FakeCog()
        vc = _AwaitVC(playing=True)
        p = _make_player(vc=vc, cog=cog)
        p.current = _M().Track({"title": "b", "duration": 10})

        async def _countdown_like():
            await p.stop()

        p._inactivity_task = asyncio.create_task(_countdown_like())
        try:
            await p._inactivity_task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.01)
        return p, vc, cog

    p, vc, cog = asyncio.run(_scenario())
    assert vc.disconnected is True, "stop() phải rời voice channel dù được gọi từ task inactivity"
    assert cog.dropped == [p.guild.id], "_drop() phải chạy để không rò zombie player"


def test_reset_inactivity_timer_still_cancels_other_task():
    """Regression: lỗi ở trên KHÔNG được phá vỡ chức năng huỷ timer từ task khác."""

    async def _scenario():
        p = _make_player()
        victim = asyncio.create_task(asyncio.sleep(30))
        p._inactivity_task = victim
        p._reset_inactivity_timer()
        assert p._inactivity_task is None
        await asyncio.sleep(0.01)
        return victim

    victim = asyncio.run(_scenario())
    assert victim.cancelled() is True


def test_dispatch_next_keeps_queue_when_vc_not_connected():
    """Regression: `_dispatch_next_async()` pop bài khỏi queue rồi mới `_play()`, mà
    `_play()` return ngay khi `vc` rời → bài bị mất vĩnh viễn."""

    async def _scenario():
        cog = _FakeCog()
        vc = _FakeVC(connected=False)
        p = _make_player(vc=vc, cog=cog)
        track = _M().Track({"title": "giữ lại", "duration": 10})
        p.queue.append(track)
        await p._dispatch_next_async()
        return p, track

    p, track = asyncio.run(_scenario())
    assert track in p.queue or p.current is track, "Bài hát phải được giữ lại khi chưa có voice client"


def test_dispatch_next_plays_when_vc_connected():
    """Đường bình thường vẫn phải pop và phát (bảo đảm fix không chặn nhầm)."""

    async def _scenario():
        cog = _FakeCog()
        vc = _FakeVC(connected=True)
        p = _make_player(vc=vc, cog=cog)
        track = _M().Track({"title": "phát", "duration": 10})
        p.queue.append(track)
        played = []

        async def _fake_play(t, seek_offset=0):
            played.append(t)

        p._play = _fake_play
        await p._dispatch_next_async()
        return p, track, played

    p, track, played = asyncio.run(_scenario())
    assert played == [track] and p.queue == []


def test_player_reconnecting_flag():
    async def _scenario():
        p = _make_player()
        p._recovering = True
        p.set_reconnecting(True)
        assert p._is_reconnecting is True and p._recovering is True
        p.set_reconnecting(False)
        assert p._is_reconnecting is False and p._recovering is False

    asyncio.run(_scenario())


# ─── Embeds ────────────────────────────────────────────────────────────────────

def test_make_np_embed_contains_track_and_thumbnail():
    m = _M()
    track = m.Track(
        {
            "title": "Bài Test",
            "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
            "duration": 180,
            "thumbnail": "https://i/t.jpg",
            "uploader": "Uploader",
        }
    )
    embed = m._make_np_embed(track, [], 0, 1.0, 30, {})
    assert "Bài Test" in embed.description
    assert embed.thumbnail.url == "https://i/t.jpg"
    # Live stream hiển thị badge LIVE
    live = m.Track({"title": "live", "duration": 0})
    assert "LIVE" in m._make_np_embed(live, [], 0, 1.0, 0, {}).description


def test_music_control_view_builds_buttons():
    m = _M()

    async def _scenario():
        p = _make_player()
        p.current = m.Track({"title": "x", "duration": 60})
        view = m.MusicControlView(p, {})
        labels = [c.label for c in view.children if getattr(c, "label", None)]
        # 5 nút điều khiển cốt lõi phải còn (autoplay/pause/skip/loop/stop)
        assert len(view.children) >= 5
        assert all(isinstance(x, str) for x in labels)

    asyncio.run(_scenario())

"""Tests Phase 5 — độ bền music, index nóng, và ops watchdog.

Nguyên tắc: kiểm TRA HIỆU ỨNG quan sát được (bot rời kênh, query dùng index, ffmpeg
được dọn), không đọc cờ nội bộ.
"""
import asyncio
import sqlite3
import time

import pytest


# ─── H9: auto-leave không còn bị chặn bởi `current` cũ ────────────────────────

def _player(tmp_path):
    import sys, os

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (BASE, os.path.join(BASE, "bot")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import cogs.music as m

    class FakeVC:
        def __init__(self, playing=False, paused=False, connected=True):
            self._p, self._pa, self._c = playing, paused, connected
            self.stop_calls = 0
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

    vc = FakeVC(playing=True)
    vc.client = type("C", (), {"loop": asyncio.get_running_loop()})()
    player = m.MusicPlayer(FakeGuild(), None, vc, cog=FakeCog())
    return player, vc


def _make_track(player):
    import music.player as P

    return P.Track({"title": "bai cuoi", "webpage_url": "https://youtu.be/z", "duration": 100})


class _FakeClock:
    """time.monotonic() nhảy nhanh để chạy hết countdown trong vài ms."""

    def __init__(self, step):
        self.step = step
        self.now = 1000.0

    def monotonic(self):
        self.now += self.step
        return self.now

    def time(self):
        return self.now


async def test_auto_leave_fires_when_queue_went_empty(temp_db, monkeypatch):
    """Bug: `_on_queue_empty` để `current` cũ, còn countdown mở đầu bằng
    `if self.current or self.queue: return` -> bot ngồi lại kênh voice vĩnh viễn."""
    import music.player as P

    player, vc = _player(temp_db)
    player.text_channel = None
    # Đây chính là trạng thái gây bug: bài đã phát xong nhưng `current` còn nguyên,
    # hàng đợi rỗng. Countdown mở đầu bằng `if self.current or self.queue: return`.
    player.current = P_Track = player.__class__ and None
    player.current = _make_track(player)
    player.queue = []
    await player._on_queue_empty()
    assert player.current is None, "_on_queue_empty phải xóa current để auto-leave chạy được"

    stops = []

    async def fake_stop():
        stops.append(True)

    player.stop = fake_stop
    monkeypatch.setattr(P, "INACTIVITY_TIMEOUT", 0)
    monkeypatch.setattr(P, "time", _FakeClock(step=9999))
    await player._inactivity_countdown()
    assert stops, "countdown không rời kênh dù không còn bài nào để phát"


async def test_auto_leave_does_not_fire_while_playing(temp_db, monkeypatch):
    import music.player as P

    player, vc = _player(temp_db)
    player.text_channel = None
    keeps_playing = object()
    player.current = keeps_playing
    player._start_inactivity_timer()

    stops = []

    async def fake_stop():
        stops.append(True)

    player.stop = fake_stop
    monkeypatch.setattr(P, "INACTIVITY_TIMEOUT", 0)
    monkeypatch.setattr(P, "time", _FakeClock(step=9999))
    await player._inactivity_countdown()
    assert not stops, "đang có bài phát mà bot rời kênh là lỗi mới"


# ─── H10: NP embed sống sót khi không còn bài nào ─────────────────────────────

def test_np_embed_handles_missing_track():
    import discord
    from music.embeds import _make_np_embed

    embed = _make_np_embed(None, [], 0, 1.0, 0, {})
    assert isinstance(embed, discord.Embed)
    assert embed.description, "embed rỗng không có nội dung"


def test_np_embed_still_renders_normal_track():
    from music.embeds import _make_np_embed
    from music.player import Track

    track = Track({"title": "Bài hát", "webpage_url": "https://youtu.be/x", "duration": 200})
    embed = _make_np_embed(track, [], 0, 1.0, 60, {})
    assert "Bài hát" in embed.description


# ─── H8: ffmpeg source được dọn trên nhánh lỗi ────────────────────────────────

async def test_play_error_path_cleans_orphan_ffmpeg_source(temp_db, monkeypatch):
    import music.player as P

    player, vc = _player(temp_db)
    player.text_channel = None
    cleaned = []

    class ExplodingSource:
        def cleanup(self):
            cleaned.append(True)

    monkeypatch.setattr(P.discord, "FFmpegOpusAudio", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("opus path unavailable")))
    # Nguồn PCM tạo thành công (đã Popen ffmpeg), nhưng bước SAU đó lỗi nên
    # `vc.play(source)` chưa bao giờ chạy -> không có audio thread nào cleanup hộ.
    monkeypatch.setattr(P.discord, "FFmpegPCMAudio", lambda *a, **k: ExplodingSource())
    monkeypatch.setattr(P.discord.opus, "is_loaded", lambda: False)
    monkeypatch.setattr(P, "load_opus_library", lambda: (_ for _ in ()).throw(RuntimeError("libopus missing")))

    track = P.Track({"title": "x", "webpage_url": "https://youtu.be/x", "duration": 100,
                     "stream_url": "https://cdn.example/a.m4a"})
    await player._play(track)
    assert cleaned, "source đã tạo mà không được cleanup -> tiến trình ffmpeg mồ côi"


# ─── H7: _ensure không tạo hai player cho một guild ───────────────────────────

async def test_concurrent_ensure_creates_a_single_player(temp_db, monkeypatch):
    import music.cog_voice as CV

    class FakeVoiceState:
        def __init__(self, channel):
            self.channel = channel
            self.self_deaf = True

    class FakeTextChannel:
        id = 999

    class FakeVoiceChannel:
        id = 555

        async def connect(self, self_deaf=False):
            await asyncio.sleep(0.05)          # mở cửa sổ race như connect thật
            vc = _player(None)[0].vc.__class__()
            vc.client = type("C", (), {"loop": asyncio.get_running_loop()})()
            return vc

    class FakeMember:
        def __init__(self):
            self.voice = FakeVoiceState(FakeVoiceChannel())

    class FakeBotUser:
        voice = None

    class FakeGuild:
        id = 424242
        me = FakeBotUser()

        def __init__(self):
            self.voice_client = None

    class FakeCtx:
        def __init__(self):
            self.guild = FakeGuild()
            self.author = FakeMember()
            self.channel = FakeTextChannel()
            self.sent = []

        async def send(self, *a, **k):
            self.sent.append(a)

    cog = CV.VoiceLifecycleMixin.__new__(CV.VoiceLifecycleMixin)
    import cogs.music as m

    cog = m.Music.__new__(m.Music)
    cog._players = {}
    cog._player_locks = {}
    cog._registry_lock = asyncio.Lock()
    cog._connecting = set()
    cog._bg_tasks = set()
    cog._empty_voice_tasks = {}
    cog._reconnect_tasks = {}
    cog._grace_tasks = {}

    monkeypatch.setattr(CV, "MAX_PLAYERS", 6)
    ctx = FakeCtx()
    players = await asyncio.gather(cog._ensure(ctx), cog._ensure(ctx), cog._ensure(ctx))
    created = [p for p in players if p is not None]
    assert len(cog._players) == 1, f"tạo {len(cog._players)} player cho MỘT guild"
    assert all(p is list(cog._players.values())[0] for p in created), "các request đồng thời nhận player khác nhau"


async def test_ensure_respects_max_players_under_concurrency(temp_db, monkeypatch):
    import cogs.music as m
    import music.cog_voice as CV

    calls = {"n": 0}

    class FakeVoiceChannel:
        id = 555

        async def connect(self, self_deaf=False):
            await asyncio.sleep(0.01)
            return _player(None)[0].vc.__class__()

    class FakeMember:
        def __init__(self):
            self.voice = type("V", (), {"channel": FakeVoiceChannel()})()

    class FakeCtx:
        def __init__(self, gid):
            self.guild = type("G", (), {"id": gid, "me": type("M", (), {"voice": None})(),
                                        "voice_client": None})()
            self.author = FakeMember()
            self.channel = type("C", (), {"id": 1})()
            self.sent = []

        async def send(self, *a, **k):
            self.sent.append(a)

    cog = m.Music.__new__(m.Music)
    cog._players = {}
    cog._player_locks = {}
    cog._registry_lock = asyncio.Lock()
    cog._connecting = set()
    monkeypatch.setattr(CV, "MAX_PLAYERS", 2)

    results = await asyncio.gather(*[cog._ensure(FakeCtx(1000 + i)) for i in range(6)])
    accepted = sum(1 for r in results if r is not None)
    assert accepted <= 2, f"vượt trần MAX_PLAYERS=2: {accepted} player được tạo"


# ─── H6: index đường nóng ─────────────────────────────────────────────────────

EXPECTED_INDEXES = [
    "idx_custom_commands_guild", "idx_economy_shop_guild_price", "idx_giveaways_message",
    "idx_giveaways_ended", "idx_reminders_due", "idx_reminders_user",
    "idx_mod_warnings_target", "idx_automod_warnings_target", "idx_playlist_tracks_playlist",
    "idx_playlists_guild", "idx_ticket_buttons_panel", "idx_rr_items_panel",
    "idx_tempvoice_guild", "idx_saved_embeds_guild", "idx_birthdays_month_day",
    "idx_support_threads_status", "idx_ticket_panels_guild", "idx_rr_panels_guild",
]


def test_hot_indexes_created(temp_db):
    import database  # temp_db fixture đã chạy init_db

    with sqlite3.connect(temp_db) as conn:
        names = {r[0] for r in conn.execute("select name from sqlite_master where type='index'")}
    missing = [i for i in EXPECTED_INDEXES if i not in names]
    assert not missing, f"thiếu index nóng: {missing}"


def test_hot_queries_use_indexes_not_scans(temp_db):
    """EXPLAIN QUERY PLAN là bằng chứng duy nhất có nghĩa trên thiết bị yếu."""
    queries = {
        "custom_commands (mỗi tin nhắn)": "select * from custom_commands where guild_id='1' and is_enabled=1",
        "economy_shop order by price": "select * from economy_shop where guild_id='1' order by price limit 20",
        "giveaways by message_id": "select * from giveaways where message_id='1'",
        "reminders đến hạn": "select * from reminders where remind_at <= 1",
        "mod_warnings count": "select count(*) from mod_warnings where guild_id='1' and user_id='2'",
        "playlist tracks": "select * from music_playlist_tracks where playlist_id=1 order by position",
        "birthdays hôm nay": "select * from user_birthdays where month=10 and day=9",
        "support threads open": "select * from support_threads where status='open' order by updated_at desc limit 50",
    }
    bad = []
    with sqlite3.connect(temp_db) as conn:
        for name, q in queries.items():
            plan = "; ".join(r[3] for r in conn.execute("explain query plan " + q))
            if plan.startswith("SCAN") or "TEMP B-TREE" in plan:
                bad.append(f"{name}: {plan}")
    assert not bad, "vẫn còn quét toàn bảng:\n" + "\n".join(bad)


# ─── H13/H14: watchdog ────────────────────────────────────────────────────────

def _watchdog_text():
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "watchdog.sh"
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_log_rotation_uses_copytruncate_not_mv():
    """`mv` đổi inode trong khi bot/dashboard vẫn giữ fd -> chúng ghi tiếp vào file .1,
    file mới vĩnh viễn rỗng và .1 phình đến đầy thẻ nhớ."""
    text = _watchdog_text()
    assert 'mv -f "$f"' not in text, "rotation vẫn dùng mv -> vô hiệu với fd đang mở"
    assert 'cp -f "$f" "$f.1"' in text and ': > "$f"' in text


def test_watchdog_restarts_dashboard_when_http_silent():
    """Dashboard chết = curl không lấy được mã HTTP nào; nhánh 503 cũ không bao giờ chạy,
    nên site nằm ngoài vô thời hạn trong khi bot vẫn khỏe."""
    text = _watchdog_text()
    assert "restart_dashboard()" in text
    assert '"000"' in text, "không phân biệt dashboard im lặng với bot offline"
    assert "DASH_PID_FILE" in text.split("restart_dashboard()")[1][:900]


def test_health_rejects_stale_pid_file(tmp_path):
    """PID có thể bị tái sử dụng sau reboot; chỉ kill -0 là chưa đủ."""
    # Kiểm tra watchdog vẫn đối chiếu cổng HTTP chứ không tin mỗi PID file.
    text = _watchdog_text()
    assert "127.0.0.1:5000/health" in text

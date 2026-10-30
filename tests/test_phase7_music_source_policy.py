"""Phase 7 — Source policy: ưu tiên Opus audio-only, fallback android an toàn.

Bối cảnh production 2026-10-30: client `android` chỉ trả format 18 (MP4 444 kbps
có video), nên mọi bài đều đi PCM + libopus (`opus_copy=False`). Client `default`
trả Opus 251 (128.93 kbps) nhưng cần cookie/PO token, nếu không sẽ bị
"Sign in to confirm you're not a bot". Vì vậy policy phải:
- auto: chỉ thử primary khi có cookie; primary lỗi/không audio-only thì fallback compat.
- opus: bắt buộc primary + audio-only Opus, không fallback (dùng cho PO token).
- compat: giữ nguyên hành vi android cũ để rollback.
Cache `song_info` phải tách theo mode + cookie để không dùng lại URL format 18
sau khi đã cấu hình cookie.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot"), os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import music.config as C  # noqa: E402
import music.extractor as E  # noqa: E402


def _fmt(url, acodec, vcodec, **extra):
    fmt = {"url": url, "acodec": acodec, "vcodec": vcodec, "protocol": "https"}
    fmt.update(extra)
    return fmt


OPUS = _fmt(
    "https://cdn/a.webm", "opus", "none",
    format_id="251", abr=128.93, asr=48000, audio_channels=2,
)
MUXED = _fmt(
    "https://cdn/v.mp4", "mp4a.40.2", "avc1",
    format_id="18", tbr=444.226,
)
AAC_ONLY = _fmt(
    "https://cdn/a.m4a", "mp4a.40.2", "none",
    format_id="140", abr=129.5, asr=44100,
)
HLS_OPUS = _fmt(
    "https://cdn/a.m3u8", "opus", "none",
    format_id="hls", protocol="m3u8_native",
)


def _info(*formats, **extra):
    info = {
        "title": "Test",
        "id": "abc12345678",
        "webpage_url": "https://youtu.be/abc12345678",
        "duration": 200,
        "formats": list(formats),
    }
    info.update(extra)
    return info


# ─── Nhận diện format ─────────────────────────────────────────────────────────

def test_selected_audio_only_detection():
    assert E._selected_is_audio_only(_info(OPUS)) is True
    assert E._selected_is_audio_only(_info(AAC_ONLY)) is True
    assert E._selected_is_audio_only(_info(MUXED)) is False
    assert E._selected_is_audio_only(_info(MUXED, OPUS)) is True
    assert E._selected_is_audio_only(_info(HLS_OPUS)) is True
    assert E._selected_is_audio_only(_info()) is False
    assert E._selected_is_audio_only(None) is False


def test_selected_opus_detection():
    assert E._selected_is_opus(_info(OPUS)) is True
    assert E._selected_is_opus(_info(HLS_OPUS)) is True
    assert E._selected_is_opus(_info(AAC_ONLY)) is False
    assert E._selected_is_opus(_info(MUXED)) is False


def test_get_stream_url_prefers_highest_opus_abr():
    """yt-dlp chọn 251 (128.93 kbps) nhưng list formats có 249/250 trước; phải lấy 251."""
    f249 = _fmt("https://cdn/a249.webm", "opus", "none", format_id="249", abr=46.234, asr=48000)
    f250 = _fmt("https://cdn/a250.webm", "opus", "none", format_id="250", abr=61.149, asr=48000)
    f251 = _fmt("https://cdn/a251.webm", "opus", "none", format_id="251", abr=128.93, asr=48000)
    assert E._get_stream_url(_info(f249, f250, f251)) == f251["url"]


def test_selected_audio_only_resolves_playlist_entries():
    assert E._selected_is_audio_only({"entries": [_info(OPUS)]}) is True
    assert E._selected_is_audio_only({"entries": [_info(MUXED)]}) is False
    assert E._selected_is_audio_only({"entries": []}) is False


# ─── Fallback policy ──────────────────────────────────────────────────────────

def test_auto_prefers_primary_audio_only(monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(OPUS) if mode == "primary" else _info(MUXED)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "auto")
    assert used == "primary"
    assert calls == ["primary"], calls
    assert E._selected_is_opus(info) is True


def test_auto_falls_back_when_primary_is_muxed(monkeypatch):
    calls = []
    compat_info = _info(MUXED)

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(MUXED) if mode == "primary" else compat_info

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "auto")
    assert used == "compat"
    assert calls == ["primary", "compat"], calls
    assert info is compat_info


def test_auto_falls_back_when_primary_returns_none(monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return None if mode == "primary" else _info(OPUS)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "auto")
    assert used == "compat"
    assert calls == ["primary", "compat"], calls
    assert E._selected_is_opus(info) is True


def test_auto_accepts_primary_audio_only_aac(monkeypatch):
    """Audio-only AAC vẫn tốt hơn format 18 (không tải video); chỉ encode là còn tốn CPU."""
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(AAC_ONLY)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "auto")
    assert used == "primary"
    assert calls == ["primary"], calls
    assert E._selected_is_opus(info) is False


def test_compat_never_calls_primary(monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(MUXED)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    _info_out, used = E._extract_with_fallback("q", "compat")
    assert used == "compat"
    assert calls == ["compat"], calls


def test_opus_mode_rejects_non_opus_and_does_not_fallback(monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(AAC_ONLY)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "opus")
    assert info is None
    assert used == "primary"
    assert calls == ["primary"], calls


def test_opus_mode_accepts_opus(monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(OPUS)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    info, used = E._extract_with_fallback("q", "opus")
    assert used == "primary"
    assert calls == ["primary"], calls
    assert E._selected_is_opus(info) is True


# ─── Chọn có thử primary hay không ───────────────────────────────────────────

def test_should_try_primary_depends_on_mode_and_cookie(monkeypatch):
    monkeypatch.setattr(E, "primary_ready", lambda: False)
    assert E._should_try_primary("auto") is False
    assert E._should_try_primary("opus") is True
    assert E._should_try_primary("compat") is False

    monkeypatch.setattr(E, "primary_ready", lambda: True)
    assert E._should_try_primary("auto") is True


# ─── Health / cooldown ───────────────────────────────────────────────────────

def test_primary_health_cooldown_and_recovery(monkeypatch):
    E._reset_primary_health()
    monkeypatch.setattr(E, "_PRIMARY_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(E, "_PRIMARY_COOLDOWN_SECONDS", 60)

    assert E._primary_available() is True
    E._note_primary_result(False)
    assert E._primary_available() is True, "1 lỗi chưa được mở cooldown"
    E._note_primary_result(False)
    assert E._primary_available() is False, "đủ ngưỡng phải mở cooldown"

    E._note_primary_result(True)
    assert E._primary_available() is True, "thành công phải reset cooldown"
    E._reset_primary_health()


# ─── Cache tag ───────────────────────────────────────────────────────────────

def test_primary_options_do_not_hardcode_android_client():
    """Primary phải dùng default client pool; compat mới giữ android."""
    assert "extractor_args" not in C.YDL_OPTS_PRIMARY, (
        "YDL_OPTS_PRIMARY còn extractor_args -> vẫn bị ép android và không bao giờ có audio-only"
    )
    assert C.YDL_OPTS["extractor_args"]["youtube"]["player_client"] == ["android"]


def test_cookie_is_only_attached_to_primary_opts(tmp_path):
    """Cookie không được gắn vào compat/flat: android + cookie fail extract."""
    import json
    import os
    import subprocess
    import sys

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    code = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "bot"))
import music.config as C
print("RESULT:" + json.dumps({
    "compat": C.YDL_OPTS.get("cookiefile"),
    "flat": C.YDL_OPTS_FLAT.get("cookiefile"),
    "primary": C.YDL_OPTS_PRIMARY.get("cookiefile"),
}))
'''
    env = os.environ.copy()
    env["YTDLP_COOKIEFILE"] = str(cookie)
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    line = [ln for ln in res.stdout.splitlines() if ln.startswith("RESULT:")][-1]
    data = json.loads(line[len("RESULT:"):])
    assert data["primary"] == str(cookie), data
    assert data["compat"] is None, f"compat/android không được dùng cookie: {data}"
    assert data["flat"] is None, f"flat/android không được dùng cookie: {data}"


def test_source_cache_tag_changes_with_mode_and_cookie(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(C, "_COOKIE_FILE", str(cookie))
    monkeypatch.setenv("MUSIC_SOURCE_MODE", "auto")

    tag_auto = C.source_cache_tag()
    assert C.primary_ready() is True
    assert "auto-c-" in tag_auto, tag_auto

    monkeypatch.setenv("MUSIC_SOURCE_MODE", "compat")
    tag_compat = C.source_cache_tag()
    assert tag_compat != tag_auto
    assert "compat-c-" in tag_compat, tag_compat

    monkeypatch.setattr(C, "_COOKIE_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.setenv("MUSIC_SOURCE_MODE", "auto")
    assert C.primary_ready() is False
    assert "auto-n-0" == C.source_cache_tag()


def test_song_info_cache_key_is_isolated_by_tag(monkeypatch):
    monkeypatch.setattr(E, "source_cache_tag", lambda: "auto-c-111")
    key_a = E._song_info_cache_key("Same Query")
    monkeypatch.setattr(E, "source_cache_tag", lambda: "compat-n-0")
    key_b = E._song_info_cache_key("Same Query")
    assert key_a != key_b
    assert key_a.startswith("song_info:auto-c-111:")
    assert key_b.startswith("song_info:compat-n-0:")


# ─── extract_info: không thử primary khi chưa có cookie ──────────────────────

async def test_extract_info_skips_primary_without_cookie(temp_db, monkeypatch):
    calls = []

    def fake_extract(query, mode="compat"):
        calls.append(mode)
        return _info(OPUS)

    monkeypatch.setattr(E, "_extract_sync", fake_extract)
    monkeypatch.setattr(E, "get_source_mode", lambda: "auto")
    monkeypatch.setattr(E, "primary_ready", lambda: False)
    monkeypatch.setattr(E, "source_cache_tag", lambda: "auto-n-0")

    out = await E.extract_info(f"ytsearch1:no-cookie-{time.time_ns()}")
    assert out and out["is_opus"] is True
    assert calls == ["compat"], calls


async def test_extract_info_uses_primary_and_notes_success(temp_db, monkeypatch):
    notes = []
    monkeypatch.setattr(E, "get_source_mode", lambda: "auto")
    monkeypatch.setattr(E, "primary_ready", lambda: True)
    monkeypatch.setattr(E, "_primary_available", lambda: True)
    monkeypatch.setattr(E, "_extract_with_fallback", lambda q, m: (_info(OPUS), "primary"))
    monkeypatch.setattr(E, "_note_primary_result", lambda ok: notes.append(ok))
    monkeypatch.setattr(E, "source_cache_tag", lambda: "auto-c-111")

    out = await E.extract_info(f"ytsearch1:primary-{time.time_ns()}")
    assert out and out["is_opus"] is True
    assert notes == [True], notes


async def test_extract_info_notes_failure_and_uses_compat(temp_db, monkeypatch):
    notes = []
    monkeypatch.setattr(E, "get_source_mode", lambda: "auto")
    monkeypatch.setattr(E, "primary_ready", lambda: True)
    monkeypatch.setattr(E, "_primary_available", lambda: True)
    monkeypatch.setattr(E, "_extract_with_fallback", lambda q, m: (_info(MUXED), "compat"))
    monkeypatch.setattr(E, "_note_primary_result", lambda ok: notes.append(ok))
    monkeypatch.setattr(E, "source_cache_tag", lambda: "auto-c-111")

    out = await E.extract_info(f"ytsearch1:fallback-{time.time_ns()}")
    assert out is not None
    assert out["is_opus"] is False
    assert notes == [False], notes

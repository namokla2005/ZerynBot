"""
test_music_smoke.py — Smoke test cho music.py (yt-dlp config, helper, load cog).

Mục tiêu:
- Đảm bảo cog Music load được lên Bot giả (không network).
- Chặn hồi quy cấu hình yt-dlp: player_client phải là bộ nhanh (tv/web_safari),
  không còn dùng "web" (bị YouTube throttle -> chậm 3-6s).
- Đảm bảo đã giảm ffmpeg probe (P0.3) và helper _get_stream_acodec tồn tại (P2).
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (BASE_DIR, os.path.join(BASE_DIR, "bot")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import():
    import cogs.music as M
    return M


def test_ytdl_client_is_stable():
    M = _import()
    clients = M.YDL_OPTS["extractor_args"]["youtube"]["player_client"]
    assert "android" in clients, f"player_client phải có 'android': {clients}"
    assert "tv" not in clients, f"Không dùng client 'tv' (bị lỗi 'The page needs to be reloaded'): {clients}"


def test_ffmpeg_probe_reduced():
    M = _import()
    before = M.FFMPEG_BEFORE
    # probesize/analyzeduration an toàn hơn 1M/1000000 ban đầu, nhưng thấp hơn để nhanh
    assert "probesize 512K" in before, f"probesize phải là 512K: {before}"
    assert "analyzeduration 500000" in before, f"analyzeduration phải là 500000: {before}"
    # Cần +genpts để chống drift PTS ("lúc nhanh lúc chậm")
    assert "+genpts" in before, f"phải có +genpts để ổn định timestamp: {before}"


def test_ffmpeg_anti_drift_encode():
    M = _import()
    # Nhánh encode lại (không copy) phải có aresample async để bù lệch PTS
    assert "aresample=async=1" in M.FFMPEG_OPTS_ENCODE, M.FFMPEG_OPTS_ENCODE
    # Nhánh copy Opus WebM KHÔNG được có -af (xung đột với -c:a copy)
    assert "-af" not in M.FFMPEG_OPTS_COPY, M.FFMPEG_OPTS_COPY


def test_opus_acodec_helper_exists():
    M = _import()
    assert callable(M._get_stream_acodec)
    # heuristic fallback: chuỗi webm -> opus
    assert M._get_stream_acodec({"formats": []}, "https://x/mime=audio%2Fwebm") == "opus"
    assert M._get_stream_acodec({"formats": []}, "") == ""


def test_music_cog_loads_on_dummy_bot():
    import discord
    from discord.ext import commands, tasks

    tasks.Loop.start = lambda self, *a, **k: None
    bot = commands.Bot(command_prefix="/", intents=discord.Intents.none(), help_command=None)

    async def load():
        await bot.load_extension("cogs.music")

    import asyncio
    asyncio.run(load())
    asyncio.run(bot.close())

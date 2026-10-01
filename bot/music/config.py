"""
config.py — Hằng số & cấu hình yt-dlp/FFmpeg của module nhạc.

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). KHÔNG chứa logic nghiệp vụ — chỉ
hằng số + helper tạo YoutubeDL thread-local. Mọi module khác import từ đây để
đảm bảo chỉ có MỘT bản duy nhất của YDL_OPTS / semaphore / thread-local.
"""

import asyncio
import logging
import os
import threading

import discord
import yt_dlp

log = logging.getLogger("BotV2.Music")


try:
    from bot.bot import load_opus_library
except ImportError:
    try:
        from bot import load_opus_library
    except ImportError:
        def load_opus_library() -> bool:
            return discord.opus.is_loaded()

load_opus_library()

FFMPEG_BEFORE = (
    "-loglevel error "
    "-nostdin "
    "-rw_timeout 10000000 "
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_on_network_error 1 "
    "-reconnect_on_http_error 4xx,5xx "
    "-reconnect_delay_max 2 "
    "-fflags +genpts "
    "-probesize 512K "
    "-analyzeduration 500000 "
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"'
)
#   -c:a copy                  : Chỉ cho nhánh copy luồng Opus WebM (không resample)
FFMPEG_OPTS_COPY   = "-vn -sn -c:a copy -threads 1"
#   -vn -sn -threads 1         : Nhánh encode lại sang Opus 48k (không resample làm biến dạng tốc độ/cao độ).
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1"

MAX_PLAYERS = 6  # Giới hạn player đồng thời (tối ưu cho tablet/phone 4-6GB, 10+ server)
MAX_BG_LOAD = 50  # Giới hạn số bài nạp ngầm từ playlist (bảo vệ RAM/CPU)
MAX_QUEUE_SIZE = 100  # Giới hạn hàng đợi tối đa mỗi server (chống DoS / tràn RAM)

def _lower_process_priority(proc, niceness: int = 10) -> None:
    """Hạ độ ưu tiên CPU của tiến trình ffmpeg con trên Linux/Termux để không tranh chấp với Bot event loop."""
    if proc is None or getattr(proc, "pid", None) is None:
        return
    try:
        if hasattr(os, "setpriority") and hasattr(os, "PRIO_PROCESS"):
            os.setpriority(os.PRIO_PROCESS, proc.pid, niceness)
    except (PermissionError, ProcessLookupError, OSError):
        pass

_COOKIE_FILE = os.environ.get("YTDLP_COOKIEFILE", None)

YDL_OPTS = {
    "format": "bestaudio[ext=webm][acodec=opus]/bestaudio[protocol^=http][abr<=160]/bestaudio[protocol^=http]/bestaudio[abr<=160]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "socket_timeout": 5,
    "extractor_args": {
        "youtube": {
            # Dùng client "android" thuần túy — tương thích 100% video/live stream, không bị bot verification như client "web".
            "player_client": ["android"],
            "player_skip": ["configs", "webpage"],
        }
    },
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "skip_download": True,
}
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    YDL_OPTS["cookiefile"] = _COOKIE_FILE

YDL_OPTS_FLAT = {
    "extract_flat": True,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "socket_timeout": 5,
    "extractor_args": {
        "youtube": {
            "player_client": ["android"],
            "player_skip": ["configs", "webpage"],
        }
    },
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
}
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    YDL_OPTS_FLAT["cookiefile"] = _COOKIE_FILE

_extract_semaphore = asyncio.Semaphore(4)

_thread_local = threading.local()

def _get_ydl() -> yt_dlp.YoutubeDL:
    """Thread-local YoutubeDL instance (tái sử dụng connection pool theo từng luồng, 100% thread-safe)."""
    ydl = getattr(_thread_local, "ydl", None)
    if ydl is None:
        ydl = yt_dlp.YoutubeDL(YDL_OPTS)
        _thread_local.ydl = ydl
    return ydl


def _get_ydl_flat() -> yt_dlp.YoutubeDL:
    """Thread-local Flat-Extraction YoutubeDL instance (< 1s metadata)."""
    ydl = getattr(_thread_local, "ydl_flat", None)
    if ydl is None:
        ydl = yt_dlp.YoutubeDL(YDL_OPTS_FLAT)
        _thread_local.ydl_flat = ydl
    return ydl

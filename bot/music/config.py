"""
config.py — Hằng số & cấu hình yt-dlp/FFmpeg của module nhạc.

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). KHÔNG chứa logic nghiệp vụ — chỉ
hằng số + helper tạo YoutubeDL thread-local. Mọi module khác import từ đây để
đảm bảo chỉ có MỘT bản duy nhất của YDL_OPTS / semaphore / thread-local.
"""

import asyncio
import logging
import os
import re
import subprocess
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

# Nền tảng: bắt buộc có với mọi build FFmpeg.
FFMPEG_BEFORE_HEAD = (
    "-loglevel error "
    "-nostdin "
    "-rw_timeout 10000000 "
    "-reconnect 1 "
    "-reconnect_streamed 1 "
)
# HTTP auto-reconnect: chỉ tồn tại từ FFmpeg 5.0 (protocol `http`).
FFMPEG_BEFORE_HTTP_RECONNECT = (
    "-reconnect_on_network_error 1 "
    "-reconnect_on_http_error 5xx "
)
FFMPEG_BEFORE_TAIL = (
    "-reconnect_delay_max 2 "
    "-fflags +genpts "
    "-probesize 512K "
    "-analyzeduration 500000 "
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"'
)


def build_ffmpeg_before(http_reconnect: bool = True) -> str:
    """Ghép `before_options` cho FFmpeg theo đúng năng lực của build đang chạy.

    Thứ tự cờ giữ NGUYÊN như bản cũ để `http_reconnect=True` trả về chuỗi giống hệt
    cấu hình đã chạy ổn định trên Termux.
    """
    middle = FFMPEG_BEFORE_HTTP_RECONNECT if http_reconnect else ""
    return FFMPEG_BEFORE_HEAD + middle + FFMPEG_BEFORE_TAIL


def parse_ffmpeg_major(banner: str) -> int | None:
    """`ffmpeg version n6.1.1` → 6; `ffmpeg version 4.4.4-0+deb11u1` → 4; không đọc được → None."""
    m = re.search(r"ffmpeg version n?(\d+)", banner or "")
    return int(m.group(1)) if m else None


def ffmpeg_http_reconnect_supported(executable: str = "ffmpeg") -> bool:
    """`-reconnect_on_network_error` / `-reconnect_on_http_error` chỉ có từ FFmpeg 5.0.

    Trên build 4.x FFmpeg báo `Option not found` và THOÁT NGAY khi mở source, nghĩa là
    mọi lệnh /play chết hàng loạt trên máy còn FFmpeg cũ (Termux/Debian oldstable) chứ
    không chỉ mất tính năng tự reconnect. Probe `ffmpeg -version` một lần lúc import.
    """
    try:
        res = subprocess.run(
            [executable, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 — không chặn được bot khởi động vì một probe
        log.warning(f"[Music] Không probe được ffmpeg -version ({exc}) → bỏ cờ reconnect HTTP")
        return False
    major = parse_ffmpeg_major(res.stdout or "")
    if major is None:
        log.warning("[Music] Không parse được version ffmpeg → bỏ cờ reconnect HTTP")
        return False
    if major < 5:
        log.warning(
            f"[Music] FFmpeg {major}.x không hỗ trợ -reconnect_on_network_error/-reconnect_on_http_error "
            "→ dùng bộ cờ nền để tránh sập toàn bộ playback."
        )
        return False
    return True


HTTP_RECONNECT_SUPPORTED = ffmpeg_http_reconnect_supported()
FFMPEG_BEFORE = build_ffmpeg_before(HTTP_RECONNECT_SUPPORTED)

# ── Stream watchdog: phát hiện FFmpeg treo mà voice vẫn "connected" ───────────
# discord.py chỉ báo `after()` khi source trả về data rỗng (EOF) hoặc process exit.
# Nếu ffmpeg kẹt trong một lần đọc pipe (mạng chập chờn, CDN giữ kết nối nhưng không
# xuất bytes) thì audio thread kẹt theo: không after(), không recovery, người dùng
# nghe im lặng vô hạn và bot vẫn chiếm slot MAX_PLAYERS.
STALL_TIMEOUT_SECONDS = max(10.0, float(os.getenv("MUSIC_STALL_TIMEOUT", "30")))
STALL_CHECK_SECONDS = max(1.0, float(os.getenv("MUSIC_STALL_CHECK_INTERVAL", "5")))
# Trần thời gian chờ `source.cleanup()` (nó join tiến trình ffmpeg con). cleanup kẹt sẽ
# giữ `_recovering=True` vĩnh viễn và vô hiệu hóa toàn bộ recovery của player.
STALL_CLEANUP_TIMEOUT_SECONDS = max(1.0, float(os.getenv("MUSIC_STALL_CLEANUP_TIMEOUT", "5")))
AUDIO_FRAME_SECONDS = 0.02  # discord.py đọc từng frame 3840 byte = 20ms audio
# Bài "chết tức thì": stream EOF sau < 5s (duration=None nên is_premature không bắt).
FAST_FAIL_SECONDS = 5
FAST_FAIL_LIMIT = 3

#   -c:a copy                  : Chỉ cho nhánh copy luồng Opus WebM (không resample)
FFMPEG_OPTS_COPY   = "-vn -sn -c:a copy -threads 1"
#   -vn -sn -threads 1         : Nhánh encode lại sang Opus 48k (không resample làm biến dạng tốc độ/cao độ).
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1"

MAX_PLAYERS = 6  # Giới hạn player đồng thời (tối ưu cho tablet/phone 4-6GB, 10+ server)
MAX_BG_LOAD = 50  # Giới hạn số bài nạp ngầm từ playlist (bảo vệ RAM/CPU)
MAX_QUEUE_SIZE = 100  # Giới hạn hàng đợi tối đa mỗi server (chống DoS / tràn RAM)
INACTIVITY_TIMEOUT = int(os.getenv("MUSIC_INACTIVITY_TIMEOUT", "180"))  # Mặc định 180s (3 phút) theo yêu cầu người dùng

def _lower_process_priority(proc, niceness: int = 10) -> None:
    """Hạ độ ưu tiên CPU của tiến trình ffmpeg con trên Linux/Termux để không tranh chấp với Bot event loop (niceness=10 bảo vệ Discord Gateway heartbeat)."""
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

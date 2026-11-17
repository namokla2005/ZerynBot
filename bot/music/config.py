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


# Không probe ffmpeg NGAY tại import: subprocess.run(timeout=5) từng chặn event
# loop mỗi lần cog load. Khởi động với bộ cờ an toàn (không reconnect), probe ở
# thread nền rồi cập nhật; player đọc get_ffmpeg_before() tại thời điểm play.
HTTP_RECONNECT_SUPPORTED = False
FFMPEG_BEFORE = build_ffmpeg_before(False)


def get_ffmpeg_before() -> str:
    return FFMPEG_BEFORE


def _probe_ffmpeg_async() -> None:
    global HTTP_RECONNECT_SUPPORTED, FFMPEG_BEFORE
    supported = ffmpeg_http_reconnect_supported()
    HTTP_RECONNECT_SUPPORTED = supported
    FFMPEG_BEFORE = build_ffmpeg_before(supported)


threading.Thread(target=_probe_ffmpeg_async, name="ffmpeg-probe", daemon=True).start()

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

SOURCE_MODES = ("auto", "opus", "compat")


def get_source_mode() -> str:
    """`auto` = primary nếu có cookie rồi fallback compat; `opus` = bắt buộc Opus; `compat` = android cũ."""
    raw = (os.getenv("MUSIC_SOURCE_MODE") or "auto").strip().lower()
    return raw if raw in SOURCE_MODES else "auto"


def _cookie_file_ready() -> bool:
    return bool(_COOKIE_FILE and os.path.exists(_COOKIE_FILE))


def _cookie_fingerprint() -> tuple:
    try:
        stat = os.stat(_COOKIE_FILE) if _COOKIE_FILE else None
        return (_COOKIE_FILE, stat.st_mtime_ns, stat.st_size) if stat else (None, 0, 0)
    except OSError:
        return (None, 0, 0)


def _cookie_file_mtime() -> int:
    return _cookie_fingerprint()[1]


def primary_ready() -> bool:
    """Primary (`default` client) chỉ đáng thử khi có cookie.

    Không có cookie, YouTube trả "Sign in to confirm you're not a bot" cho mọi
    client trừ `android` — thử primary chỉ tốn 1-3s mỗi bài rồi vẫn phải fallback.
    """
    return _cookie_file_ready()


def source_cache_tag() -> str:
    """Khóa cache phải đổi khi mode/cookie đổi, tránh dùng lại URL format 18 đã cache."""
    path, mtime_ns, size = _cookie_fingerprint()
    if path is None:
        return f"{get_source_mode()}-n-0"
    return f"{get_source_mode()}-c-{mtime_ns}-{size}"


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
# Compat giữ nguyên client android: không cần auth nhưng hiện chỉ trả format 18
# (MP4 444 kbps có video) -> PCM + libopus. Chỉ dùng khi primary không khả dụng.
YDL_OPTS_COMPAT = YDL_OPTS
# Primary dùng default client pool của yt-dlp: có audio-only Opus 251 khi có cookie.
YDL_OPTS_PRIMARY = {k: v for k, v in YDL_OPTS.items() if k != "extractor_args"}
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    # CHỈ primary được dùng cookie. Android/compat + cookie trả
    # "Failed to extract any player response" trên Termux (đo 2026-10-30),
    # làm hỏng luôn nhánh fallback; compat phải chạy cookie-free.
    YDL_OPTS_PRIMARY["cookiefile"] = _COOKIE_FILE

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
# Flat extraction dùng android: không gắn cookie (android + cookie fail extract).

class _ExtractionCapacity:
    """Loop-independent admission; release belongs to the real worker, not its waiter."""

    def __init__(self):
        self._slots = threading.BoundedSemaphore(4)

    async def acquire(self):
        while not self._slots.acquire(blocking=False):
            await asyncio.sleep(0.01)
        return True

    def release(self):
        self._slots.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


# importlib.reload(config) must not split the permits held by live native workers.
if "_extract_semaphore" not in globals():
    _extract_semaphore = _ExtractionCapacity()

# Keep ownership here so reloading extractor/cog cannot orphan its pool/tasks/session.
class _ExtractionRuntime:
    def __init__(self):
        self.executor = None
        self.workers = set()
        self.lock = threading.Lock()
        self.inflight = {}
        self.jobs = set()
        self.generation = 0
        self.closing = False
        self.close_task = None
        self.close_generation = None
        self.retiring = None
        self.spotify_session = None


if "_extraction_runtime" not in globals():
    _extraction_runtime = _ExtractionRuntime()
if "_thread_local" not in globals():
    _thread_local = threading.local()

def _get_ydl() -> yt_dlp.YoutubeDL:
    """Thread-local YoutubeDL instance (tái sử dụng connection pool theo từng luồng, 100% thread-safe)."""
    ydl = getattr(_thread_local, "ydl", None)
    if ydl is None:
        ydl = yt_dlp.YoutubeDL(YDL_OPTS)
        _thread_local.ydl = ydl
    return ydl


def _get_ydl_primary() -> yt_dlp.YoutubeDL:
    """Thread-local YoutubeDL cho primary (`default` client + cookie nếu có)."""
    fingerprint = _cookie_fingerprint()
    ydl = getattr(_thread_local, "ydl_primary", None)
    if ydl is not None and getattr(_thread_local, "primary_cookie", None) != fingerprint:
        # Same worker thread, after its preceding extraction: never close an in-use jar.
        _thread_local.ydl_primary = None
        try:
            # YoutubeDL.close() saves its jar first. Never overwrite a refreshed file
            # with this retired instance's stale cookies; still close HTTP transports.
            params = getattr(ydl, "params", None)
            if params is not None:
                params["cookiefile"] = None
            ydl.close()
        except Exception:
            log.debug("[Music] Primary instance close failed")
        ydl = None
    if ydl is None:
        opts = {k: v for k, v in YDL_OPTS_PRIMARY.items() if k != "cookiefile"}
        if fingerprint[0] is not None:
            opts["cookiefile"] = fingerprint[0]
        ydl = yt_dlp.YoutubeDL(opts)
        _thread_local.ydl_primary = ydl
        _thread_local.primary_cookie = fingerprint
    return ydl


def _get_ydl_flat() -> yt_dlp.YoutubeDL:
    """Thread-local Flat-Extraction YoutubeDL instance (< 1s metadata)."""
    ydl = getattr(_thread_local, "ydl_flat", None)
    if ydl is None:
        ydl = yt_dlp.YoutubeDL(YDL_OPTS_FLAT)
        _thread_local.ydl_flat = ydl
    return ydl

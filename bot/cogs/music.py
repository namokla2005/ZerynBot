"""
music.py — High-Performance Optimized Music Cog for ARM & Termux (yt-dlp + FFmpegOpusAudio).
Không dùng Lavalink. Tối ưu tối đa cho thiết bị ARM yếu như Tablet, Raspberry Pi, Termux.

Tối ưu:
  - FFmpegOpusAudio tối ưu cờ buffer & -nostdin (< 0.8s start latency)
  - Tự động phân giải link Spotify qua oEmbed thành truy vấn YouTube tức thì
  - yt-dlp chạy trong thread pool với semaphore & đa client fallback (android, web_safari)
  - URL Cache 10 phút để tái sử dụng
  - Pre-load bài tiếp theo khi bài hiện tại đang chạy
  - Khóa đồng bộ chống xung đột phát nhạc (Atomic Play Lock)
  - Tự động rời voice sau 3 phút không hoạt động để giải phóng RAM/CPU
  - Hỗ trợ /volume (1-150%) và /shuffle (xáo trộn hàng chờ)
"""
import asyncio
import logging
import os
import random
import re
import threading
import time

import aiohttp
import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from datetime import datetime, timezone
from cache import cache
from database import (
    async_get_guild_settings,
    async_get_song_cache,
    async_set_song_cache,
    async_delete_song_cache,
    async_increment_stat,
    async_get_top_played_songs,
)
from i18n import tr

try:
    from emojis import e, embed_title, partial
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, partial

log = logging.getLogger("BotV2.Music")

# ─── Opus Library Discovery (Termux / Linux / Windows / macOS) ───────────────
try:
    from bot.bot import load_opus_library
except ImportError:
    try:
        from bot import load_opus_library
    except ImportError:
        def load_opus_library() -> bool:
            return discord.opus.is_loaded()

load_opus_library()

# ─── FFmpeg options tối ưu cho ARM (Đồng bộ PTS chống giật & lệch tốc độ) ─────
#   -rw_timeout 10000000     : Chặn treo đọc I/O FFmpeg khi chuyển đổi Wifi/4G hoặc mạng di động kém (10s)
#   -fflags +genpts          : Sinh PTS khi stream thiếu/nhảy timestamp → chống "lúc nhanh lúc chậm"
#   -probesize 512K / -analyzeduration 500000 : An toàn hơn 128K/250000 (tránh nhận sai demuxer
#                             cho luồng AAC/m4a), vẫn nhanh hơn nhiều so với 1M/1000000 ban đầu.
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

# ─── Stream lofi 24/7 ──────────────────────────────────────────────────────────
LOFI_STREAMS = {
    "soma": {
        "name": "SomaFM Groove Salad",
        "url": "https://ice1.somafm.com/groovesalad-128-mp3",
        "title": "🎧 SomaFM Groove Salad (Chill/Lofi)",
    },
    "youtube": {
        "name": "YouTube Lofi Girl",
        "url": "https://www.youtube.com/@LofiGirl/live",
        "title": "🎧 Lofi Girl 24/7 (YouTube)",
    },
}

# Autocomplete cho /lofi
async def lofi_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Gợi ý dropdown YouTube / SomaFM cho slash command /lofi."""
    choices = [
        app_commands.Choice(name="📺 YouTube Lofi Girl (live stream)", value="youtube"),
        app_commands.Choice(name="🎧 SomaFM Groove Salad (ổn định 24/7)", value="soma"),
    ]
    if current:
        choices = [c for c in choices if current.lower() in c.value.lower() or current.lower() in c.name.lower()]
    return choices[:25]


_COOKIE_FILE = os.environ.get("YTDLP_COOKIEFILE", None)

# Cấu hình yt-dlp tối ưu tốc độ & ưu tiên WebM Opus / Direct HTTP (tránh HLS m3u8 gây giật âm thanh trên SoundCloud)
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

# Cấu hình Flat Extraction siêu tốc (chỉ lấy metadata, timeout 2s)
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

# Thread-local persistent sessions để tái sử dụng connection pool theo luồng (100% thread-safe)
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



def _fmt_duration(seconds) -> str:
    if seconds is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        return "🔴 LIVE"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


_spotify_session: aiohttp.ClientSession | None = None


async def _get_spotify_session() -> aiohttp.ClientSession:
    """Tái sử dụng ClientSession cho Spotify resolve để giảm TCP handshake overhead."""
    global _spotify_session
    if _spotify_session is None or _spotify_session.closed:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        _spotify_session = aiohttp.ClientSession(headers=headers)
    return _spotify_session


async def _resolve_external_url(query: str) -> str:
    """Tự động phân giải link Spotify qua oEmbed API thành truy vấn tìm kiếm YouTube."""
    q_strip = query.strip()
    if "spotify.com/track" in q_strip or "spotify.link" in q_strip:
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={q_strip}"
            session = await _get_spotify_session()
            async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title")
                    if title:
                        log.info(f"[Music] Resolved Spotify URL '{q_strip}' -> '{title}'")
                        return title
        except Exception as e:
            log.debug(f"[Music] Spotify resolve error: {e}")
    return query


def clean_youtube_query(query: str) -> str:
    """Chuẩn hóa URL YouTube, loại bỏ các tham số rác (&list=, ?si=, &ab_channel=) để tránh bị nhận diện nhầm thành playlist tab."""
    q = query.strip()
    match = re.search(r"(?:v=|\/|vi=)([0-9A-Za-z_-]{11})(?:[&?]|$|\/)", q)
    if match and any(domain in q.lower() for domain in ["youtube.com", "youtu.be"]):
        video_id = match.group(1)
        return f"https://www.youtube.com/watch?v={video_id}"
    return q


def _extract_sync(query: str) -> dict | None:
    """Đồng bộ yt-dlp (chạy trong thread pool qua singleton session)."""
    try:
        clean_q = clean_youtube_query(query)
        if not clean_q.startswith("http") and not clean_q.startswith("ytsearch:"):
            clean_q = f"ytsearch1:{clean_q}"
        elif clean_q.startswith("ytsearch:") and not clean_q.startswith("ytsearch1:"):
            clean_q = clean_q.replace("ytsearch:", "ytsearch1:", 1)

        ydl = _get_ydl()
        info = ydl.extract_info(clean_q, download=False)
        if not info:
            return None
        if "entries" in info:
            entries = list(info.get("entries") or [])
            if entries and entries[0]:
                info = entries[0]
            else:
                return None
        return info
    except Exception as e:
        log.warning(f"[Music] yt-dlp error for query '{query}': {e}")
        return None


def _extract_metadata_sync(query: str) -> dict | None:
    """Trích xuất nhanh metadata bài hát qua Flat Extraction (< 1s)."""
    try:
        clean_q = clean_youtube_query(query)
        if not clean_q.startswith("http") and not clean_q.startswith("ytsearch:"):
            clean_q = f"ytsearch1:{clean_q}"
        elif clean_q.startswith("ytsearch:") and not clean_q.startswith("ytsearch1:"):
            clean_q = clean_q.replace("ytsearch:", "ytsearch1:", 1)

        ydl = _get_ydl_flat()
        info = ydl.extract_info(clean_q, download=False)
        if not info:
            return None
        if "entries" in info:
            entries = list(info.get("entries") or [])
            if entries and entries[0]:
                info = entries[0]
            else:
                return None

        # Fallback nếu flat extraction trả về entry thiếu title
        if isinstance(info, dict) and not info.get("title") and info.get("id"):
            v_id = info["id"]
            direct_url = f"https://www.youtube.com/watch?v={v_id}"
            fallback_info = ydl.extract_info(direct_url, download=False)
            if fallback_info and fallback_info.get("title"):
                info = fallback_info
        return info
    except Exception as e:
        log.warning(f"[Music] yt-dlp flat metadata error for query '{query}': {e}")
        return None


def _clean_song_title(t: str, lowercase: bool = True) -> str:
    """Loại bỏ các hậu tố rác (Official MV, Lyrics, Remix,...) để so sánh tên bài hát chính xác."""
    cleaned = re.sub(
        r"\[.*?\]|\(.*?\)|official\s*music\s*video|official\s*video|official\s*audio|lyrics\s*video|mv|audio|lyrics",
        "",
        t,
        flags=re.IGNORECASE
    ).strip()
    return cleaned.lower() if lowercase else cleaned


def _is_duplicate_song(t1: str, t2: str) -> bool:
    """Nhận diện 2 bài hát có phải là một (kể cả khi khác tiền tố nghệ sĩ hoặc thêm hậu tố)."""
    c1, c2 = _clean_song_title(t1), _clean_song_title(t2)
    if not c1 or not c2:
        return False
    if c1 == c2:
        return True
    if len(c1) >= 6 and c1 in c2:
        return True
    if len(c2) >= 6 and c2 in c1:
        return True
    return False


def _find_related_track_sync(current_title: str, current_uploader: str, history: list[str] | set[str] | None = None, current_id: str = "") -> dict | None:
    """Tìm bài hát liên quan / cùng thể loại khi bật chế độ Autoplay (< 1s)."""
    try:
        hist = history or set()
        clean_title = _clean_song_title(current_title, lowercase=False)
        if not clean_title:
            clean_title = current_title.strip()

        uploader_clean = re.sub(r"-\s*topic|vevo", "", current_uploader or "", flags=re.IGNORECASE).strip()
        has_valid_uploader = bool(uploader_clean and uploader_clean.lower() not in ("—", "unknown", "none", "various artists", "various"))

        queries = []
        if has_valid_uploader:
            queries.append(f"ytsearch10:{clean_title} {uploader_clean}")
            queries.append(f"ytsearch10:{uploader_clean} songs")
        else:
            queries.append(f"ytsearch10:{clean_title}")
        queries.append(f"ytsearch10:{clean_title} radio mix")

        ydl = _get_ydl_flat()
        for search_q in queries:
            try:
                info = ydl.extract_info(search_q, download=False)
                if not info or "entries" not in info:
                    continue
                entries = [entry for entry in info.get("entries") if entry]
                for entry in entries:
                    title = entry.get("title", "")
                    url = entry.get("webpage_url") or entry.get("url") or ""
                    vid = entry.get("id") or ""

                    if not title:
                        continue

                    # Bỏ qua bài hát hiện tại (trùng ID hoặc trùng tên bài)
                    if current_id and vid == current_id:
                        continue
                    if _is_duplicate_song(current_title, title):
                        continue

                    # Kiểm tra lịch sử phát (tránh lặp bài thông minh, chống false positive với từ ngắn)
                    if any(h and (h == vid or (url and h in url) or _is_duplicate_song(h, title)) for h in hist):
                        continue

                    dur = entry.get("duration") or 0
                    # Cho phép bài hát / DJ mix lên đến 4 tiếng (14400s), loại bỏ clip rác (< 30s)
                    if dur > 0 and (dur < 30 or dur > 14400):
                        continue

                    # Chuẩn hóa URL YouTube nếu thiếu
                    if vid and not entry.get("webpage_url"):
                        entry["webpage_url"] = f"https://www.youtube.com/watch?v={vid}"

                    # Đảm bảo không để lộ webpage URL dưới dạng stream URL
                    entry.pop("stream_url", None)

                    return entry
            except Exception:
                continue
    except Exception as e:
        log.warning(f"[Music] Autoplay search failed: {e}")
    return None


def _get_stream_url(info: dict) -> str | None:
    """Lấy URL stream tốt nhất từ info dict (ưu tiên progressive HTTP trước HLS m3u8, lọc bỏ storyboard/mhtml)."""
    if not info:
        return None
    if info.get("stream_url"):
        return info["stream_url"]

    valid_formats = []
    for f in info.get("formats", []):
        url = f.get("url", "")
        ext = (f.get("ext") or "").lower()
        acodec = (f.get("acodec") or "").lower()

        # Bỏ các format không có audio hoặc là storyboard / file ảnh
        if acodec in ("none", "", "null") or ext in ("mhtml", "jpg", "jpeg", "png", "webp"):
            continue
        if "storyboard" in url or "/sb/" in url:
            continue
        if url.startswith("http"):
            valid_formats.append(f)

    def _is_hls(fmt: dict) -> bool:
        proto = (fmt.get("protocol") or "").lower()
        u = (fmt.get("url") or "").lower()
        return "m3u8" in proto or ".m3u8" in u

    # 1. Tối ưu nhất: Opus audio-only qua progressive HTTP (không phải HLS)
    for f in valid_formats:
        acodec = (f.get("acodec") or "").lower()
        vcodec = (f.get("vcodec") or "").lower()
        if acodec == "opus" and vcodec in ("none", "", "null") and not _is_hls(f):
            return f["url"]

    # 2. Ưu tiên cao: Audio-only bất kỳ (mp3, m4a, aac) qua progressive HTTP (chống HLS m3u8 làm méo nhịp / lúc nhanh lúc chậm)
    for f in valid_formats:
        vcodec = (f.get("vcodec") or "").lower()
        if vcodec in ("none", "", "null") and not _is_hls(f):
            return f["url"]

    # 3. Fallback: Opus audio-only (kể cả HLS m3u8)
    for f in valid_formats:
        acodec = (f.get("acodec") or "").lower()
        vcodec = (f.get("vcodec") or "").lower()
        if acodec == "opus" and vcodec in ("none", "", "null"):
            return f["url"]

    # 4. Fallback: Audio-only bất kỳ (kể cả HLS m3u8)
    for f in valid_formats:
        vcodec = (f.get("vcodec") or "").lower()
        if vcodec in ("none", "", "null"):
            return f["url"]

    # 5. Fallback: Luồng có audio bitrate tốt nhất (ưu tiên progressive trước)
    prog_formats = [f for f in valid_formats if not _is_hls(f)]
    if prog_formats:
        best_audio = max(prog_formats, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))
        return best_audio["url"]

    if valid_formats:
        best_audio = max(valid_formats, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))
        return best_audio["url"]

    # 6. Trực tiếp info.get("url") nếu hợp lệ (CHỈ chấp nhận direct media stream, tuyệt đối không nhận webpage URL)
    direct_url = info.get("url")
    if (
        direct_url
        and direct_url.startswith("http")
        and not any(x in direct_url.lower() for x in [
            "storyboard", ".jpg", ".png", ".mhtml",
            "youtube.com", "youtu.be", "soundcloud.com", "spotify.com"
        ])
    ):
        return direct_url

    return None


def _get_stream_acodec(info: dict, stream_url: str | None) -> str:
    """Xác định codec audio của URL stream đã chọn (trả về 'opus', 'mp4a', ...)."""
    if not stream_url or not info:
        return ""
    for f in info.get("formats", []):
        if f.get("url") == stream_url:
            return (f.get("acodec") or "").lower()
    if info.get("acodec"):
        return info["acodec"].lower()
    # Fallback: heuristic theo mimetype/URL
    if "mime=audio%2Fwebm" in stream_url or "audio/webm" in stream_url:
        return "opus"
    return ""


def _get_best_thumbnail(info: dict) -> str:
    if not info:
        return ""
    if info.get("thumbnail") and isinstance(info.get("thumbnail"), str) and info["thumbnail"].startswith("http"):
        return info["thumbnail"]
    thumbnails = info.get("thumbnails", [])
    if thumbnails and isinstance(thumbnails, list):
        valid = [t for t in thumbnails if t.get("url") and t.get("url").startswith("http")]
        if valid:
            best = max(valid, key=lambda t: t.get("width") or 0)
            return best.get("url") or ""
    return info.get("thumbnail") or ""


def _extract_stream_expire(stream_url: str | None, info: dict) -> float:
    """Trích xuất expire timestamp thật từ format/info yt-dlp hoặc query parameter của stream URL."""
    if not stream_url:
        return 0.0
    # 1. Trực tiếp từ trường expire của info
    if info.get("stream_expire"):
        try:
            return float(info["stream_expire"])
        except (ValueError, TypeError):
            pass
    if info.get("expire"):
        try:
            return float(info["expire"])
        except (ValueError, TypeError):
            pass
    # 2. Kiểm tra formats array
    if info.get("formats"):
        for fmt in info["formats"]:
            if fmt.get("url") == stream_url and fmt.get("expire"):
                try:
                    return float(fmt["expire"])
                except (ValueError, TypeError):
                    pass
    # 3. Regex param ?expire=... từ stream_url (chuẩn của Google video / YouTube stream CDN)
    m = re.search(r"[?&]expire=(\d+)", stream_url)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    # 4. Fallback: 5.5 giờ nếu có stream_url
    return time.time() + (5.5 * 3600)


def _compact_song_info(info: dict) -> dict:
    """Rút gọn thông tin bài hát chỉ còn các trường cần thiết (< 0.5 KB).

    Loại bỏ toàn bộ formats video 4K/1080p, captions 50 ngôn ngữ, heatmap rác,
    giúp giảm 99.9% dung lượng SQLite và tăng tốc giải mã JSON trên Helio G85.
    """
    if not info:
        return {}
    stream_url = _get_stream_url(info)
    acodec = _get_stream_acodec(info, stream_url)
    is_opus = bool(info.get("is_opus")) if "is_opus" in info else (acodec == "opus")
    thumbnail = _get_best_thumbnail(info)
    stream_expire = _extract_stream_expire(stream_url, info)
    is_live = bool(info.get("is_live") or info.get("live_status") == "is_live")
    return {
        "id":            info.get("id", ""),
        "title":         info.get("title", "Unknown"),
        "webpage_url":   info.get("webpage_url") or info.get("url", ""),
        "url":           info.get("url", ""),
        "stream_url":    stream_url,
        "stream_expire": stream_expire,
        "duration":      info.get("duration"),
        "uploader":      info.get("uploader") or info.get("channel") or "—",
        "thumbnail":     thumbnail,
        "acodec":        acodec,
        "is_opus":       is_opus,
        "is_live":       is_live,
    }


async def extract_info(query: str, force_refresh: bool = False) -> dict | None:
    """Lấy thông tin bài hát đầy đủ bao gồm stream audio (cho lệnh phát nhạc)."""
    key = query.strip().lower()
    cache_key = f"song_info:{key}"

    if not force_refresh:
        # 1. Kiểm tra RAM Cache wrapper
        cached = await cache.aget(cache_key)
        if cached is not None:
            return cached

        # 1b. Disk cache (giúp nhanh sau khi bot restart, TTL 6h — URL stream tự hết hạn 5.5h)
        disk = await async_get_song_cache(cache_key, ttl=21600)
        if disk is not None:
            exp = disk.get("stream_expire")
            if exp and float(exp) <= (time.time() + 30):
                disk = None
            else:
                await cache.aset(cache_key, disk, ttl=600)
                return disk

    # 2. Chạy yt-dlp trong thread pool (giới hạn đồng thời bằng semaphore)
    async with _extract_semaphore:
        if force_refresh:
            await cache.adelete(cache_key)
            await async_delete_song_cache(cache_key)

        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, _extract_sync, query)

    if info:
        compact = _compact_song_info(info)
        exp_ts = compact.get("stream_expire")
        is_live = compact.get("is_live", False)
        # Với live stream: Tuyệt đối không cache để token luôn tươi mới và chống OOM trên Termux
        if not is_live:
            await cache.aset(cache_key, compact, ttl=600)
            await async_set_song_cache(cache_key, compact, exp_ts)
            vid = compact.get("id")
            if vid:
                await cache.aset(f"song_info:{vid}", compact, ttl=600)
                await async_set_song_cache(f"song_info:{vid}", compact, exp_ts)
            web_url = compact.get("webpage_url") or compact.get("url")
            if web_url and isinstance(web_url, str) and web_url.startswith("http"):
                await cache.aset(f"song_info:{web_url.lower().strip()}", compact, ttl=600)
                await async_set_song_cache(f"song_info:{web_url.lower().strip()}", compact, exp_ts)
        return compact

    return None


async def extract_metadata(query: str) -> dict | None:
    """Lấy nhanh thông tin cơ bản bài hát cho Playlist / Search (Flat Extraction + RAM Cache 24h)."""
    key = query.strip().lower()
    cache_key = f"song_meta:{key}"

    # 1. Kiểm tra RAM Cache (trả về tức thì 0ms)
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    # 2. Chạy Flat Extraction siêu tốc trong thread pool có semaphore bảo vệ chống quá tải
    async with _extract_semaphore:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, _extract_metadata_sync, query)

    if info:
        # Chuẩn hóa webpage_url nếu bị thiếu
        video_id = info.get("id")
        if not info.get("webpage_url") and video_id:
            info["webpage_url"] = f"https://www.youtube.com/watch?v={video_id}"
        # Lưu vào RAM Cache (TTL 24 giờ)
        await cache.aset(cache_key, info, ttl=86400)

    return info


# ─── Track ─────────────────────────────────────────────────────────────────────
class Track:
    __slots__ = ("duration", "requester", "stream_expire", "stream_url", "thumbnail", "title", "uploader", "url", "is_opus", "recovery_attempts", "is_live")

    def __init__(self, info: dict, requester: discord.Member | None = None):
        self.title         = info.get("title", "Unknown")
        self.url           = info.get("webpage_url") or info.get("url", "")
        # stream_url chỉ được nạp nếu đã trích xuất stream audio thực sự (từ _compact_song_info hoặc formats)
        stream_url = info.get("stream_url")
        if not stream_url and info.get("formats"):
            stream_url = _get_stream_url(info)
        if stream_url and any(domain in stream_url.lower() for domain in ("youtube.com", "youtu.be", "soundcloud.com", "spotify.com")):
            stream_url = None
        self.stream_url    = stream_url
        self.stream_expire = _extract_stream_expire(self.stream_url, info)
        self.duration      = info.get("duration")
        self.uploader      = info.get("uploader") or info.get("channel") or "—"
        self.thumbnail     = info.get("thumbnail") or _get_best_thumbnail(info)
        self.requester     = requester
        # Xác định opus chính xác theo acodec (fallback heuristic nếu không tìm thấy format)
        self.is_opus       = bool(info.get("is_opus")) if "is_opus" in info else (_get_stream_acodec(info, self.stream_url) == "opus")
        self.recovery_attempts = 0
        self.is_live       = bool(
            info.get("is_live")
            or info.get("live_status") == "is_live"
            or (self.duration is not None and self.duration <= 0)
        )


    @property
    def is_stream_expired(self) -> bool:
        return self.stream_url is None or time.time() > self.stream_expire

    @property
    def duration_str(self) -> str:
        return _fmt_duration(self.duration)

    @property
    def requester_mention(self) -> str:
        return self.requester.mention if self.requester else "Không rõ"


# ─── Music Player (1 per guild) ────────────────────────────────────────────────
class MusicPlayer:
    def __init__(self, guild: discord.Guild, text_channel, vc: discord.VoiceClient, cog=None):
        self.guild         = guild
        self.text_channel  = text_channel
        self.vc            = vc
        self.cog           = cog
        self._manual_stopped = False
        self.loop          = asyncio.get_running_loop()
        self.queue         : list[Track] = []
        self.current       : Track | None = None
        self.loop_mode     = 0   # 0=off  1=loop-one  2=loop-all
        self.autoplay      = False # Autoplay: tự động tìm và phát bài tương tự khi hết hàng chờ
        self._played_history : list[str] = [] # Lưu các bài đã phát để không bị lặp lại trong Autoplay
        self._played_history_set : set[str] = set()
        self.volume        = 1.0 # 100%
        self._consecutive_errors = 0
        self.now_playing_msg : discord.Message | None = None
        self.start_time    : float = 0.0
        self.pause_start   : float = 0.0
        self.total_paused_time : float = 0.0
        self._skipped      : bool = False
        self._recovering   : bool = False
        self._last_recovery_time : float = 0.0
        self._preload_task : asyncio.Task | None = None
        self._inactivity_task : asyncio.Task | None = None
        self._play_lock    = asyncio.Lock()
        self._recovery_lock = asyncio.Lock()

    def _get_loop(self):
        """Lấy event loop an toàn tại thời điểm gọi để tránh stale loop."""
        try:
            return self.vc.client.loop
        except Exception:
            return asyncio.get_event_loop()

    def _record_played(self, title: str):
        """Ghi nhận bài đã phát vào history và set hỗ trợ O(1) tra cứu."""
        if not title:
            return
        self._played_history.append(title)
        self._played_history_set.add(title.lower().strip())
        if len(self._played_history) > 30:
            removed = self._played_history.pop(0)
            self._played_history_set.discard(removed.lower().strip())

    def get_elapsed(self) -> int:
        if not self.current or self.start_time <= 0:
            return 0
        if self.vc and self.vc.is_paused() and self.pause_start > 0:
            return max(0, int(self.pause_start - self.start_time - self.total_paused_time))
        return max(0, int(time.time() - self.start_time - self.total_paused_time))

    # ── Inactivity Auto-Disconnect ─────────────────────────────────────────
    def _reset_inactivity_timer(self):
        if self._inactivity_task and not self._inactivity_task.done():
            self._inactivity_task.cancel()
        self._inactivity_task = None

    def _start_inactivity_timer(self):
        self._reset_inactivity_timer()
        self._inactivity_task = asyncio.create_task(self._inactivity_countdown())

    async def _inactivity_countdown(self):
        """Tự động rời phòng voice sau 180s (3 phút) nếu không có bài hát nào được phát."""
        try:
            await asyncio.sleep(180)
            if not self.current and not self.queue and self.vc and self.vc.is_connected():
                if self.text_channel:
                    try:
                        s = await async_get_guild_settings(str(self.guild.id))
                        await self.text_channel.send(tr(s, "music.auto_leave_inactivity"), delete_after=60)
                    except Exception:
                        pass
                await self.stop()
        except asyncio.CancelledError:
            pass

    # ── Internal ───────────────────────────────────────────────────────────
    async def _preload_next(self):
        if not self.queue:
            return
        nxt = self.queue[0]
        if nxt.stream_url and not nxt.is_stream_expired:
            return
        try:
            info = await extract_info(nxt.url or nxt.title)
            if info:
                nxt.stream_url    = _get_stream_url(info)
                nxt.stream_expire = _extract_stream_expire(nxt.stream_url, info)
                nxt.is_opus       = _get_stream_acodec(info, nxt.stream_url) == "opus"
        except Exception as e:
            log.debug(f"[Music] Preload error: {e}")

    def _schedule_preload(self):
        """Preload bài tiếp theo (queue[0]) ngay khi có hàng chờ, tránh chờ tới lúc hết bài."""
        if not self.queue:
            return
        if self._preload_task and not self._preload_task.done():
            self._preload_task.cancel()
        self._preload_task = asyncio.create_task(self._preload_next())

    def _after_play(self, error=None):
        """Callback từ audio thread của discord.py khi stream dừng (chuyển sang event loop an toàn)."""
        if self._manual_stopped or self._recovering:
            return

        try:
            loop = self._get_loop()
            if loop.is_closed():
                return
            elapsed = self.get_elapsed()
            curr = self.current
            if not curr:
                return

            asyncio.run_coroutine_threadsafe(self._handle_after_play_async(error, elapsed, curr), loop)
        except Exception as e:
            log.debug(f"[Music] _after_play dispatch error: {e}")

    async def _handle_after_play_async(self, error, elapsed: int, track: Track):
        """Xử lý kết thúc phát nhạc trên Main Event Loop (100% thread-safe)."""
        async with self._recovery_lock:
            if self._manual_stopped or self._recovering:
                return

            is_live_track = getattr(track, "is_live", False)
            now = time.time()

            # 1. LIVE STREAM AUTO-RECOVERY (Lofi Girl 24/7, Radio, YouTube Live)
            if is_live_track and not self._skipped:
                # Reset recovery counter chỉ khi đã phát ổn định >= 180s (3 phút)
                if elapsed >= 180 or (self._last_recovery_time > 0 and (now - self._last_recovery_time) >= 180):
                    track.recovery_attempts = 0

                if getattr(track, "recovery_attempts", 0) < 5:
                    track.recovery_attempts = getattr(track, "recovery_attempts", 0) + 1
                    self._last_recovery_time = now
                    self._recovering = True
                    log.warning(
                        f"[Music] Live stream 24/7 '{track.title}' ngắt kết nối tại {elapsed}s (lần {track.recovery_attempts}/5). "
                        f"Đang tự động làm mới stream URL và tiếp tục phát sau 2s backoff..."
                    )
                    try:
                        track.stream_url = None
                        await asyncio.sleep(2)
                        await self._play(track, seek_offset=0)
                    except Exception as rec_err:
                        log.error(f"[Music] Lỗi khôi phục live stream '{track.title}': {rec_err}")
                        await self._on_queue_empty()
                    finally:
                        self._recovering = False
                    return
                else:
                    log.error(f"[Music] Live stream '{track.title}' lỗi liên tục 5 lần, dừng stream.")
                    try:
                        if self.text_channel:
                            await self.text_channel.send(
                                embed=discord.Embed(
                                    description=f"⚠️ Live stream **{track.title}** bị gián đoạn và không thể kết nối lại sau 5 lần thử.",
                                    color=0xED4245
                                )
                            )
                    except Exception:
                        pass
                    await self.stop()
                    return

            # 2. Regular song premature disconnect auto-recovery (403 Forbidden / rớt mạng)
            is_premature = (
                not self._skipped
                and not is_live_track
                and track.duration
                and track.duration > 30
                and elapsed < (track.duration - 15)
            )
            if (error or is_premature) and getattr(track, "recovery_attempts", 0) < 1 and not self._skipped:
                track.recovery_attempts = 1
                self._recovering = True
                log.warning(
                    f"[Music] Bài hát '{track.title}' đứt kết nối tại {elapsed}s (error={error}, premature={is_premature}). "
                    f"Đang tự động làm mới URL và phát tiếp từ {elapsed}s..."
                )
                try:
                    track.stream_url = None
                    await self._play(track, seek_offset=elapsed)
                except Exception as rec_err:
                    log.error(f"[Music] Lỗi khôi phục bài hát '{track.title}': {rec_err}")
                    await self._on_queue_empty()
                finally:
                    self._recovering = False
                return

            if error:
                log.warning(f"[Music] Player error: {error}")
                self._consecutive_errors += 1
                if self._consecutive_errors >= 3:
                    log.error(f"[Music] Gặp {self._consecutive_errors} lỗi phát nhạc liên tiếp, dừng autoplay để chống lặp.")
                    self._consecutive_errors = 0
                    self.autoplay = False
                    await self._on_queue_empty()
                    return
            else:
                self._consecutive_errors = 0

            self._record_played(track.title)

            if self.loop_mode == 1:
                track.recovery_attempts = 0
                await self._play(track)
            elif self.loop_mode == 2:
                track.recovery_attempts = 0
                self.queue.append(track)
                await self._dispatch_next_async()
            else:
                await self._dispatch_next_async()

    def _dispatch_next(self):
        """Dispatch bài tiếp theo an toàn (hỗ trợ gọi đồng bộ từ bên ngoài)."""
        loop = self._get_loop()
        asyncio.run_coroutine_threadsafe(self._dispatch_next_async(), loop)

    async def _dispatch_next_async(self):
        """Dispatch bài tiếp theo bất đồng bộ trực tiếp trên event loop."""
        if self.queue:
            self._reset_inactivity_timer()
            await self._play(self.queue.pop(0))
        elif self.autoplay and self.current:
            self._reset_inactivity_timer()
            await self._handle_autoplay()
        else:
            self.current = None
            await self._on_queue_empty()

    async def _handle_autoplay(self):
        """Tự động tìm kiếm và phát bài hát cùng thể loại khi bật Autoplay."""
        if not self.current:
            await self._on_queue_empty()
            return
        last_track = self.current
        curr_id = ""
        if last_track.url:
            m = re.search(r"(?:v=|\/|vi=)([0-9A-Za-z_-]{11})(?:[&?]|$|\/)", last_track.url)
            if m:
                curr_id = m.group(1)

        try:
            related_info = await asyncio.to_thread(
                _find_related_track_sync,
                last_track.title,
                last_track.uploader,
                self._played_history_set,
                curr_id,
            )
            if related_info:
                # Đảm bảo stream_url luôn None để _play() giải mã stream audio đầy đủ
                related_info.pop("stream_url", None)
                bot_user = getattr(self.vc, "client", None)
                requester = bot_user.user if (bot_user and hasattr(bot_user, "user")) else None
                new_track = Track(related_info, requester=requester)
                new_track.stream_url = None
                if self.text_channel:
                    try:
                        await self.text_channel.send(
                            f"♾️ **Autoplay:** Tự động phát bài tiếp theo **[{new_track.title}]({new_track.url})**",
                            delete_after=10
                        )
                    except Exception:
                        pass
                await self._play(new_track)
                return
        except Exception as e:
            log.warning(f"[Music] Autoplay error: {e}")

        # Fallback nếu không tìm thấy bài liên quan
        self.current = None
        await self._on_queue_empty()

    async def _on_queue_empty(self):
        """Xử lý khi hàng chờ hết — xóa embed/disable nút NP cũ và bật timer tự rời voice."""
        if self.now_playing_msg:
            try:
                view = discord.ui.View()  # View rỗng = xóa toàn bộ nút bấm cũ
                await self.now_playing_msg.edit(view=view)
            except Exception:
                pass
            self.now_playing_msg = None

        if self.text_channel and not self._manual_stopped:
            try:
                s = await async_get_guild_settings(str(self.guild.id))
                await self.text_channel.send(tr(s, "music.queue_empty"), delete_after=60)
            except Exception:
                pass

        if not self._manual_stopped:
            self._start_inactivity_timer()

    async def _report_play_failure(self, track: Track, reason_key: str = "music.cannot_decode"):
        """Báo cáo lỗi phát bài hát lên text channel và chuyển sang bài kế tiếp một cách an toàn."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= 3:
            self._consecutive_errors = 0
            self.autoplay = False
            await self._on_queue_empty()
            return

        if self.text_channel:
            try:
                s = await async_get_guild_settings(str(self.guild.id))
                await self.text_channel.send(
                    tr(s, reason_key, title=track.title),
                    delete_after=8,
                )
            except Exception as e:
                log.debug(f"[Music] report_play_failure send error: {e}")
        self._dispatch_next()

    async def _play(self, track: Track, seek_offset: int = 0):
        async with self._play_lock:
            if not self.vc or not self.vc.is_connected():
                return

            self._reset_inactivity_timer()
            self._skipped = False

            # Lấy stream URL tươi mới nếu chưa có hoặc URL đã hết hạn (sau 5.5h)
            if not track.stream_url or track.is_stream_expired:
                must_force = (track.stream_url is None) or getattr(track, "is_live", False)
                info = await extract_info(track.url or track.title, force_refresh=must_force)
                if not info:
                    log.warning(f"[Music] Cannot get stream URL for '{track.title}'")
                    await self._report_play_failure(track)
                    return
                track.stream_url    = info.get("stream_url") or _get_stream_url(info)
                track.stream_expire = _extract_stream_expire(track.stream_url, info)
                track.is_opus       = bool(info.get("is_opus")) if "is_opus" in info else (_get_stream_acodec(info, track.stream_url) == "opus")
                if info.get("is_live"):
                    track.is_live = True

            if not track.stream_url:
                log.warning(f"[Music] Cannot resolve stream URL for '{track.title}'")
                await self._report_play_failure(track)
                return

            self.current = track
            self.start_time = time.time() - seek_offset
            self.pause_start = 0.0
            self.total_paused_time = 0.0

            # Ghi nhận thống kê bài hát được phát vào DB.
            # Đây là NGUỒN DUY NHẤT cho `/topmusic` + dashboard (event_type="music_play",
            # label = tên bài). Trước đây còn một dòng ghi `event_type="music"` với
            # `track.video_id` (Track không có field này → AttributeError bị bắt im lặng)
            # khiến số liệu bị chia làm 2 loại và `/topmusic` luôn trắng.
            try:
                from database import async_increment_stat
                asyncio.create_task(async_increment_stat(str(self.guild.id), "music_play", track.title[:80]))
            except Exception as stat_err:
                log.debug(f"[Music] Increment stat error: {stat_err}")

            # Tự động chọn Opus copy mode nếu stream gốc là Opus WebM (giảm 90% CPU)
            # Dùng track.is_opus (đã xác định theo acodec), fallback heuristic URL.
            is_opus = track.is_opus or (
                track.stream_url
                and ("mime=audio%2Fwebm" in track.stream_url or "audio/webm" in track.stream_url)
            )

            if self.vc.is_playing() or self.vc.is_paused():
                self.vc.stop()
                for _ in range(10):
                    if not self.vc.is_playing() and not self.vc.is_paused():
                        break
                    await asyncio.sleep(0.05)

            source = None
            _t_ffmpeg = time.time()
            before_opts = FFMPEG_BEFORE
            if seek_offset > 0:
                before_opts = f"-ss {seek_offset} " + FFMPEG_BEFORE

            try:
                if is_opus and self.volume == 1.0:
                    try:
                        source = discord.FFmpegOpusAudio(
                            track.stream_url,
                            before_options=before_opts,
                            options=FFMPEG_OPTS_COPY,
                        )
                    except Exception as opus_err:
                        log.debug(f"[Music] FFmpegOpusAudio failed ({opus_err}), fallback to PCMAudio...")
                        source = None

                if source is None:
                    source = discord.FFmpegPCMAudio(
                        track.stream_url,
                        before_options=before_opts,
                        options=FFMPEG_OPTS_ENCODE,
                    )
                    if self.volume != 1.0:
                        source = discord.PCMVolumeTransformer(source, volume=self.volume)

                proc = getattr(source, "_process", None) or getattr(getattr(source, "original", None), "_process", None)
                _lower_process_priority(proc)

                if not discord.opus.is_loaded():
                    load_opus_library()

                self.vc.play(source, after=self._after_play)
                self._consecutive_errors = 0
                log.info(f"[Music][timing] ffmpeg source ready in {time.time() - _t_ffmpeg:.2f}s (opus_copy={is_opus}, seek={seek_offset}s)")
            except Exception as e:
                log.error(f"[Music] FFmpeg playback error for '{track.title}': {type(e).__name__} - {e}", exc_info=True)
                await self._report_play_failure(track)
                return

            # Gửi embed Now Playing
            await self._send_now_playing()

            # Pre-load bài tiếp theo ở background
            if self.queue:
                self._schedule_preload()

    async def _send_now_playing(self):
        if not self.text_channel or not self.current:
            return

        s = await async_get_guild_settings(str(self.guild.id))
        view  = MusicControlView(self, s)
        elapsed = self.get_elapsed()
        is_opus_copy = bool(self.vc and self.vc.source and not isinstance(self.vc.source, discord.PCMVolumeTransformer))
        embed = _make_np_embed(self.current, self.queue, self.loop_mode, self.volume, elapsed, s, is_opus_copy=is_opus_copy)

        # Nếu đã có now_playing_msg đang tồn tại (ví dụ khi auto-reconnect live stream), ưu tiên edit
        if self.now_playing_msg:
            try:
                await self.now_playing_msg.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.now_playing_msg = None
            except Exception as e:
                log.debug(f"[Music] edit NP message error: {e}")
                self.now_playing_msg = None

        try:
            self.now_playing_msg = await self.text_channel.send(embed=embed, view=view)
        except Exception as e:
            log.error(f"[Music] NP embed error: {e}")


    # ── Public API ─────────────────────────────────────────────────────────
    async def add_and_play(self, track: Track):
        self._reset_inactivity_timer()
        if self.vc.is_playing() or self.vc.is_paused() or self.current:
            self.queue.append(track)
            # Preload sớm bài kế tiếp để skip tới là có sẵn ngay
            if self.queue:
                self._schedule_preload()
        else:
            await self._play(track)

    def skip(self):
        self._skipped = True
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()

    def shuffle(self):
        if len(self.queue) > 1:
            random.shuffle(self.queue)

    def set_volume(self, volume: float):
        self.volume = max(0.01, min(1.5, volume))
        if self.vc and self.vc.source and isinstance(self.vc.source, discord.PCMVolumeTransformer):
            self.vc.source.volume = self.volume
        if self.now_playing_msg:
            asyncio.create_task(self.update_now_playing())

    async def update_now_playing(self):
        """Cập nhật embed Now Playing khi trạng thái thay đổi (volume/pause/autoplay)."""
        if not self.now_playing_msg or not self.current:
            return
        try:
            s = await async_get_guild_settings(str(self.guild.id))
            elapsed = self.get_elapsed()
            is_opus_copy = bool(self.vc and self.vc.source and not isinstance(self.vc.source, discord.PCMVolumeTransformer))
            embed = _make_np_embed(self.current, self.queue, self.loop_mode, self.volume, elapsed, s, is_opus_copy=is_opus_copy)
            view = MusicControlView(self, s)
            await self.now_playing_msg.edit(embed=embed, view=view)
        except Exception as e:
            log.debug(f"[Music] update_now_playing error: {e}")

    async def stop(self):
        self._manual_stopped = True
        self._reset_inactivity_timer()
        self.queue.clear()
        self.current   = None
        self.loop_mode = 0
        self.autoplay  = False
        self._played_history.clear()
        self._played_history_set.clear()
        if self._preload_task:
            self._preload_task.cancel()

        # 1. Dọn dẹp self.vc
        if self.vc:
            try:
                if self.vc.is_playing() or self.vc.is_paused():
                    self.vc.stop()
                if self.vc.is_connected():
                    await self.vc.disconnect(force=True)
            except Exception as e:
                log.debug(f"[Music] voice disconnect error: {e}")

        # 2. Dọn dẹp guild.voice_client trực tiếp (chống ghost voice desync)
        try:
            g_vc = self.guild.voice_client
            if g_vc and g_vc.is_connected():
                if g_vc.is_playing() or g_vc.is_paused():
                    g_vc.stop()
                await g_vc.disconnect(force=True)
        except Exception as e:
            log.debug(f"[Music] guild voice_client disconnect error: {e}")

        # 3. Dọn dẹp voice state nếu bot vẫn còn kẹt trong channel
        try:
            if self.guild.me and self.guild.me.voice and self.guild.me.voice.channel:
                await self.guild.change_voice_state(channel=None)
        except Exception as e:
            log.debug(f"[Music] guild change_voice_state error: {e}")

        if self.now_playing_msg:
            try:
                await self.now_playing_msg.delete()
            except Exception as e:
                log.debug(f"[Music] delete NP message (stop) error: {e}")
        self.now_playing_msg = None
        if self.cog:
            self.cog._drop(self.guild.id)


# ─── Embeds & Helpers ──────────────────────────────────────────────────────────
def _make_progress_bar(elapsed_sec: int, total_sec: int | None, bar_length: int = 45) -> str:
    """Tạo thanh tiến trình phát nhạc nét đậm nổi bật theo phong cách Markdown Bold (45 ký tự)."""
    if total_sec is None or not isinstance(total_sec, (int, float)) or total_sec <= 0:
        return f"[**{'━' * bar_length}**](https://zerynbot.id.vn)"

    elapsed_sec = max(0, min(int(elapsed_sec or 0), int(total_sec)))
    ratio = elapsed_sec / total_sec if total_sec > 0 else 0.0
    played_len = max(1, min(bar_length, int(ratio * bar_length)))
    remaining_len = bar_length - played_len

    played_bar = "━" * played_len
    remaining_bar = "━" * remaining_len

    if remaining_len > 0:
        return f"[**{played_bar}**](https://zerynbot.id.vn)**{remaining_bar}**"
    else:
        return f"[**{played_bar}**](https://zerynbot.id.vn)"


def _format_queue_duration(queue: list, current_track: Track = None) -> str:
    total_sec = 0
    has_live = False
    if current_track:
        if current_track.duration is not None and isinstance(current_track.duration, (int, float)) and current_track.duration > 0:
            total_sec += int(current_track.duration)
        else:
            has_live = True
    for t in queue:
        if t.duration is not None and isinstance(t.duration, (int, float)) and t.duration > 0:
            total_sec += int(t.duration)
        else:
            has_live = True
    if total_sec <= 0:
        return "LIVE" if has_live else "0s"
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}h {m}m"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _make_np_embed(track: Track, queue: list, loop_mode: int, volume: float = 1.0, elapsed_sec: int = 0, settings: dict = None, is_opus_copy: bool = False) -> discord.Embed:
    """Tạo Embed Now Playing chuẩn phong cách Wave Music (Compact card, right thumbnail, bold bar)."""
    s = settings or {}
    vol_percent = int(volume * 100)
    queue_len = len(queue)
    total_dur_str = _format_queue_duration(queue, track)
    np_title = tr(s, "music.now_playing_title") if tr(s, "music.now_playing_title") != "music.now_playing_title" else "Now Playing"
    vol_label = tr(s, "music.np_volume")
    queue_label = tr(s, "music.np_queue")
    dur_label = tr(s, "music.total_duration")
    songs_unit = tr(s, "music.songs_unit")

    dur_badge = track.duration_str if track.duration and track.duration > 0 else "LIVE"
    progress_bar = _make_progress_bar(elapsed_sec, track.duration, bar_length=45)

    embed = discord.Embed(
        color=0x5865F2,  # Discord Blurple (#5865F2) matching Wave Music
        description=(
            f"**{e('zb_play')} {np_title}**\n"
            f"### [{track.title}]({track.url})\n"
            f"**{track.uploader}** — `{dur_badge}` — {track.requester_mention}\n"
            f"─────────────────────────────────────────────\n"
            f"**{vol_label}:** `{vol_percent}%` — **{queue_label}:** `{queue_len} {songs_unit}` — **{dur_label}:** `{total_dur_str}`\n\n"
            f"{progress_bar}"
        )
    )

    # Đặt thumbnail ở góc phải trên cùng thay vì ảnh to choáng màn hình
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

    if is_opus_copy and volume != 1.0:
        embed.set_footer(text=f"ℹ️ {tr(s, 'music.vol_applies_next')}")

    return embed


# ─── Music Control View ────────────────────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, player: MusicPlayer, settings: dict = None):
        super().__init__(timeout=None)
        self.player = player
        self.settings = settings or {}

        # 1. Nút Autoplay
        self.btn_autoplay.label = "Autoplay"
        self.btn_autoplay.emoji = "♾️"
        if player.autoplay:
            self.btn_autoplay.style = discord.ButtonStyle.primary
        else:
            self.btn_autoplay.style = discord.ButtonStyle.secondary

        # 2. Nút Stop
        self.btn_stop.label = tr(self.settings, "music.btn_stop")
        self.btn_stop.emoji = "⏹️"
        self.btn_stop.style = discord.ButtonStyle.secondary

        # 3. Nút Pause / Resume
        if player.vc and player.vc.is_paused():
            self.btn_pause.label = tr(self.settings, "music.btn_resume")
            self.btn_pause.emoji = partial("zb_play", "▶️")
        else:
            self.btn_pause.label = tr(self.settings, "music.btn_pause")
            self.btn_pause.emoji = partial("zb_pause", "⏸️")
        self.btn_pause.style = discord.ButtonStyle.secondary

        # 4. Nút Skip
        self.btn_skip.label = tr(self.settings, "music.btn_skip")
        self.btn_skip.emoji = partial("zb_skip", "⏭️")
        self.btn_skip.style = discord.ButtonStyle.secondary

        # 5. Nút Loop (Lặp lại)
        if player.loop_mode == 0:
            self.btn_loop.label = tr(self.settings, "music.btn_loop_off")
            self.btn_loop.emoji = partial("zb_loop", "🔁")
            self.btn_loop.style = discord.ButtonStyle.secondary
        elif player.loop_mode == 1:
            self.btn_loop.label = tr(self.settings, "music.btn_loop_one")
            self.btn_loop.emoji = "🔂"
            self.btn_loop.style = discord.ButtonStyle.primary
        else:
            self.btn_loop.label = tr(self.settings, "music.btn_loop_all")
            self.btn_loop.emoji = partial("zb_loop", "🔁")
            self.btn_loop.style = discord.ButtonStyle.primary

    async def _check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or interaction.user.voice.channel != self.player.vc.channel:
            await interaction.response.send_message(
                tr(self.settings, "music.same_voice_err"), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Autoplay", style=discord.ButtonStyle.secondary, emoji="♾️", row=0)
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.autoplay = not self.player.autoplay
        if self.player.autoplay:
            button.style = discord.ButtonStyle.primary
        else:
            button.style = discord.ButtonStyle.secondary

        elapsed = self.player.get_elapsed()
        embed = _make_np_embed(self.player.current, self.player.queue, self.player.loop_mode, self.player.volume, elapsed, self.settings)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary, emoji="⏹️", row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        s = self.settings or await async_get_guild_settings(str(interaction.guild_id))
        channel = self.player.text_channel or interaction.channel
        await self.player.stop()
        if channel:
            try:
                await channel.send(tr(s, "music.stopped_left"), delete_after=60)
            except Exception:
                pass

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji=partial("zb_pause", "⏸️"), row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        if self.player.vc.is_paused():
            self.player.vc.resume()
            if self.player.pause_start > 0:
                self.player.total_paused_time += time.time() - self.player.pause_start
                self.player.pause_start = 0.0
            button.label = tr(self.settings, "music.btn_pause")
            button.emoji = partial("zb_pause", "⏸️")
        else:
            self.player.vc.pause()
            self.player.pause_start = time.time()
            button.label = tr(self.settings, "music.btn_resume")
            button.emoji = partial("zb_play", "▶️")
        button.style = discord.ButtonStyle.secondary
        elapsed = self.player.get_elapsed()
        embed = _make_np_embed(self.player.current, self.player.queue, self.player.loop_mode, self.player.volume, elapsed, self.settings)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji=partial("zb_skip", "⏭️"), row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.skip()

    @discord.ui.button(label="Lặp lại", style=discord.ButtonStyle.secondary, emoji=partial("zb_loop", "🔁"), row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.loop_mode = (self.player.loop_mode + 1) % 3
        if self.player.loop_mode == 0:
            button.label = tr(self.settings, "music.btn_loop_off")
            button.emoji = partial("zb_loop", "🔁")
            button.style = discord.ButtonStyle.secondary
        elif self.player.loop_mode == 1:
            button.label = tr(self.settings, "music.btn_loop_one")
            button.emoji = "🔂"
            button.style = discord.ButtonStyle.primary
        else:
            button.label = tr(self.settings, "music.btn_loop_all")
            button.emoji = partial("zb_loop", "🔁")
            button.style = discord.ButtonStyle.primary

        elapsed = self.player.get_elapsed()
        embed = _make_np_embed(self.player.current, self.player.queue, self.player.loop_mode, self.player.volume, elapsed, self.settings)
        await interaction.message.edit(embed=embed, view=self)


# ─── Remove Song UI ────────────────────────────────────────────────────────────
class RemoveSongSelect(discord.ui.Select):
    def __init__(self, tracks: list):
        options = []
        for i, t in enumerate(tracks[:25]):
            title = t.get("title", "Unknown")
            if len(title) > 90:
                title = title[:87] + "..."
            options.append(discord.SelectOption(
                label=f"{i+1}. {title}",
                value=str(i),
                description=_fmt_duration(t.get("duration", 0)),
            ))
        super().__init__(
            placeholder="🎵 Chọn bài hát muốn xóa...",
            min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_index = int(self.values[0])
        await interaction.response.defer()


class RemoveSongView(discord.ui.View):
    def __init__(self, ctx: commands.Context, pl: dict, tracks: list):
        super().__init__(timeout=60)
        self.ctx            = ctx
        self.pl             = pl
        self.tracks         = tracks
        self.selected_index : int | None = None
        self.message        : discord.Message | None = None
        self.add_item(RemoveSongSelect(tracks))

    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        import database as db
        s = await db.async_get_guild_settings(str(interaction.guild.id))
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(tr(s, "common.no_permission"), ephemeral=True)
        if self.selected_index is None:
            return await interaction.response.send_message(tr(s, "music.select_song_first"), ephemeral=True)
        await interaction.response.defer()
        track = self.tracks[self.selected_index]
        await db.async_delete_track_from_playlist(track["id"])
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(
            content=tr(s, "music.song_removed_from_pl", track=track.get('title', 'Unknown'), pl=self.pl['name']),
            embed=None, view=self,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        import database as db
        s = await db.async_get_guild_settings(str(interaction.guild.id))
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(tr(s, "common.no_permission"), ephemeral=True)
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content=tr(s, "music.op_cancelled"), embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                import database as db
                s = await db.async_get_guild_settings(str(self.ctx.guild.id))
                await self.message.edit(content=tr(s, "music.op_timeout"), embed=None, view=self)
            except Exception:
                pass


def _parse_time_str(time_str: str) -> int | None:
    """Chuyển chuỗi thời gian (VD: '1:30', '02:45', '90', '1h20m') thành số giây."""
    s = time_str.strip().lower()
    if s.isdigit():
        return int(s)
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return None
    return None


class SearchSelect(discord.ui.Select):
    def __init__(self, results: list[dict], requester: discord.Member, player: MusicPlayer, settings: dict):
        self.results = results
        self.requester = requester
        self.player = player
        self.settings = settings

        options = []
        for i, item in enumerate(results[:5], 1):
            title = (item.get("title") or "Unknown")[:85]
            uploader = item.get("uploader") or item.get("channel") or "Unknown"
            dur = _fmt_duration(item.get("duration"))
            options.append(discord.SelectOption(
                label=f"{i}. {title}"[:100],
                value=str(i - 1),
                description=f"{dur} • {uploader}"[:100],
                emoji="🎵"
            ))

        super().__init__(
            placeholder=tr(settings, "music.search_select_placeholder"),
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester.id:
            return await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)

        await interaction.response.defer()
        idx = int(self.values[0])
        chosen = self.results[idx]
        query = chosen.get("webpage_url") or chosen.get("url") or chosen.get("title")
        info = await extract_info(query)
        if not info:
            return await interaction.followup.send(tr(self.settings, "music.not_found", query=query), ephemeral=True)

        track = Track(info, requester=self.requester)
        if self.player.vc.is_playing() or self.player.vc.is_paused() or self.player.current:
            if len(self.player.queue) >= MAX_QUEUE_SIZE:
                return await interaction.followup.send(tr(self.settings, "music.queue_full", max=MAX_QUEUE_SIZE), ephemeral=True)
            self.player.queue.append(track)
            embed = discord.Embed(
                title=embed_title("zb_play", tr(self.settings, "music.added_to_queue")),
                description=f"**[{track.title}]({track.url})**",
                color=0x3B82F6,
            )
            embed.add_field(name=tr(self.settings, "music.duration_field"),  value=f"`{track.duration_str}`", inline=True)
            embed.add_field(name=tr(self.settings, "music.position_field"),  value=f"`#{len(self.player.queue)}`", inline=True)
            embed.add_field(name=tr(self.settings, "music.requester_field"), value=self.requester.mention, inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed)
        else:
            await self.player.add_and_play(track)
            await interaction.followup.send(f"▶️ **{track.title}** (`{track.duration_str}`)", ephemeral=True)

        # Disable selection sau khi đã chọn
        for child in self.view.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self.view)
        except Exception:
            pass
        self.view.stop()


class SearchSelectView(discord.ui.View):
    def __init__(self, results: list[dict], requester: discord.Member, player: MusicPlayer, settings: dict):
        super().__init__(timeout=60)
        self.message = None
        self.settings = settings
        self.add_item(SearchSelect(results, requester, player, settings))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content=tr(self.settings, "music.search_timeout"), view=self)
            except Exception:
                pass



# ─── Lyrics Utilities & Paginator ─────────────────────────────────────────────
def _clean_track_title(title: str) -> str:
    """Loại bỏ các hậu tố thừa như [MV], (Official Audio), HD, 4K để tìm lyrics chính xác."""
    t = re.sub(r'(?i)\b(official\s+(music\s+)?video|official\s+audio|lyrics\s+video|lyric\s+video|mv|visualizer|audio|4k|hd|remastered)\b', '', title)
    t = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', t)
    t = re.sub(r'\|.*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' -_')
    return t or title


async def _fetch_lyrics_from_lrclib(query: str) -> tuple[str | None, str | None]:
    """Tìm lyrics qua LrcLib API với timeout 5.0s. Trả về (lyrics_text, track_title) hoặc (None, None)."""
    clean_q = _clean_track_title(query)
    cache_key = f"lyrics:{clean_q.lower()}"
    cached = await cache.aget(cache_key)
    if cached:
        return cached

    url = "https://lrclib.net/api/search"
    headers = {"User-Agent": "ZerynBot/2.0 (Discord Music Bot)"}
    params = {"q": clean_q}

    try:
        timeout = aiohttp.ClientTimeout(total=5.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return None, None
                data = await resp.json(content_type=None)
                if not data or not isinstance(data, list):
                    return None, None

                for item in data:
                    plain = item.get("plainLyrics")
                    synced = item.get("syncedLyrics")
                    track_name = f"{item.get('artistName', '')} - {item.get('trackName', '')}".strip(' -')
                    if plain:
                        res = (plain.strip(), track_name)
                        await cache.aset(cache_key, res, ttl=86400)
                        return res
                    elif synced:
                        clean_synced = re.sub(r'\[\d{2}:\d{2}\.\d{2,3}\]\s*', '', synced).strip()
                        if clean_synced:
                            res = (clean_synced, track_name)
                            await cache.aset(cache_key, res, ttl=86400)
                            return res
    except Exception as exc:
        log.warning("LrcLib lyrics fetch failed for '%s': %s", clean_q, exc)
    return None, None


def _chunk_lyrics(text: str, max_chars: int = 1800) -> list[str]:
    """Chia nhỏ lời bài hát thành các trang <= 1800 ký tự theo ngắt dòng."""
    lines = text.splitlines()
    pages = []
    current_page = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current_page:
            pages.append("\n".join(current_page))
            current_page = [line]
            current_len = line_len
        else:
            current_page.append(line)
            current_len += line_len

    if current_page:
        pages.append("\n".join(current_page))

    return pages or [text[:max_chars]]


class LyricsPaginatorView(discord.ui.View):
    def __init__(self, pages: list[str], title: str, user_id: int, settings: dict):
        super().__init__(timeout=180)
        self.pages = pages
        self.title = title
        self.user_id = user_id
        self.settings = settings
        self.current_page = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.current_page <= 0)
        self.next_btn.disabled = (self.current_page >= len(self.pages) - 1)
        self.indicator_btn.label = f"{self.current_page + 1}/{len(self.pages)}"

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"📜 {self.title}",
            description=self.pages[self.current_page],
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="lyrics_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(tr(self.settings, "common.not_your_interaction"), ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            embed = self.get_embed()
            embed.set_footer(text=f"Trang {self.current_page + 1}/{len(self.pages)} • Nguồn: LrcLib | {tr(self.settings, 'common.requested_by', user=interaction.user.display_name)}")
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="lyrics_indicator")
    async def indicator_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="lyrics_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(tr(self.settings, "common.not_your_interaction"), ephemeral=True)
            return
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._update_buttons()
            embed = self.get_embed()
            embed.set_footer(text=f"Trang {self.current_page + 1}/{len(self.pages)} • Nguồn: LrcLib | {tr(self.settings, 'common.requested_by', user=interaction.user.display_name)}")
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ─── Cog ───────────────────────────────────────────────────────────────────────
class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self._players: dict[int, MusicPlayer] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._empty_voice_tasks: dict[int, asyncio.Task] = {}

    def cog_unload(self):
        """Cancel tất cả background tasks khi cog bị unload."""
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()
        for task in self._empty_voice_tasks.values():
            task.cancel()
        self._empty_voice_tasks.clear()
        global _spotify_session
        if _spotify_session and not _spotify_session.closed:
            asyncio.create_task(_spotify_session.close())

    # ── Helpers ────────────────────────────────────────────────────────────
    def _get(self, guild_id: int) -> MusicPlayer | None:
        return self._players.get(guild_id)

    def _drop(self, guild_id: int):
        self._players.pop(guild_id, None)

    async def _ensure(self, ctx: commands.Context) -> MusicPlayer | None:
        _t0 = time.time()
        s = await async_get_guild_settings(str(ctx.guild.id))
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(tr(s, "music.join_voice_first"))
            return None

        guild_id = ctx.guild.id
        player   = self._players.get(guild_id)
        g_vc     = ctx.guild.voice_client

        # Trường hợp 1: Player đang sống và vc đang kết nối
        if player and player.vc and player.vc.is_connected():
            if player.vc.channel != ctx.author.voice.channel:
                await ctx.send(tr(s, "music.bot_in_other_voice"))
                return None
            player.text_channel = ctx.channel
            # Đảm bảo bot luôn tự động tắt nghe (self_deaf)
            if ctx.guild.me.voice and not ctx.guild.me.voice.self_deaf:
                try:
                    await ctx.guild.change_voice_state(channel=player.vc.channel, self_deaf=True)
                except Exception:
                    pass
            return player

        # Trường hợp 2: Desync recovery — discord.py voice_client đã kết nối nhưng player bị mất
        if g_vc and g_vc.is_connected():
            log.info(f"[Music] Phát hiện voice_client đã kết nối tại guild {guild_id}, tự động đồng bộ lại player.")
            if g_vc.channel != ctx.author.voice.channel:
                try:
                    await g_vc.move_to(ctx.author.voice.channel)
                except Exception:
                    await ctx.send(tr(s, "music.bot_in_other_voice"))
                    return None
            if player:
                player.vc = g_vc
                player.text_channel = ctx.channel
            else:
                player = MusicPlayer(ctx.guild, ctx.channel, g_vc, cog=self)
                self._players[guild_id] = player
            if ctx.guild.me.voice and not ctx.guild.me.voice.self_deaf:
                try:
                    await ctx.guild.change_voice_state(channel=g_vc.channel, self_deaf=True)
                except Exception:
                    pass
            return player

        # Kiểm tra giới hạn số player đồng thời
        if guild_id not in self._players and len(self._players) >= MAX_PLAYERS:
            await ctx.send(
                tr(s, "music.max_players_err", max=MAX_PLAYERS),
                ephemeral=True,
            )
            return None

        try:
            vc = await ctx.author.voice.channel.connect(self_deaf=True)
        except Exception as e:
            if "already connected" in str(e).lower() and ctx.guild.voice_client:
                vc = ctx.guild.voice_client
            else:
                await ctx.send(tr(s, "music.cannot_connect", err=e))
                return None

        log.info(f"[Music][timing] voice connected in {time.time() - _t0:.2f}s")
        player = MusicPlayer(ctx.guild, ctx.channel, vc, cog=self)
        self._players[guild_id] = player
        return player

    # ── Events ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Xử lý sự kiện voice channel: dọn dẹp tức thì khi bot bị kick, và tự động rời phòng sau 30s nếu không còn ai."""
        guild = member.guild
        guild_id = guild.id

        # 1. Dọn dẹp tức thì nếu chính bot bị ngắt kết nối voice (bị kick hoặc disconnect)
        if self.bot.user and member.id == self.bot.user.id:
            if before.channel and after.channel is None:
                log.info(f"[Music] Bot bị ngắt kết nối khỏi kênh voice tại guild {guild_id}. Dọn dẹp player tức thì.")
                task = self._empty_voice_tasks.pop(guild_id, None)
                if task and not task.done():
                    task.cancel()
                player = self._players.get(guild_id)
                if player:
                    await player.stop()
                    self._drop(guild_id)
            elif after.channel:
                # Bot vừa join kênh voice hoặc chuyển kênh: kiểm tra nếu kênh mới trống
                self._check_and_schedule_empty_voice(guild)
            return

        if member.bot:
            return

        # 2. Xử lý khi người dùng (user) vào/ra/chuyển kênh
        self._check_and_schedule_empty_voice(guild)

    def _check_and_schedule_empty_voice(self, guild: discord.Guild):
        """Kiểm tra kênh voice của bot, nếu không còn ai ngoài bot thì lên lịch tự động out sau 30s."""
        guild_id = guild.id
        vc = guild.voice_client
        bot_channel = vc.channel if (vc and vc.is_connected()) else (guild.me.voice.channel if (guild.me and guild.me.voice) else None)

        if not bot_channel:
            # Bot không ở trong kênh voice nào, hủy task đếm ngược nếu có
            task = self._empty_voice_tasks.pop(guild_id, None)
            if task and not task.done():
                task.cancel()
            return

        # Kiểm tra xem có người thật (không phải bot) trong kênh của bot không
        has_human = any(not m.bot for m in bot_channel.members)

        if has_human:
            # Có người trong phòng -> Hủy bộ đếm 30s nếu đang chạy
            task = self._empty_voice_tasks.pop(guild_id, None)
            if task and not task.done():
                task.cancel()
                log.debug(f"[Music] Người dùng đã vào lại phòng '{bot_channel.name}' tại guild {guild_id}. Đã hủy timer 30s.")
            return

        # Phòng không có người nào ngoài bot -> Khởi động bộ đếm 30s tự động rời phòng
        existing_task = self._empty_voice_tasks.get(guild_id)
        if existing_task and not existing_task.done():
            return  # Đã có timer 30s đang đếm ngược

        log.info(f"[Music] Kênh voice '{bot_channel.name}' không còn ai (guild {guild_id}). Bắt đầu đếm ngược 30s tự động out.")
        task = asyncio.create_task(self._handle_empty_voice(guild_id, bot_channel.id))
        self._empty_voice_tasks[guild_id] = task

    async def _handle_empty_voice(self, guild_id: int, channel_id: int):
        """Xử lý rời kênh khi phòng voice trống sau 30 giây (không block event loop)."""
        try:
            await asyncio.sleep(30)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            vc = guild.voice_client
            bot_channel = vc.channel if (vc and vc.is_connected()) else (guild.me.voice.channel if (guild.me and guild.me.voice) else None)

            # Nếu bot không còn ở trong kênh ban đầu hoặc đã rời
            if not bot_channel or bot_channel.id != channel_id:
                return

            # Kiểm tra lần cuối xem có người nào vào lại không
            if any(not m.bot for m in bot_channel.members):
                return

            player = self._players.get(guild_id)
            log.info(f"[Music] Phòng voice '{bot_channel.name}' đã trống 30s tại guild {guild_id}. Bot tự động rời kênh.")

            # Gửi thông báo nếu có kênh text
            channel_to_notify = player.text_channel if player else None
            if channel_to_notify:
                try:
                    s = await async_get_guild_settings(str(guild_id))
                    await channel_to_notify.send(tr(s, "music.empty_voice_left"), delete_after=60)
                except Exception:
                    pass

            # Dừng và rời kênh an toàn
            if player:
                await player.stop()
                self._drop(guild_id)
            elif vc and vc.is_connected():
                try:
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            elif guild.me and guild.me.voice and guild.me.voice.channel:
                try:
                    await guild.change_voice_state(channel=None)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"[Music] empty voice handler error: {e}")
        finally:
            self._empty_voice_tasks.pop(guild_id, None)

    # ── Basic commands ─────────────────────────────────────────────────────
    @commands.hybrid_command(name="join", description="Gọi bot vào kênh voice")
    async def join(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        if await self._ensure(ctx):
            ch_name = ctx.author.voice.channel.name if (ctx.author.voice and ctx.author.voice.channel) else ""
            await ctx.send(tr(s, "music.joined_voice", channel=ch_name), ephemeral=True)

    @commands.hybrid_command(name="leave", description="Bắt bot rời kênh voice")
    async def leave(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        g_vc = ctx.guild.voice_client
        me_voice = ctx.guild.me.voice if ctx.guild.me else None

        if not player and not g_vc and not (me_voice and me_voice.channel):
            await ctx.send(tr(s, "music.not_in_voice"))
            return

        if player:
            await player.stop()
            self._drop(ctx.guild.id)

        # Fallback dọn dẹp kết nối voice vật lý nếu player bị drop trước đó (chống ghost voice)
        if g_vc and g_vc.is_connected():
            try:
                if g_vc.is_playing() or g_vc.is_paused():
                    g_vc.stop()
                await g_vc.disconnect(force=True)
            except Exception as e:
                log.debug(f"[Music] leave g_vc disconnect error: {e}")
        elif me_voice and me_voice.channel:
            try:
                await ctx.guild.change_voice_state(channel=None)
            except Exception as e:
                log.debug(f"[Music] leave change_voice_state error: {e}")

        await ctx.send(tr(s, "music.left_voice"))

    @commands.hybrid_command(name="play", description="Phát nhạc từ YouTube hoặc Spotify (tên bài hoặc link)")
    @app_commands.describe(query="Tên bài hát, link YouTube hoặc link Spotify")
    async def play(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        _t0 = time.time()
        s = await async_get_guild_settings(str(ctx.guild.id))

        # Nếu không phải Spotify → bắt đầu extract NGAY (song song với việc kết nối voice)
        is_spotify = "spotify.com/track" in query or "spotify.link" in query
        info_task = None if is_spotify else asyncio.create_task(extract_info(query))

        # Kết nối voice (chạy song song với extract)
        player = await self._ensure(ctx)
        if not player:
            if info_task:
                info_task.cancel()
            return

        # Chờ kết quả extract (đã chạy song song với _ensure ở trên)
        if info_task:
            info = await info_task
        else:
            resolved_query = await _resolve_external_url(query)
            info = await extract_info(resolved_query)

        if not info:
            await ctx.send(tr(s, "music.not_found", query=query))
            return

        log.info(f"[Music][timing] play ready in {time.time() - _t0:.2f}s (query='{query[:40]}')")

        track = Track(info, requester=ctx.author)

        if player.vc.is_playing() or player.vc.is_paused() or player.current:
            if len(player.queue) >= MAX_QUEUE_SIZE:
                await ctx.send(tr(s, "music.queue_full", max=MAX_QUEUE_SIZE), ephemeral=True)
                return
            player.queue.append(track)
            embed = discord.Embed(
                title=embed_title("zb_play", tr(s, "music.added_to_queue")),
                description=f"**[{track.title}]({track.url})**",
                color=0x3B82F6,
            )
            embed.add_field(name=tr(s, "music.duration_field"),   value=f"`{track.duration_str}`", inline=True)
            embed.add_field(name=tr(s, "music.position_field"),   value=f"`#{len(player.queue)}`", inline=True)
            embed.add_field(name=tr(s, "music.requester_field"),  value=ctx.author.mention,         inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await ctx.send(embed=embed)
        else:
            await player.add_and_play(track)
            if ctx.interaction:
                try:
                    await ctx.interaction.delete_original_response()
                except Exception as e:
                    log.debug(f"[Music] delete_original_response error: {e}")

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Xem bài hát đang phát và thanh tiến trình")
    async def nowplaying(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.current or not (player.vc and player.vc.is_connected()):
            await ctx.send(tr(s, "music.no_song_playing"), ephemeral=True)
            return

        elapsed = player.get_elapsed()
        embed = _make_np_embed(player.current, player.queue, player.loop_mode, player.volume, elapsed, s)
        view = MusicControlView(player, s)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="lyrics", description="Xem lời bài hát đang phát hoặc tìm theo tên")
    @app_commands.describe(query="Tên bài hát cần tìm lời (để trống nếu muốn lấy bài đang phát)")
    async def lyrics(self, ctx: commands.Context, *, query: str = None):
        s = await async_get_guild_settings(str(ctx.guild.id))
        target_query = query
        if not target_query:
            player = self._get(ctx.guild.id)
            if player and player.current:
                target_query = player.current.title
            else:
                await ctx.send(tr(s, "music.lyrics_no_track"), ephemeral=True)
                return

        # Defer vì gọi API LrcLib có thể mất vài giây
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer()

        lyrics_text, track_title = await _fetch_lyrics_from_lrclib(target_query)
        if not lyrics_text:
            display_title = target_query[:50]
            msg = tr(s, "music.lyrics_not_found", query=display_title)
            await ctx.send(msg)
            return

        pages = _chunk_lyrics(lyrics_text, max_chars=1800)
        display_name = track_title or target_query

        if len(pages) == 1:
            embed = discord.Embed(
                title=f"📜 {display_name}",
                description=pages[0],
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Trang 1/1 • Nguồn: LrcLib | {tr(s, 'common.requested_by', user=ctx.author.display_name)}")
            await ctx.send(embed=embed)
        else:
            view = LyricsPaginatorView(pages, display_name, ctx.author.id, s)
            embed = view.get_embed()
            embed.set_footer(text=f"Trang 1/{len(pages)} • Nguồn: LrcLib | {tr(s, 'common.requested_by', user=ctx.author.display_name)}")
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

    @commands.hybrid_command(name="volume", description="Điều chỉnh âm lượng phát nhạc (1-150%)")
    @app_commands.describe(level="Mức âm lượng (1 - 150)")
    async def volume(self, ctx: commands.Context, level: int = None):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not (player.vc.is_playing() or player.vc.is_paused()):
            await ctx.send(tr(s, "music.not_playing"))
            return

        if level is None:
            current_vol = int(player.volume * 100)
            await ctx.send(tr(s, "music.volume_current", vol=current_vol))
            return

        if level < 1 or level > 150:
            await ctx.send(tr(s, "music.volume_invalid"), ephemeral=True)
            return

        player.set_volume(level / 100.0)
        is_delayed = bool(player.vc and player.vc.source and not isinstance(player.vc.source, discord.PCMVolumeTransformer))
        if is_delayed and level != 100:
            await ctx.send(f"{tr(s, 'music.volume_changed', vol=level)}\n*ℹ️ {tr(s, 'music.vol_applies_next')}*")
        else:
            await ctx.send(tr(s, "music.volume_changed", vol=level))

    @commands.hybrid_command(name="shuffle", description="Xáo trộn ngẫu nhiên thứ tự bài hát trong hàng chờ")
    async def shuffle(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or len(player.queue) < 2:
            await ctx.send(tr(s, "music.shuffle_empty"), ephemeral=True)
            return

        player.shuffle()
        await ctx.send(tr(s, "music.queue_shuffled", count=len(player.queue)))

    @commands.hybrid_command(name="stop", description="Dừng nhạc và rời kênh")
    async def stop(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        g_vc = ctx.guild.voice_client
        me_voice = ctx.guild.me.voice if ctx.guild.me else None

        if not player and not g_vc and not (me_voice and me_voice.channel):
            await ctx.send(tr(s, "music.not_playing"))
            return

        if player:
            await player.stop()
            self._drop(ctx.guild.id)

        # Fallback dọn dẹp vật lý nếu bot vẫn còn kẹt trong voice (chống ghost voice)
        if g_vc and g_vc.is_connected():
            try:
                if g_vc.is_playing() or g_vc.is_paused():
                    g_vc.stop()
                await g_vc.disconnect(force=True)
            except Exception as e:
                log.debug(f"[Music] stop g_vc disconnect error: {e}")
        elif me_voice and me_voice.channel:
            try:
                await ctx.guild.change_voice_state(channel=None)
            except Exception as e:
                log.debug(f"[Music] stop change_voice_state error: {e}")

        await ctx.send(tr(s, "music.stopped_left"), delete_after=60)

    @commands.hybrid_command(name="skip", description="Bỏ qua bài hát hiện tại")
    async def skip(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not (player.vc.is_playing() or player.vc.is_paused()):
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.skip()
        await ctx.send(tr(s, "music.skipped"), ephemeral=True)

    @commands.hybrid_command(name="pause", description="Tạm dừng nhạc")
    async def pause(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.vc.is_playing():
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.vc.pause()
        player.pause_start = time.time()
        await ctx.send(tr(s, "music.paused"), ephemeral=True)

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc")
    async def resume(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.vc.is_paused():
            await ctx.send(tr(s, "music.not_paused"))
            return
        player.vc.resume()
        if player.pause_start > 0:
            player.total_paused_time += time.time() - player.pause_start
            player.pause_start = 0.0
        await ctx.send(tr(s, "music.resumed"), ephemeral=True)

    @commands.hybrid_command(name="loop", description="Bật/tắt chế độ lặp lại")
    async def loop(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.loop_mode = (player.loop_mode + 1) % 3
        msg_list = [tr(s, "music.loop_off_msg"), tr(s, "music.loop_one_msg"), tr(s, "music.loop_all_msg")]
        await ctx.send(msg_list[player.loop_mode])

    @commands.hybrid_command(name="autoplay", description="Bật/tắt chế độ tự động phát bài hát tương tự khi hết hàng chờ")
    async def autoplay_cmd(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send(tr(s, "music.no_song_playing"), ephemeral=True)
            return
        player.autoplay = not player.autoplay
        if player.now_playing_msg:
            try:
                view = MusicControlView(player, s)
                await player.now_playing_msg.edit(view=view)
            except Exception:
                pass
        key = "music.autoplay_on" if player.autoplay else "music.autoplay_off"
        await ctx.send(tr(s, key), ephemeral=True)

    @commands.hybrid_command(name="queue", description="Xem hàng chờ nhạc")
    async def queue_cmd(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or (not player.current and not player.queue):
            await ctx.send(tr(s, "music.queue_empty_msg"))
            return
        desc = ""
        if player.current:
            desc += f"{tr(s, 'music.np_header')} [{player.current.title}]({player.current.url}) `[{player.current.duration_str}]`\n\n"
        if player.queue:
            desc += f"{tr(s, 'music.queue_header')}\n"
            for i, t in enumerate(player.queue[:10], 1):
                desc += f"`{i:2}.` [{t.title}]({t.url}) `[{t.duration_str}]`\n"
            if len(player.queue) > 10:
                desc += tr(s, "music.queue_more", cnt=len(player.queue) - 10)
        embed = discord.Embed(title=embed_title("zb_queue", tr(s, "music.queue_title")), description=desc, color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="replay", description="Phát lại bài hát từ đầu")
    async def replay(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.current:
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.queue.insert(0, player.current)
        player.skip()
        await ctx.send(tr(s, "music.replayed"), ephemeral=True)

    @commands.hybrid_command(name="lofi", description="Phát nhạc Lofi 24/7 (mặc định YouTube)")
    @app_commands.describe(source="Nguồn lofi (mặc định: youtube — live stream Lofi Girl)")
    @app_commands.autocomplete(source=lofi_autocomplete)
    async def lofi(self, ctx: commands.Context, source: str = None):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        src_key = source if source else "youtube"
        if src_key not in LOFI_STREAMS:
            await ctx.send(tr(s, "music.invalid_source"))
            return
        stream = LOFI_STREAMS.get(src_key, LOFI_STREAMS["youtube"])

        player = await self._ensure(ctx)
        if not player:
            return

        if src_key == "soma":
            track = Track(
                {"title": stream["title"], "url": stream["url"], "webpage_url": stream["url"], "duration": -1, "is_live": True},
                requester=ctx.author,
            )
            track.is_live = True
            track.stream_url = stream["url"]
            track.stream_expire = float("inf")  # stream sống mãi, không expire
            await player.add_and_play(track)
            await ctx.send(f"{e('zb_lofi')} " + tr(s, "music.lofi_soma_success", name=stream['name']))
        else:
            info = await extract_info(stream["url"], force_refresh=True)
            if not info:
                await ctx.send(tr(s, "music.lofi_yt_err"))
                return
            track = Track(info, requester=ctx.author)
            track.is_live = True
            await player.add_and_play(track)
            await ctx.send(f"{e('zb_lofi')} " + tr(s, "music.lofi_yt_success", name=stream['name']))

    # ── Queue & Navigation Management ──────────────────────────────────────
    @commands.hybrid_command(name="seek", description="Tua đến vị trí chỉ định trong bài hát (VD: 1:30 hoặc 90)")
    @app_commands.describe(position="Vị trí thời gian muốn tua tới (VD: 1:30 hoặc 90)")
    async def seek_cmd(self, ctx: commands.Context, position: str):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.current or not (player.vc and player.vc.is_connected()):
            await ctx.send(tr(s, "music.no_song_playing"), ephemeral=True)
            return

        curr = player.current
        if curr.duration is None or curr.duration <= 0:
            await ctx.send(tr(s, "music.seek_live_err"), ephemeral=True)
            return

        target_sec = _parse_time_str(position)
        if target_sec is None or target_sec < 0:
            await ctx.send(tr(s, "music.seek_invalid"), ephemeral=True)
            return

        if target_sec >= curr.duration:
            await ctx.send(
                tr(s, "music.seek_range_err", target=_fmt_duration(target_sec), duration=curr.duration_str),
                ephemeral=True,
            )
            return

        await ctx.defer()
        await player._play(curr, seek_offset=target_sec)
        await ctx.send(tr(s, "music.seek_success", time=_fmt_duration(target_sec)))

    @commands.hybrid_command(name="search", description="Tìm kiếm bài hát và chọn từ top 5 kết quả")
    @app_commands.describe(query="Tên bài hát cần tìm kiếm")
    async def search_cmd(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = await self._ensure(ctx)
        if not player:
            return

        clean_q = clean_youtube_query(query)
        if not clean_q.startswith("http") and not clean_q.startswith("ytsearch:"):
            clean_q = f"ytsearch5:{clean_q}"
        elif clean_q.startswith("ytsearch:") and not clean_q.startswith("ytsearch5:"):
            clean_q = clean_q.replace("ytsearch:", "ytsearch5:", 1)

        async with _extract_semaphore:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: _get_ydl_flat().extract_info(clean_q, download=False))

        if not info or "entries" not in info or not info.get("entries"):
            await ctx.send(tr(s, "music.not_found", query=query))
            return

        entries = [e for e in info.get("entries") if e][:5]
        if not entries:
            await ctx.send(tr(s, "music.not_found", query=query))
            return

        view = SearchSelectView(entries, ctx.author, player, s)
        desc = ""
        for i, item in enumerate(entries, 1):
            title = item.get("title", "Unknown")
            dur = _fmt_duration(item.get("duration"))
            uploader = item.get("uploader") or item.get("channel") or "Unknown"
            desc += f"`{i}.` **{title}** `[{dur}]` — *{uploader}*\n"

        embed = discord.Embed(
            title=f"🔍 Kết quả tìm kiếm: {query[:60]}",
            description=desc,
            color=0x5865F2,
        )
        embed.set_footer(text="Chọn bài hát từ menu bên dưới (hết hạn sau 60s)")
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @commands.hybrid_command(name="remove", description="Xóa một bài hát khỏi hàng chờ theo vị trí")
    @app_commands.describe(position="Vị trí của bài hát trong hàng chờ (bắt đầu từ 1)")
    async def remove_cmd(self, ctx: commands.Context, position: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.queue:
            await ctx.send(tr(s, "music.queue_empty_msg"), ephemeral=True)
            return

        if position < 1 or position > len(player.queue):
            await ctx.send(tr(s, "music.remove_invalid", max=len(player.queue)), ephemeral=True)
            return

        removed = player.queue.pop(position - 1)
        await ctx.send(tr(s, "music.removed_from_queue", title=removed.title, url=removed.url))

    @commands.hybrid_command(name="clearqueue", aliases=["cq", "qclear"], description="Xóa sạch toàn bộ bài hát trong hàng chờ")
    async def clearqueue_cmd(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.queue:
            await ctx.send(tr(s, "music.queue_empty_msg"), ephemeral=True)
            return

        cnt = len(player.queue)
        player.queue.clear()
        await ctx.send(tr(s, "music.queue_cleared", count=cnt))

    @commands.hybrid_command(name="jump", description="Nhảy ngay tới bài hát chỉ định trong hàng chờ")
    @app_commands.describe(position="Vị trí bài hát muốn nhảy tới (bắt đầu từ 1)")
    async def jump_cmd(self, ctx: commands.Context, position: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.queue:
            await ctx.send(tr(s, "music.queue_empty_msg"), ephemeral=True)
            return

        if position < 1 or position > len(player.queue):
            await ctx.send(tr(s, "music.jump_invalid", max=len(player.queue)), ephemeral=True)
            return

        target_track = player.queue[position - 1]
        player.queue = player.queue[position - 1:]
        player.skip()
        await ctx.send(tr(s, "music.jumped", title=target_track.title, url=target_track.url))

    # ── Playlist commands ──────────────────────────────────────────────────
    @commands.hybrid_group(name="playlist", description="Quản lý playlist nhạc")
    async def playlist_group(self, ctx: commands.Context):
        pass

    @playlist_group.command(name="create", description="Tạo một playlist mới")
    @app_commands.describe(name="Tên playlist muốn tạo")
    async def playlist_create(self, ctx: commands.Context, *, name: str):
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if pl:
            await ctx.send(tr(s, "music.pl_exists", name=name))
        else:
            await db.async_create_playlist(str(ctx.guild.id), name, str(ctx.author.id), ctx.author.display_name)
            await ctx.send(tr(s, "music.pl_created", name=name))

    @playlist_group.command(name="add", description="Thêm bài hát vào playlist")
    @app_commands.describe(query="Link hoặc tên bài hát", name="Tên playlist")
    async def playlist_add(self, ctx: commands.Context, query: str, *, name: str):
        await ctx.defer()
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(tr(s, "music.pl_not_found", name=name))
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send(tr(s, "music.pl_no_perm"))
            return
        
        resolved = await _resolve_external_url(query)
        info = await extract_metadata(resolved)
        if not info:
            await ctx.send(tr(s, "music.pl_song_not_found"))
            return

        thumbnail = _get_best_thumbnail(info)
        video_id = info.get("id", "")
        webpage_url = info.get("webpage_url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else info.get("url", ""))
        song_title = info.get("title") or info.get("fulltitle") or query.strip()

        await db.async_add_track_to_playlist(pl["id"], {
            "title": song_title,
            "id":    video_id,
            "webpage_url": webpage_url,
            "duration": info.get("duration") or -1,
            "uploader": info.get("uploader") or info.get("channel") or "—",
            "thumbnail": thumbnail,
            "url": "",
        })
        await ctx.send(tr(s, "music.pl_added_song", title=song_title, name=name))

    async def _load_playlist_background(self, player: MusicPlayer, tracks: list, requester: discord.Member):
        """Nạp ngầm các bài còn lại từ playlist vào hàng chờ theo batch 2 bài (bảo vệ RAM/CPU & tránh rate-limit)."""
        batch_size = 2
        slice_tracks = tracks[:MAX_BG_LOAD]
        added_any = False
        for i in range(0, len(slice_tracks), batch_size):
            if player._manual_stopped or not player.vc or not player.vc.is_connected():
                break
            chunk = slice_tracks[i:i + batch_size]

            async def _load_one(t_data):
                url_q = t_data.get("webpage_url") or ""
                title_q = t_data.get("title") or ""
                primary = url_q or title_q
                info = None
                try:
                    if primary:
                        info = await extract_info(primary)
                    # Nếu URL thất bại hoặc đổi ID, fallback tìm theo title
                    if not info and title_q and primary != title_q:
                        info = await extract_info(title_q)
                    if info:
                        return Track(info, requester=requester)
                except Exception as e:
                    log.warning(f"[Music] Background load track error ({primary}): {e}")
                return None

            batch_results = await asyncio.gather(*[_load_one(t) for t in chunk])
            for trk in batch_results:
                if trk:
                    if not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
                        await player.add_and_play(trk)
                    else:
                        if len(player.queue) >= MAX_QUEUE_SIZE:
                            log.info(f"[Music] Playlist background load: dừng nạp vì hàng chờ đạt trần {MAX_QUEUE_SIZE} bài")
                            break
                        player.queue.append(trk)
                    added_any = True
            await asyncio.sleep(0.4)

        if added_any:
            try:
                await player.update_now_playing()
            except Exception:
                pass

        if len(tracks) > MAX_BG_LOAD:
            log.info(f"[Music] Playlist background load: chỉ nạp {MAX_BG_LOAD}/{len(tracks)} bài (giới hạn bảo vệ)")

    @playlist_group.command(name="play", description="Phát toàn bộ playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_play(self, ctx: commands.Context, *, name: str):
        await ctx.defer()
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl or not pl.get("tracks"):
            await ctx.send(tr(s, "music.pl_empty", name=name))
            return
        player = await self._ensure(ctx)
        if not player:
            return
        
        tracks = pl["tracks"]
        msg = await ctx.send(tr(s, "music.pl_loading_first", name=name))
        
        # 1. Tìm và phát bài hát đầu tiên tải thành công ngay lập tức
        first_track = None
        start_index = 0
        for idx, t_data in enumerate(tracks):
            url_q = t_data.get("webpage_url") or ""
            title_q = t_data.get("title") or ""
            primary = url_q or title_q
            info = None
            if primary:
                info = await extract_info(primary)
            if not info and title_q and primary != title_q:
                info = await extract_info(title_q)
            if info:
                first_track = Track(info, requester=ctx.author)
                start_index = idx
                break

        if first_track:
            if not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
                await player.add_and_play(first_track)
            else:
                if len(player.queue) >= MAX_QUEUE_SIZE:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return await ctx.send(tr(s, "music.queue_full", max=MAX_QUEUE_SIZE), ephemeral=True)
                player.queue.append(first_track)
            
            # Xóa tin nhắn tạm "Đang tải playlist..." ngay khi phát bài đầu tiên
            try:
                await msg.delete()
            except Exception:
                pass

            remaining = tracks[start_index + 1:]
            if remaining:
                task = asyncio.create_task(self._load_playlist_background(player, remaining, ctx.author))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
        else:
            await msg.edit(content=tr(s, "music.pl_fail_first", name=name))

    @playlist_group.command(name="show", description="Xem danh sách bài trong playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_show(self, ctx: commands.Context, *, name: str):
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl or not pl.get("tracks"):
            await ctx.send(tr(s, "music.pl_empty", name=name))
            return
        desc = ""
        for i, t in enumerate(pl["tracks"], 1):
            title = t.get("title", "Unknown")
            dur   = _fmt_duration(t.get("duration", 0))
            desc += f"`{i:2}.` **{title}** `[{dur}]`\n"
            if i >= 15:
                rem = len(pl["tracks"]) - 15
                if rem > 0:
                    desc += tr(s, "music.queue_more", cnt=rem)
                break
        embed = discord.Embed(title=f"🎵 Playlist: {pl['name']}", description=desc, color=0x5865F2)
        if pl.get("creator_name"):
            embed.set_footer(text=tr(s, "music.pl_footer", user=pl['creator_name'], cnt=len(pl['tracks'])))
        await ctx.send(embed=embed)

    @playlist_group.command(name="remove", description="Xóa playlist do bạn tạo")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_remove(self, ctx: commands.Context, *, name: str):
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(tr(s, "music.pl_not_found", name=name))
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send(tr(s, "music.pl_del_no_perm"))
            return
        await db.async_delete_playlist(pl["id"], str(ctx.guild.id))
        await ctx.send(tr(s, "music.pl_deleted", name=name))

    @playlist_group.command(name="removesong", description="Xóa một bài hát khỏi playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_removesong(self, ctx: commands.Context, *, name: str):
        import database as db
        s = await async_get_guild_settings(str(ctx.guild.id))
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(tr(s, "music.pl_not_found", name=name))
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send(tr(s, "music.pl_edit_no_perm"))
            return
        if not pl.get("tracks"):
            await ctx.send(tr(s, "music.pl_empty", name=name))
            return
        desc = ""
        for i, t in enumerate(pl["tracks"], 1):
            title = t.get("title", "Unknown")
            dur   = _fmt_duration(t.get("duration", 0))
            desc += f"`{i:2}.` **{title}** `[{dur}]`\n"
            if i >= 20:
                rem = len(pl["tracks"]) - 20
                if rem > 0:
                    desc += f"\n*... và {rem} bài khác (menu hiển thị tối đa 25 bài)*"
                break
        embed = discord.Embed(
            title=tr(s, "music.pl_del_title", name=pl['name']),
            description=desc,
            color=discord.Color.red(),
        )
        embed.set_footer(text=tr(s, "music.pl_del_footer"))
        view = RemoveSongView(ctx, pl, pl["tracks"])
        view.message = await ctx.send(embed=embed, view=view)

    @playlist_group.command(name="loop", description="Đổi chế độ lặp lại hàng chờ")
    async def playlist_loop(self, ctx: commands.Context):
        import database as db
        s = await db.async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send(tr(s, "music.no_song"))
            return
        player.loop_mode = (player.loop_mode + 1) % 3
        loop_msgs = [tr(s, "music.loop_off"), tr(s, "music.loop_one"), tr(s, "music.loop_all")]
        await ctx.send(loop_msgs[player.loop_mode])

    @commands.hybrid_command(name="topmusic", description="Bảng xếp hạng bài hát được nghe nhiều nhất trong server")
    async def topmusic(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        top_songs = await async_get_top_played_songs(str(ctx.guild.id), limit=10)
        if not top_songs:
            return await ctx.send(tr(s, "music.top_empty"))

        desc = ""
        medals = ["🥇", "🥈", "🥉"]
        for idx, item in enumerate(top_songs):
            rank = medals[idx] if idx < 3 else f"`#{idx+1:2}`"
            # `get_top_played_songs` trả về {"title", "play_count"}; hàng cũ có thể
            # còn dạng "<video_id>|<tên bài>" → chỉ lấy phần tên bài.
            raw_title = str(item.get("title") or "?")
            title = raw_title.split("|", 1)[-1]
            count = int(item.get("play_count") or 0)
            desc += f"{rank} **{title}** — **{count:,}** lần nghe\n"

        embed = discord.Embed(
            title=embed_title("zb_music", tr(s, "music.top_title")),
            description=desc,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

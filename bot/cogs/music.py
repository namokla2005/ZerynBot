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
import os
import time
import logging
import random
import re

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from cache import cache
from database import async_get_guild_settings
from i18n import tr

log = logging.getLogger("BotV2.Music")

# ─── Opus Library Discovery (Termux / Linux / Windows / macOS) ───────────────
def load_opus_library() -> bool:
    """Tự động phát hiện và nạp libopus cho Termux, Linux, Windows, macOS."""
    if discord.opus.is_loaded():
        return True

    opus_candidates = [
        # 1. Android Termux
        "/data/data/com.termux/files/usr/lib/libopus.so",
        "/data/data/com.termux/files/usr/lib/libopus.so.0",
        "/data/data/com.termux/files/usr/lib/libopus.so.0.8.0",
        # 2. Linux chuẩn & ARM Linux
        "libopus.so.0",
        "libopus.so",
        "/usr/lib/libopus.so.0",
        "/usr/lib/libopus.so",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/x86_64-linux-gnu/libopus.so",
        "/usr/lib/arm-linux-gnueabihf/libopus.so.0",
        "/usr/local/lib/libopus.so.0",
        "/usr/local/lib/libopus.so",
        # 3. macOS
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.dylib",
        "libopus.dylib",
        # 4. Windows
        "libopus-0.x86_64.dll",
        "libopus-0.x86.dll",
        "opus.dll",
    ]

    for candidate in opus_candidates:
        try:
            discord.opus.load_opus(candidate)
            if discord.opus.is_loaded():
                log.info(f"[Opus] Loaded Opus library successfully from: {candidate}")
                return True
        except Exception:
            continue

    try:
        import ctypes.util
        lib = ctypes.util.find_library("opus")
        if lib:
            discord.opus.load_opus(lib)
            if discord.opus.is_loaded():
                log.info(f"[Opus] Loaded Opus library via ctypes: {lib}")
                return True
    except Exception:
        pass

    log.warning("[Opus] libopus not found. Voice playback may require libopus installed (e.g. 'pkg install libopus' on Termux).")
    return False

load_opus_library()

# ─── FFmpeg options tối ưu cho ARM ─────────────────────────────────────────────
FFMPEG_BEFORE = '-loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 1M -analyzeduration 1000000 -user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"'
FFMPEG_OPTS_COPY   = "-vn -sn -c:a copy -threads 1"
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1"

MAX_PLAYERS = 6  # Giới hạn player đồng thời (tối ưu cho tablet 4GB, 10+ server)
MAX_BG_LOAD = 50  # Giới hạn số bài nạp ngầm từ playlist (bảo vệ RAM/CPU tablet)

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
    """Gợi ý dropdown SomaFM / YouTube cho slash command /lofi."""
    choices = [
        app_commands.Choice(name="🎧 SomaFM Groove Salad (ổn định 24/7)", value="soma"),
        app_commands.Choice(name="📺 YouTube Lofi Girl (live stream)", value="youtube"),
    ]
    if current:
        choices = [c for c in choices if current.lower() in c.value.lower() or current.lower() in c.name.lower()]
    return choices[:25]


_COOKIE_FILE = os.environ.get("YTDLP_COOKIEFILE", None)

YDL_OPTS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "socket_timeout": 8,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web_creator", "web"],
        }
    },
    "nocheckcertificate": True,
    "ignoreerrors": True,
}
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    YDL_OPTS["cookiefile"] = _COOKIE_FILE

# Cấu hình Flat Extraction siêu tốc (chỉ lấy metadata, không tải trang player & không giải mã stream)
YDL_OPTS_FLAT = {
    "extract_flat": True,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "socket_timeout": 5,
    "nocheckcertificate": True,
    "ignoreerrors": True,
}
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    YDL_OPTS_FLAT["cookiefile"] = _COOKIE_FILE

_extract_semaphore = asyncio.Semaphore(3)


def _fmt_duration(seconds) -> str:
    if seconds is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        return "🔴 LIVE"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


async def _resolve_external_url(query: str) -> str:
    """Tự động phân giải link Spotify qua oEmbed API thành truy vấn tìm kiếm YouTube."""
    q_strip = query.strip()
    if "spotify.com/track" in q_strip or "spotify.link" in q_strip:
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={q_strip}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
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
    """Đồng bộ yt-dlp (chạy trong thread pool)."""
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            clean_q = clean_youtube_query(query)
            if not clean_q.startswith("http") and not clean_q.startswith("ytsearch:"):
                clean_q = f"ytsearch1:{clean_q}"
            elif clean_q.startswith("ytsearch:") and not clean_q.startswith("ytsearch1:"):
                clean_q = clean_q.replace("ytsearch:", "ytsearch1:", 1)

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

        with yt_dlp.YoutubeDL(YDL_OPTS_FLAT) as ydl:
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


def _find_related_track_sync(current_title: str, current_uploader: str, history: list[str] | None = None) -> dict | None:
    """Tìm bài hát liên quan / cùng thể loại khi bật chế độ Autoplay."""
    try:
        hist = history or []
        # Chuẩn hóa title: loại bỏ các tag rác như [Official MV], (Remix), etc.
        clean_title = re.sub(
            r"\[.*?\]|\(.*?\)|official\s*music\s*video|official\s*video|official\s*audio|lyrics\s*video|mv|audio",
            "",
            current_title,
            flags=re.IGNORECASE
        ).strip()
        uploader_clean = re.sub(r"-\s*topic|vevo", "", current_uploader, flags=re.IGNORECASE).strip()

        queries = [
            f"ytsearch10:{clean_title} {uploader_clean}",
            f"ytsearch10:{clean_title} related audio mix",
            f"ytsearch10:{clean_title}"
        ]

        with yt_dlp.YoutubeDL(YDL_OPTS_FLAT) as ydl:
            for search_q in queries:
                try:
                    info = ydl.extract_info(search_q, download=False)
                    if not info or "entries" not in info:
                        continue
                    entries = [e for e in info.get("entries") if e]
                    for entry in entries:
                        title = entry.get("title", "")
                        url = entry.get("webpage_url") or entry.get("url") or ""
                        vid = entry.get("id") or ""

                        if not title:
                            continue

                        # Không lặp lại bài hiện tại hoặc bài trong lịch sử
                        if any(h and (h.lower() in title.lower() or h == vid or (url and h in url)) for h in hist):
                            continue
                        if title.lower().strip() == current_title.lower().strip():
                            continue

                        # Giới hạn thời lượng bài nhạc chuẩn (30s - 15 phút)
                        dur = entry.get("duration") or 0
                        if dur > 0 and (dur < 30 or dur > 900):
                            continue

                        return entry
                except Exception:
                    continue
    except Exception as e:
        log.warning(f"[Music] Autoplay search failed: {e}")
    return None


async def extract_info(query: str) -> dict | None:
    """Lấy thông tin bài hát đầy đủ bao gồm stream audio (cho lệnh phát nhạc)."""
    key = query.strip().lower()
    cache_key = f"song_info:{key}"

    # 1. Kiểm tra RAM Cache wrapper
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    # 2. Chạy yt-dlp trong thread pool (giới hạn đồng thời bằng semaphore)
    async with _extract_semaphore:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, _extract_sync, query)

    if info:
        # Lưu vào In-Memory Cache (TTL 10 phút)
        await cache.aset(cache_key, info, ttl=600)

    return info


async def extract_metadata(query: str) -> dict | None:
    """Lấy nhanh thông tin cơ bản bài hát cho Playlist / Search (Flat Extraction + RAM Cache 24h)."""
    key = query.strip().lower()
    cache_key = f"song_meta:{key}"

    # 1. Kiểm tra RAM Cache (trả về tức thì 0ms)
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    # 2. Chạy Flat Extraction siêu tốc trong thread pool
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


def _get_stream_url(info: dict) -> str | None:
    """Lấy URL stream tốt nhất từ info dict (lọc bỏ storyboard/mhtml)."""
    if not info:
        return None

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

    # 1. Ưu tiên opus audio-only
    for f in valid_formats:
        acodec = (f.get("acodec") or "").lower()
        vcodec = (f.get("vcodec") or "").lower()
        if acodec == "opus" and vcodec in ("none", "", "null"):
            return f["url"]

    # 2. Ưu tiên audio-only bất kỳ (m4a, webm, mp3, aac)
    for f in valid_formats:
        vcodec = (f.get("vcodec") or "").lower()
        if vcodec in ("none", "", "null"):
            return f["url"]

    # 3. Fallback: Lựa chọn luồng có audio bitrate (abr) tốt nhất
    if valid_formats:
        best_audio = max(valid_formats, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))
        return best_audio["url"]

    # 4. Trực tiếp info.get("url") nếu hợp lệ
    direct_url = info.get("url")
    if direct_url and direct_url.startswith("http") and not any(x in direct_url for x in ["storyboard", ".jpg", ".png", ".mhtml"]):
        return direct_url

    return None


def _get_best_thumbnail(info: dict) -> str:
    thumbnails = info.get("thumbnails", [])
    if thumbnails and isinstance(thumbnails, list):
        valid = [t for t in thumbnails if t.get("url") and t.get("url").startswith("http")]
        if valid:
            best = max(valid, key=lambda t: t.get("width") or 0)
            return best.get("url") or ""
    return info.get("thumbnail") or ""


# ─── Track ─────────────────────────────────────────────────────────────────────
class Track:
    __slots__ = ("title", "url", "stream_url", "stream_expire", "duration", "uploader", "thumbnail", "requester")

    def __init__(self, info: dict, requester: discord.Member | None = None):
        self.title         = info.get("title", "Unknown")
        self.url           = info.get("webpage_url") or info.get("url", "")
        self.stream_url    = _get_stream_url(info)
        self.stream_expire = time.time() + (5.5 * 3600) if self.stream_url else 0
        self.duration      = info.get("duration")
        self.uploader      = info.get("uploader") or info.get("channel") or "—"
        self.thumbnail     = _get_best_thumbnail(info)
        self.requester     = requester

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
    def __init__(self, guild: discord.Guild, text_channel, vc: discord.VoiceClient):
        self.guild         = guild
        self.text_channel  = text_channel
        self.vc            = vc
        self.loop          = asyncio.get_running_loop()
        self.queue         : list[Track] = []
        self.current       : Track | None = None
        self.loop_mode     = 0   # 0=off  1=loop-one  2=loop-all
        self.autoplay      = False # Autoplay: tự động tìm và phát bài tương tự khi hết hàng chờ
        self._played_history : list[str] = [] # Lưu các bài đã phát để không bị lặp lại trong Autoplay
        self.volume        = 1.0 # 100%
        self.now_playing_msg : discord.Message | None = None
        self.start_time    : float = 0.0
        self.pause_start   : float = 0.0
        self.total_paused_time : float = 0.0
        self._preload_task : asyncio.Task | None = None
        self._inactivity_task : asyncio.Task | None = None
        self._play_lock    = asyncio.Lock()

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
                        await self.text_channel.send(tr(s, "music.auto_leave_inactivity"))
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
                nxt.stream_expire = time.time() + (5.5 * 3600)
        except Exception as e:
            log.debug(f"[Music] Preload error: {e}")

    def _after_play(self, error=None):
        if error:
            log.warning(f"[Music] Player error: {error}")
        if self.current:
            self._played_history.append(self.current.title)
            if len(self._played_history) > 30:
                self._played_history.pop(0)
        if self.loop_mode == 1 and self.current:
            asyncio.run_coroutine_threadsafe(self._play(self.current), self.loop)
        elif self.loop_mode == 2 and self.current:
            self.queue.append(self.current)
            self._dispatch_next()
        else:
            self._dispatch_next()

    def _dispatch_next(self):
        if self.queue:
            self._reset_inactivity_timer()
            asyncio.run_coroutine_threadsafe(self._play(self.queue.pop(0)), self.loop)
        elif self.autoplay and self.current:
            self._reset_inactivity_timer()
            asyncio.run_coroutine_threadsafe(self._handle_autoplay(), self.loop)
        else:
            self.current = None
            asyncio.run_coroutine_threadsafe(self._on_queue_empty(), self.loop)

    async def _handle_autoplay(self):
        """Tự động tìm kiếm và phát bài hát cùng thể loại khi bật Autoplay."""
        if not self.current:
            await self._on_queue_empty()
            return
        last_track = self.current
        try:
            related_info = await asyncio.to_thread(
                _find_related_track_sync,
                last_track.title,
                last_track.uploader,
                self._played_history
            )
            if related_info:
                bot_user = getattr(self.vc, "client", None)
                requester = bot_user.user if (bot_user and hasattr(bot_user, "user")) else None
                new_track = Track(related_info, requester=requester)
                if self.text_channel:
                    try:
                        s = await async_get_guild_settings(str(self.guild.id))
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

        if self.text_channel:
            try:
                s = await async_get_guild_settings(str(self.guild.id))
                await self.text_channel.send(tr(s, "music.queue_empty"))
            except Exception:
                pass

        self._start_inactivity_timer()

    async def _play(self, track: Track):
        async with self._play_lock:
            if not self.vc or not self.vc.is_connected():
                return

            self._reset_inactivity_timer()

            # Lấy stream URL tươi mới nếu chưa có hoặc URL đã hết hạn (sau 5.5h)
            if not track.stream_url or track.is_stream_expired:
                info = await extract_info(track.url or track.title)
                if not info:
                    log.warning(f"[Music] Cannot get stream URL for '{track.title}'")
                    self._dispatch_next()
                    return
                track.stream_url    = _get_stream_url(info)
                track.stream_expire = time.time() + (5.5 * 3600)

            if not track.stream_url:
                log.warning(f"[Music] Cannot resolve stream URL for '{track.title}'")
                if self.text_channel:
                    try:
                        s = await async_get_guild_settings(str(self.guild.id))
                        await self.text_channel.send(
                            tr(s, "music.cannot_decode", title=track.title),
                            delete_after=8,
                        )
                    except Exception:
                        pass
                self._dispatch_next()
                return

            self.current = track
            self.start_time = time.time()
            self.pause_start = 0.0
            self.total_paused_time = 0.0

            # Tự động chọn Opus copy mode nếu stream gốc là Opus WebM (giảm 90% CPU)
            is_opus = (
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
            try:
                if is_opus and self.volume == 1.0:
                    try:
                        source = discord.FFmpegOpusAudio(
                            track.stream_url,
                            before_options=FFMPEG_BEFORE,
                            options=FFMPEG_OPTS_COPY,
                        )
                    except Exception as opus_err:
                        log.debug(f"[Music] FFmpegOpusAudio failed ({opus_err}), fallback to PCMAudio...")
                        source = None

                if source is None:
                    source = discord.FFmpegPCMAudio(
                        track.stream_url,
                        before_options=FFMPEG_BEFORE,
                        options=FFMPEG_OPTS_ENCODE,
                    )
                    if self.volume != 1.0:
                        source = discord.PCMVolumeTransformer(source, volume=self.volume)

                if not discord.opus.is_loaded():
                    load_opus_library()

                self.vc.play(source, after=self._after_play)
            except Exception as e:
                log.error(f"[Music] FFmpeg playback error for '{track.title}': {type(e).__name__} - {e}", exc_info=True)
                if self.text_channel:
                    try:
                        s = await async_get_guild_settings(str(self.guild.id))
                        await self.text_channel.send(
                            tr(s, "music.cannot_decode", title=track.title),
                            delete_after=8,
                        )
                    except Exception:
                        pass
                self._dispatch_next()
                return

            # Gửi embed Now Playing
            await self._send_now_playing()

            # Pre-load bài tiếp theo ở background
            if self.queue:
                if self._preload_task and not self._preload_task.done():
                    self._preload_task.cancel()
                self._preload_task = asyncio.create_task(self._preload_next())

    async def _send_now_playing(self):
        if not self.text_channel or not self.current:
            return
        if self.now_playing_msg:
            try:
                await self.now_playing_msg.delete()
            except Exception:
                pass
        s = await async_get_guild_settings(str(self.guild.id))
        view  = MusicControlView(self, s)
        elapsed = self.get_elapsed()
        embed = _make_np_embed(self.current, self.queue, self.loop_mode, self.volume, elapsed, s)
        try:
            self.now_playing_msg = await self.text_channel.send(embed=embed, view=view)
        except Exception as e:
            log.error(f"[Music] NP embed error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────
    async def add_and_play(self, track: Track):
        self._reset_inactivity_timer()
        if self.vc.is_playing() or self.vc.is_paused() or self.current:
            self.queue.append(track)
        else:
            await self._play(track)

    def skip(self):
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()

    def shuffle(self):
        if len(self.queue) > 1:
            random.shuffle(self.queue)

    def set_volume(self, volume: float):
        self.volume = max(0.01, min(1.5, volume))
        if self.vc and self.vc.source and isinstance(self.vc.source, discord.PCMVolumeTransformer):
            self.vc.source.volume = self.volume

    async def stop(self):
        self._reset_inactivity_timer()
        self.queue.clear()
        self.current   = None
        self.loop_mode = 0
        self.autoplay  = False
        self._played_history.clear()
        if self._preload_task:
            self._preload_task.cancel()
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()
        try:
            await self.vc.disconnect()
        except Exception:
            pass
        if self.now_playing_msg:
            try:
                await self.now_playing_msg.delete()
            except Exception:
                pass
        self.now_playing_msg = None


# ─── Embeds & Helpers ──────────────────────────────────────────────────────────
def _make_progress_bar(elapsed_sec: int, total_sec: int | None, bar_length: int = 40) -> str:
    """Tạo thanh tiến trình phát nhạc nét đậm nổi bật theo phong cách Markdown Bold (40 ký tự)."""
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


def _make_np_embed(track: Track, queue: list, loop_mode: int, volume: float = 1.0, elapsed_sec: int = 0, settings: dict = None) -> discord.Embed:
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
    progress_bar = _make_progress_bar(elapsed_sec, track.duration, bar_length=40)

    embed = discord.Embed(
        color=0x5865F2,  # Discord Blurple (#5865F2) matching Wave Music
        description=(
            f"**{np_title}**\n"
            f"### [{track.title}]({track.url})\n"
            f"**{track.uploader}** — `{dur_badge}` — {track.requester_mention}\n"
            f"────────────────────────────────────────────\n"
            f"**{vol_label}:** `{vol_percent}%` — **{queue_label}:** `{queue_len} {songs_unit}` — **{dur_label}:** `{total_dur_str}`\n\n"
            f"{progress_bar}"
        )
    )

    # Đặt thumbnail ở góc phải trên cùng thay vì ảnh to choáng màn hình
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

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
            self.btn_pause.emoji = "▶️"
        else:
            self.btn_pause.label = tr(self.settings, "music.btn_pause")
            self.btn_pause.emoji = "⏸️"
        self.btn_pause.style = discord.ButtonStyle.secondary

        # 4. Nút Skip
        self.btn_skip.label = tr(self.settings, "music.btn_skip")
        self.btn_skip.emoji = "⏭️"
        self.btn_skip.style = discord.ButtonStyle.secondary

        # 5. Nút Loop (Lặp lại - thay cho Yêu thích)
        if player.loop_mode == 0:
            self.btn_loop.label = "Lặp lại"
            self.btn_loop.emoji = "🔁"
            self.btn_loop.style = discord.ButtonStyle.secondary
        elif player.loop_mode == 1:
            self.btn_loop.label = "Lặp 1 bài"
            self.btn_loop.emoji = "🔂"
            self.btn_loop.style = discord.ButtonStyle.primary
        else:
            self.btn_loop.label = "Lặp toàn bộ"
            self.btn_loop.emoji = "🔁"
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
        await self.player.stop()

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️", row=0)
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
            button.emoji = "⏸️"
        else:
            self.player.vc.pause()
            self.player.pause_start = time.time()
            button.label = tr(self.settings, "music.btn_resume")
            button.emoji = "▶️"
        button.style = discord.ButtonStyle.secondary
        elapsed = self.player.get_elapsed()
        embed = _make_np_embed(self.player.current, self.player.queue, self.player.loop_mode, self.player.volume, elapsed, self.settings)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.skip()

    @discord.ui.button(label="Lặp lại", style=discord.ButtonStyle.secondary, emoji="🔁", row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.loop_mode = (self.player.loop_mode + 1) % 3
        if self.player.loop_mode == 0:
            button.label = "Lặp lại"
            button.emoji = "🔁"
            button.style = discord.ButtonStyle.secondary
        elif self.player.loop_mode == 1:
            button.label = "Lặp 1 bài"
            button.emoji = "🔂"
            button.style = discord.ButtonStyle.primary
        else:
            button.label = "Lặp toàn bộ"
            button.emoji = "🔁"
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


# ─── Cog ───────────────────────────────────────────────────────────────────────
class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self._players: dict[int, MusicPlayer] = {}
        self._bg_tasks: set[asyncio.Task] = set()

    def cog_unload(self):
        """Cancel tất cả background tasks khi cog bị unload."""
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()

    # ── Helpers ────────────────────────────────────────────────────────────
    def _get(self, guild_id: int) -> MusicPlayer | None:
        return self._players.get(guild_id)

    def _drop(self, guild_id: int):
        self._players.pop(guild_id, None)

    async def _ensure(self, ctx: commands.Context) -> MusicPlayer | None:
        s = await async_get_guild_settings(str(ctx.guild.id))
        if not ctx.author.voice:
            await ctx.send(tr(s, "music.join_voice_first"))
            return None

        guild_id = ctx.guild.id
        player   = self._players.get(guild_id)

        if player and player.vc.is_connected():
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
            await ctx.send(tr(s, "music.cannot_connect", err=e))
            return None

        player = MusicPlayer(ctx.guild, ctx.channel, vc)
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
        """Tự rời kênh sau 30s nếu không còn thành viên thực nào trong kênh voice."""
        if member.bot:
            return
        player = self._players.get(member.guild.id)
        if not player or not player.vc.is_connected():
            return
        channel = player.vc.channel
        if any(not m.bot for m in channel.members):
            return
            
        await asyncio.sleep(30)
        
        # Kiểm tra lại sau 30s
        current_player = self._players.get(member.guild.id)
        if current_player is not player:
            return
            
        if any(not m.bot for m in player.vc.channel.members):
            return
            
        if player.text_channel:
            try:
                s = await async_get_guild_settings(str(member.guild.id))
                await player.text_channel.send(tr(s, "music.empty_voice_left"))
            except Exception:
                pass
        await player.stop()
        self._drop(member.guild.id)

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
        if player:
            await player.stop()
            self._drop(ctx.guild.id)
            await ctx.send(tr(s, "music.left_voice"))
        else:
            await ctx.send(tr(s, "music.not_in_voice"))

    @commands.hybrid_command(name="play", description="Phát nhạc từ YouTube hoặc Spotify (tên bài hoặc link)")
    @app_commands.describe(query="Tên bài hát, link YouTube hoặc link Spotify")
    async def play(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = await self._ensure(ctx)
        if not player:
            return

        # Tự động phân giải link Spotify nếu có
        resolved_query = await _resolve_external_url(query)
        msg = await ctx.send(tr(s, "music.searching", query=query))
        info = await extract_info(resolved_query)
        if not info:
            await msg.edit(content=tr(s, "music.not_found", query=query))
            return

        track = Track(info, requester=ctx.author)

        if player.vc.is_playing() or player.vc.is_paused() or player.current:
            player.queue.append(track)
            embed = discord.Embed(
                title=tr(s, "music.added_to_queue"),
                description=f"**[{track.title}]({track.url})**",
                color=0x3B82F6,
            )
            embed.add_field(name=tr(s, "music.duration_field"),   value=f"`{track.duration_str}`", inline=True)
            embed.add_field(name=tr(s, "music.position_field"),   value=f"`#{len(player.queue)}`", inline=True)
            embed.add_field(name=tr(s, "music.requester_field"),  value=ctx.author.mention,         inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await msg.edit(content=None, embed=embed)
        else:
            await msg.delete()
            await player.add_and_play(track)

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
        if not player:
            await ctx.send(tr(s, "music.not_playing"))
            return
        await player.stop()
        self._drop(ctx.guild.id)
        await ctx.send(tr(s, "music.stopped_left"))

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
        await ctx.send(tr(s, "music.paused"), ephemeral=True)

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc")
    async def resume(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.vc.is_paused():
            await ctx.send(tr(s, "music.not_paused"))
            return
        player.vc.resume()
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
        status_text = "BẬT ♾️ (Sẽ tự động tìm bài tương tự khi hết hàng chờ)" if player.autoplay else "TẮT"
        await ctx.send(f"♾️ Đã **{status_text}** chế độ Autoplay!", ephemeral=True)

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
        embed = discord.Embed(title=tr(s, "music.queue_title"), description=desc, color=0x5865F2)
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

    @commands.hybrid_command(name="lofi", description="Phát nhạc Lofi 24/7 (mặc định SomaFM, ổn định)")
    @app_commands.describe(source="Nguồn lofi (mặc định: soma — ổn định, không bị chặn)")
    @app_commands.autocomplete(source=lofi_autocomplete)
    async def lofi(self, ctx: commands.Context, source: str = None):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        src_key = source if source else "soma"
        if src_key not in LOFI_STREAMS:
            await ctx.send(tr(s, "music.invalid_source"))
            return
        stream = LOFI_STREAMS.get(src_key, LOFI_STREAMS["soma"])

        player = await self._ensure(ctx)
        if not player:
            return

        if src_key == "soma":
            track = Track(
                {"title": stream["title"], "url": stream["url"], "webpage_url": stream["url"], "duration": -1},
                requester=ctx.author,
            )
            track.stream_url = stream["url"]
            track.stream_expire = float("inf")  # stream sống mãi, không expire
            await player.add_and_play(track)
            await ctx.send(tr(s, "music.lofi_soma_success", name=stream['name']))
        else:
            info = await extract_info(stream["url"])
            if not info:
                await ctx.send(tr(s, "music.lofi_yt_err"))
                return
            track = Track(info, requester=ctx.author)
            await player.add_and_play(track)
            await ctx.send(tr(s, "music.lofi_yt_success", name=stream['name']))

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
        """Nạp ngầm các bài còn lại từ playlist vào hàng chờ (giới hạn MAX_BG_LOAD bài)."""
        for t in tracks[:MAX_BG_LOAD]:
            query = t.get("webpage_url") or t.get("title", "")
            try:
                info = await extract_info(query)
                if info:
                    track = Track(info, requester=requester)
                    if not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
                        await player.add_and_play(track)
                    else:
                        player.queue.append(track)
            except Exception as e:
                log.warning(f"[Music] Background load track error: {e}")
            await asyncio.sleep(0.2)
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
        
        # 1. Phát bài đầu tiên ngay lập tức (không chờ cả playlist)
        first_track_data = tracks[0]
        first_query = first_track_data.get("webpage_url") or first_track_data.get("title", "")
        first_info = await extract_info(first_query)
        
        if first_info:
            first_track = Track(first_info, requester=ctx.author)
            if not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
                await player.add_and_play(first_track)
            else:
                player.queue.append(first_track)
            if len(tracks) > 1:
                await msg.edit(content=tr(s, "music.pl_loading_bg", cnt=len(tracks) - 1, name=name))
            else:
                await msg.edit(content=tr(s, "music.pl_loaded", cnt=len(tracks), name=name))
        else:
            await msg.edit(content=tr(s, "music.pl_fail_first", name=name))

        # 2. Nạp ngầm các bài còn lại ở background task
        if len(tracks) > 1:
            task = asyncio.create_task(self._load_playlist_background(player, tracks[1:], ctx.author))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

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


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

"""
extractor.py — Trích xuất thông tin & URL stream qua yt-dlp (thread pool).

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Toàn bộ hàm ở đây thuần logic /
async và KHÔNG chạm voice client — nhờ vậy có thể test hoàn toàn offline.
"""

import asyncio
import logging
import re
import time

import aiohttp

from cache import cache

from database import (
    async_delete_song_cache,
    async_get_song_cache,
    async_set_song_cache,
)

from .config import _extract_semaphore, _get_ydl, _get_ydl_flat

log = logging.getLogger("BotV2.Music")


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

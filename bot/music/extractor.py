"""
extractor.py — Trích xuất thông tin & URL stream qua yt-dlp (thread pool).

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Toàn bộ hàm ở đây thuần logic /
async và KHÔNG chạm voice client — nhờ vậy có thể test hoàn toàn offline.
"""

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import aiohttp

from cache import cache

from database import (
    async_delete_song_cache,
    async_get_song_cache,
    async_set_song_cache,
)

from database.music import async_set_song_cache_batch

from .config import (
    _extraction_runtime,
    _extract_semaphore,
    _get_ydl,
    _get_ydl_flat,
    _get_ydl_primary,
    get_source_mode,
    primary_ready,
    source_cache_tag,
)

log = logging.getLogger("BotV2.Music")

_NO_CODEC = (None, "", "none", "null")
_PRIMARY_FAIL_THRESHOLD = 3
_PRIMARY_COOLDOWN_SECONDS = 600
_primary_fail_streak = 0
_primary_disabled_until = 0.0
_health_lock = threading.Lock()


def _reset_primary_health() -> None:
    global _primary_fail_streak, _primary_disabled_until
    with _health_lock:
        _primary_fail_streak = 0
        _primary_disabled_until = 0.0


def _primary_available() -> bool:
    with _health_lock:
        return time.monotonic() >= _primary_disabled_until


def _note_primary_result(ok: bool) -> None:
    global _primary_fail_streak, _primary_disabled_until
    with _health_lock:
        if ok:
            _primary_fail_streak = 0
            _primary_disabled_until = 0.0
            return
        _primary_fail_streak += 1
        if _primary_fail_streak >= _PRIMARY_FAIL_THRESHOLD:
            _primary_fail_streak = 0
            _primary_disabled_until = time.monotonic() + _PRIMARY_COOLDOWN_SECONDS
            log.warning(
                "[Music] Primary source lỗi %d lần liên tiếp; dùng compat/android trong %ds",
                _PRIMARY_FAIL_THRESHOLD, _PRIMARY_COOLDOWN_SECONDS,
            )


def _first_entry(info: dict | None) -> dict | None:
    if not info:
        return None
    if "entries" in info:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        return entries[0] if entries else None
    return info


def _is_audio_only_format(fmt: dict | None) -> bool:
    if not fmt:
        return False
    return (fmt.get("vcodec") in _NO_CODEC) and (fmt.get("acodec") not in _NO_CODEC)


def _selected_format(info: dict | None) -> dict | None:
    info = _first_entry(info)
    if not info:
        return None
    stream = _get_stream_url(info)
    if stream:
        for fmt in info.get("formats") or []:
            if fmt.get("url") == stream:
                return fmt
    return info


def _selected_is_audio_only(info: dict | None) -> bool:
    return _is_audio_only_format(_selected_format(info))


def _selected_is_opus(info: dict | None) -> bool:
    fmt = _selected_format(info)
    return _is_audio_only_format(fmt) and (fmt.get("acodec") or "").lower() in ("opus", "libopus")


def _should_try_primary(mode: str) -> bool:
    if mode == "compat":
        return False
    if mode == "opus":
        return True
    return primary_ready()


def _extract_with_fallback(query: str, mode: str) -> tuple[dict | None, str]:
    """Chạy trong thread pool: primary trước, compat sau (trừ mode opus/compat)."""
    if mode == "compat":
        return _extract_sync(query, "compat"), "compat"

    info = _extract_sync(query, "primary")
    ok = _selected_is_opus(info) if mode == "opus" else _selected_is_audio_only(info)
    if ok:
        return info, "primary"

    if mode == "opus":
        log.warning("[Music] Primary không có Opus audio-only")
        return None, "primary"

    return _extract_sync(query, "compat"), "compat"


def _normalized_query(query: str) -> str:
    query = clean_youtube_query(query or "")
    if _is_url(query):
        try:
            parts = urlsplit(query)
        except ValueError:
            return query  # The worker's SSRF guard still rejects malformed URLs.
        # Host/scheme are insensitive; userinfo, port, path, query and IDs are not.
        userinfo, separator, hostport = parts.netloc.rpartition("@")
        authority = userinfo + separator + hostport.lower()
        return parts._replace(scheme=parts.scheme.lower(), netloc=authority).geturl()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", query):
        return query
    return query.lower()


def _is_url(query: str) -> bool:
    return query.lower().startswith(("http://", "https://"))


def _song_info_cache_key(query: str, tag: str | None = None) -> str:
    return f"song_info:{tag or source_cache_tag()}:{_normalized_query(query)}"


_EXTRACT_REQUEST_TIMEOUT = 30.0
_EXTRACT_CLOSE_TIMEOUT = 5.0
_MAX_INFLIGHT = 128
_inflight = _extraction_runtime.inflight


def _activate_extraction_generation() -> bool:
    """The first replacement request invalidates any old drain's cleanup authority."""
    runtime = _extraction_runtime
    with runtime.lock:
        if runtime.closing:
            return False
        if runtime.close_generation == runtime.generation:
            runtime.generation += 1
        return True


async def _run_worker(func, *args, recheck=None):
    """One reload-stable pool/permit set, including all lingering generations."""
    runtime = _extraction_runtime
    if runtime.closing:
        return None
    generation = runtime.generation
    capacity = _extract_semaphore
    start = time.monotonic()
    await capacity.acquire()
    submitted = False
    try:
        log.debug("[Music][extract] worker_wait_ms=%.1f", (time.monotonic() - start) * 1000)
        if runtime.closing or runtime.generation != generation:
            return None
        if recheck is not None:
            hit = await recheck()
            if hit is not None:
                return hit
        while True:
            with runtime.lock:
                if runtime.closing or runtime.generation != generation:
                    return None
                retiring = runtime.retiring
                if retiring is not None and retiring[1].is_set():
                    runtime.retiring = retiring = None
                if retiring is None:
                    if runtime.executor is None:
                        runtime.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="music-extract")
                    future = runtime.executor.submit(func, *args)
                    runtime.workers.add(future)
                    break
            # A completely idle retired pool is joining outside both executors.
            # Do not create a second pool until its actual worker threads have exited.
            await asyncio.sleep(0.01)
        def finished(done):
            with runtime.lock:
                runtime.workers.discard(done)
            capacity.release()
        future.add_done_callback(finished)
        submitted = True
        # Shield the actual future: cancellation/deadline cannot release true capacity.
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        return await asyncio.shield(wrapped)
    finally:
        if not submitted:
            capacity.release()


async def _singleflight(key, operation):
    runtime = _extraction_runtime
    if not _activate_extraction_generation():
        return None
    # Different event loops must not await one another's tasks (offline tests/reloads).
    flight_key = (asyncio.get_running_loop(), key)
    task = _inflight.get(flight_key)
    if task is None:
        if len(_inflight) >= _MAX_INFLIGHT:
            log.debug("[Music][extract] admission=busy")
            return None
        async def bounded():
            start = time.monotonic()
            try:
                return await asyncio.wait_for(operation(), timeout=_EXTRACT_REQUEST_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("[Music][extract] deadline exceeded")
                return None
            except Exception as exc:
                # Never log provider exceptions: they may contain signed URLs/cookies.
                log.debug("[Music][extract] failed type=%s", type(exc).__name__)
                return None
            finally:
                log.debug("[Music][extract] latency_ms=%.1f", (time.monotonic() - start) * 1000)
        task = asyncio.create_task(bounded(), name="music-extraction")
        _inflight[flight_key] = task
        def forget(done):
            if _inflight.get(flight_key) is done:
                _inflight.pop(flight_key, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(forget)
    else:
        log.debug("[Music][extract] singleflight=joined")
    return await asyncio.shield(task)


async def _retire_idle_executor(runtime, executor, generation):
    """Only the still-current unload may retire an idle pool, never a replacement."""
    with runtime.lock:
        if (executor is None or runtime.executor is not executor
                or runtime.generation != generation or runtime.workers):
            return
        done = threading.Event()
        retiring = (executor, done)
        runtime.retiring = retiring
        runtime.executor = None
    def join_pool():
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        finally:
            done.set()
    # No join on the event loop or the extraction/default executor; all real work
    # is already finished. New submissions wait for this pool's threads to exit.
    threading.Thread(target=join_pool, name="music-pool-close", daemon=True).start()
    while not done.is_set():
        await asyncio.sleep(0.01)
    with runtime.lock:
        if runtime.retiring is retiring:
            runtime.retiring = None


async def _close_extractor_generation():
    runtime = _extraction_runtime
    global _spotify_session
    # Detach everything before the first await. Later cleanup only owns these
    # snapshots; replacement requests may create their own tasks/session immediately.
    with runtime.lock:
        runtime.generation += 1
        generation = runtime.close_generation = runtime.generation
        executor = runtime.executor
        workers = list(runtime.workers)
        tasks = list(_inflight.values()) + list(runtime.jobs)
        _inflight.clear()
        runtime.jobs.clear()
        sessions = [s for s in (_spotify_session, runtime.spotify_session) if s is not None]
        _spotify_session = runtime.spotify_session = None
        for task in tasks:
            task.cancel()
        runtime.closing = False
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for session in {id(s): s for s in sessions}.values():
        try:
            if not session.closed:
                await asyncio.wait_for(session.close(), timeout=_EXTRACT_CLOSE_TIMEOUT)
        except Exception as exc:
            log.debug("[Music][extract] session close failed type=%s", type(exc).__name__)
    if workers:
        wrapped = [asyncio.wrap_future(worker) for worker in workers]
        for future in wrapped:
            future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        # Finite snapshot wait, not a background drain retained forever by a hung job.
        await asyncio.wait(wrapped, timeout=_EXTRACT_CLOSE_TIMEOUT)
    await _retire_idle_executor(runtime, executor, generation)


async def close_extractor_resources() -> None:
    """Detach one generation; lingering work keeps its permits, not an admission veto.

    Replacement generations reuse the same four-worker pool while old native work
    runs. An idle pool is joined off-loop before any replacement pool can be created.
    """
    runtime = _extraction_runtime
    task = runtime.close_task
    if (task is None or task.done()
            or (not runtime.closing and runtime.close_generation != runtime.generation)):
        runtime.closing = True
        task = runtime.close_task = asyncio.create_task(_close_extractor_generation())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_EXTRACT_CLOSE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("[Music][extract] shutdown pending; replacement admission remains available")


async def run_extraction_job(func, *args):
    """Run a synchronous callable on the shared pool; do NOT wrap in the semaphore.

    Cancellation propagates to the caller, but real capacity is held until thread exit.
    Queue/worker time counts toward the deadline; timeout/provider errors return None.
    """
    runtime = _extraction_runtime
    if not _activate_extraction_generation():
        return None
    job = asyncio.create_task(_run_worker(func, *args), name="music-worker-job")
    runtime.jobs.add(job)
    start = time.monotonic()
    try:
        return await asyncio.wait_for(job, timeout=_EXTRACT_REQUEST_TIMEOUT)
    except asyncio.TimeoutError:
        log.debug("[Music][extract] job deadline exceeded")
        return None
    except Exception as exc:
        log.debug("[Music][extract] job failed type=%s", type(exc).__name__)
        return None
    finally:
        runtime.jobs.discard(job)
        log.debug("[Music][extract] job_latency_ms=%.1f", (time.monotonic() - start) * 1000)


async def find_related_track(current_title: str, current_uploader: str, history=None, current_id: str = "") -> dict | None:
    """Autoplay convenience wrapper around the generic bounded worker entry point."""
    return await run_extraction_job(
        _find_related_track_sync, current_title, current_uploader, history, current_id,
    )


def _log_source(query: str, info: dict | None, used_mode: str) -> None:
    fmt = _selected_format(info) or {}
    log.info(
        "[Music] source=%s format=%s acodec=%s vcodec=%s abr=%s protocol=%s audio_only=%s",
        used_mode, fmt.get("format_id"), fmt.get("acodec"), fmt.get("vcodec"),
        fmt.get("abr"), fmt.get("protocol"), _selected_is_audio_only(info),
    )


_EXPIRE_PATH_RE = re.compile(r"/expire/(\d{9,12})")


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
    if not _activate_extraction_generation():
        raise RuntimeError("Extractor resources are closing")
    if _spotify_session is None:
        _spotify_session = _extraction_runtime.spotify_session
    if _spotify_session is None or _spotify_session.closed:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        _spotify_session = aiohttp.ClientSession(headers=headers)
    _extraction_runtime.spotify_session = _spotify_session
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
                        log.info("[Music] Resolved Spotify track metadata")
                        return title
        except Exception as e:
            log.debug("[Music] Spotify resolve error type=%s", type(e).__name__)
    return query

def clean_youtube_query(query: str) -> str:
    """Chuẩn hóa URL YouTube, loại bỏ các tham số rác (&list=, ?si=, &ab_channel=) để tránh bị nhận diện nhầm thành playlist tab."""
    q = query.strip()
    match = re.search(r"(?:v=|\/|vi=)([0-9A-Za-z_-]{11})(?:[&?]|$|\/)", q)
    try:
        host = (urlsplit(q).hostname or "").lower()
    except ValueError:
        host = ""
    if match and (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
        video_id = match.group(1)
        return f"https://www.youtube.com/watch?v={video_id}"
    return q

def _is_safe_remote_url(url: str) -> bool:
    """Chặn SSRF trước khi đưa URL vào yt-dlp. Fail-closed nếu không import được."""
    try:
        from dashboard.auth import is_safe_http_url
        return bool(is_safe_http_url(url))
    except Exception:
        return False


def _extract_sync(query: str, mode: str = "compat") -> dict | None:
    """Đồng bộ yt-dlp (chạy trong thread pool qua singleton session).

    `mode="compat"` giữ client android cũ; `mode="primary"` dùng default client
    pool (cần cookie/PO token để có audio-only Opus).
    """
    try:
        clean_q = clean_youtube_query(query)
        if _is_url(clean_q) and not _is_safe_remote_url(clean_q):
            log.warning("[Music] Chặn URL không an toàn")
            return None
        if not _is_url(clean_q) and not clean_q.startswith("ytsearch:"):
            clean_q = f"ytsearch1:{clean_q}"
        elif clean_q.startswith("ytsearch:") and not clean_q.startswith("ytsearch1:"):
            clean_q = clean_q.replace("ytsearch:", "ytsearch1:", 1)

        ydl = _get_ydl_primary() if mode == "primary" else _get_ydl()
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
        log.warning("[Music] yt-dlp error type=%s", type(e).__name__)
        return None

def _extract_metadata_sync(query: str) -> dict | None:
    """Trích xuất nhanh metadata bài hát qua Flat Extraction (< 1s)."""
    try:
        clean_q = clean_youtube_query(query)
        if _is_url(clean_q) and not _is_safe_remote_url(clean_q):
            log.warning("[Music] Chặn URL không an toàn (metadata)")
            return None
        if not _is_url(clean_q) and not clean_q.startswith("ytsearch:"):
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
        log.warning("[Music] yt-dlp flat metadata error type=%s", type(e).__name__)
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
        log.warning("[Music] Autoplay search failed type=%s", type(e).__name__)
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

    # 1. Tối ưu nhất: Opus audio-only qua progressive HTTP (không phải HLS).
    # Chọn abr CAO NHẤT, không lấy format đầu tiên: yt-dlp có thể chọn 251
    # (128.93 kbps) trong khi list formats xếp 249 (46 kbps) trước.
    opus_progressive = [
        f for f in valid_formats
        if (f.get("acodec") or "").lower() == "opus"
        and (f.get("vcodec") or "").lower() in ("none", "", "null")
        and not _is_hls(f)
    ]
    if opus_progressive:
        return max(opus_progressive, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))["url"]

    # 2. Ưu tiên cao: Audio-only bất kỳ (mp3, m4a, aac) qua progressive HTTP (chống HLS m3u8 làm méo nhịp / lúc nhanh lúc chậm)
    audio_progressive = [
        f for f in valid_formats
        if (f.get("vcodec") or "").lower() in ("none", "", "null")
        and not _is_hls(f)
    ]
    if audio_progressive:
        return max(audio_progressive, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))["url"]

    # 3. Fallback: Opus audio-only (kể cả HLS m3u8)
    opus_any = [
        f for f in valid_formats
        if (f.get("acodec") or "").lower() == "opus"
        and (f.get("vcodec") or "").lower() in ("none", "", "null")
    ]
    if opus_any:
        return max(opus_any, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))["url"]

    # 4. Fallback: Audio-only bất kỳ (kể cả HLS m3u8)
    audio_any = [
        f for f in valid_formats
        if (f.get("vcodec") or "").lower() in ("none", "", "null")
    ]
    if audio_any:
        return max(audio_any, key=lambda x: (x.get("abr") or 0, x.get("tbr") or 0))["url"]

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
    """Trích xuất expire timestamp thật từ format/info yt-dlp hoặc query parameter / path của stream URL."""
    now = time.time()
    if not stream_url:
        return 0.0

    def _val(cand) -> float | None:
        if cand is None:
            return None
        try:
            f = float(cand)
            if now < f <= (now + 86400 * 7):
                return f
            elif f <= now:
                return f
            elif f > (now + 86400 * 7):
                return now + (5.5 * 3600)
        except (ValueError, TypeError):
            pass
        return None

    # 1. Trực tiếp từ trường info
    for k in ("stream_expire", "expire"):
        v = _val(info.get(k))
        if v is not None:
            return v

    # 2. Kiểm tra formats array
    for fmt in info.get("formats") or []:
        if fmt.get("url") == stream_url:
            v = _val(fmt.get("expire"))
            if v is not None:
                return v

    # 3. urllib.parse query parameter (?expire=...) & path (/expire/...)
    try:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(stream_url)
        qs = parse_qs(parsed.query)
        if "expire" in qs and qs["expire"]:
            v = _val(qs["expire"][0])
            if v is not None:
                return v

        m = _EXPIRE_PATH_RE.search(parsed.path)
        if m:
            v = _val(m.group(1))
            if v is not None:
                return v
    except Exception:
        pass

    # Fallback: 5.5 giờ nếu có stream_url
    return now + (5.5 * 3600)

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

def _stream_cache_ttl(info) -> float:
    if not isinstance(info, dict) or info.get("is_live"):
        return 0.0
    try:
        expire = info.get("stream_expire")
        return max(0.0, min(600.0, float(expire) - time.time() - 30)) if expire else 600.0
    except (ValueError, TypeError, OverflowError):
        return 0.0


async def _cached_song(cache_key):
    cached = await cache.aget(cache_key)
    if cached is not None:
        if _stream_cache_ttl(cached) > 0:
            log.debug("[Music][extract] cache_hit=ram")
            return cached
        await cache.adelete(cache_key)
    disk = await async_get_song_cache(cache_key, ttl=21600)
    ttl = _stream_cache_ttl(disk)
    if ttl > 0:
        await cache.aset(cache_key, disk, ttl=ttl)
        log.debug("[Music][extract] cache_hit=disk")
        return disk
    return None


def _extract_policy_sync(query, mode):
    if not _should_try_primary(mode):
        return _extract_sync(query, "compat"), "compat"
    if not _primary_available():
        if mode == "opus":
            return None, "primary"
        return _extract_sync(query, "compat"), "compat"
    info, used_mode = _extract_with_fallback(query, mode)
    _note_primary_result(used_mode == "primary")
    return info, used_mode


async def extract_info(query: str, force_refresh: bool = False) -> dict | None:
    """Stream extraction with bounded DNS/workers, deadline and cancellation-safe sharing."""
    query = (query or "").strip()
    tag = source_cache_tag()
    cache_key = _song_info_cache_key(query, tag)
    mode = get_source_mode()

    async def extract():
        # DNS is deliberately before even a RAM hit and uses the same bounded pool.
        if _is_url(query) and not await _run_worker(_is_safe_remote_url, query):
            log.warning("[Music][extract] blocked unsafe URL")
            return None
        if force_refresh:
            await cache.adelete(cache_key)
            await async_delete_song_cache(cache_key)
        else:
            hit = await _cached_song(cache_key)
            if hit is not None:
                return hit
        # Another alias may have populated cache while this request waited for capacity.
        async def recheck():
            hit = await _cached_song(cache_key)
            return (hit, "cache") if hit is not None else None
        result = await _run_worker(
            _extract_policy_sync, query, mode, recheck=None if force_refresh else recheck,
        )
        if result is None:
            return None
        info, used_mode = result
        if used_mode == "cache":
            return info
        if not info:
            return None
        _log_source(query, info, used_mode)
        compact = _compact_song_info(info)
        ttl = _stream_cache_ttl(compact)
        if ttl > 0:
            keys = [cache_key]
            if compact.get("id"):
                keys.append(_song_info_cache_key(compact["id"], tag))
            web = compact.get("webpage_url") or compact.get("url")
            if isinstance(web, str) and _is_url(web):
                keys.append(_song_info_cache_key(web, tag))
            keys = list(dict.fromkeys(keys))
            for key in keys:
                await cache.aset(key, compact, ttl=ttl)
            await async_set_song_cache_batch(keys, compact, compact.get("stream_expire"))
        return compact

    # Force requests coalesce with one another, but must not join an ordinary cache hit.
    return await _singleflight(("stream", cache_key, bool(force_refresh)), extract)

def _compact_metadata(info: dict) -> dict:
    """Bản gọn cho RAM cache 24h của `extract_metadata` (flat extraction).

    `cache.py` là LRU tối đa 10000 key nhưng TTL 24h nghĩa là gần như không có gì bị
    đẩy ra trong một phiên chạy; dict thô của yt-dlp mang theo `thumbnails` (4-9 độ
    phân giải), `formats`/`description`/`heatmap`... nên toàn bộ hàng đợi metadata nằm
    lại trong RAM trên thiết bị 6GB. Chỉ giữ đúng các trường `playlist add` cần.
    """
    if not info:
        return {}
    vid = info.get("id") or ""
    web = info.get("webpage_url") or info.get("url") or ""
    if not web and vid:
        web = f"https://www.youtube.com/watch?v={vid}"
    return {
        "id":           vid,
        "title":        info.get("title") or info.get("fulltitle") or "Unknown",
        "webpage_url":  web,
        "url":          info.get("url") or "",
        "duration":     info.get("duration"),
        "uploader":     info.get("uploader") or info.get("channel") or "—",
        "thumbnail":    _get_best_thumbnail(info),
        "is_live":      bool(info.get("is_live") or info.get("live_status") == "is_live"),
    }


async def extract_metadata(query: str) -> dict | None:
    """Flat metadata with bounded workers and source-tagged single-flight."""
    query = (query or "").strip()
    # Flat extraction is always cookie-free compat; preserve its public RAM namespace.
    tag = source_cache_tag()
    cache_key = f"song_meta:{_normalized_query(query)}"

    async def extract():
        if _is_url(query) and not await _run_worker(_is_safe_remote_url, query):
            return None
        async def recheck():
            hit = await cache.aget(cache_key)
            if hit is not None:
                log.debug("[Music][extract] cache_hit=metadata")
            return hit
        cached = await recheck()
        if cached is not None:
            return cached
        info = await _run_worker(_extract_metadata_sync, query, recheck=recheck)
        if not info:
            return None
        compact = _compact_metadata(info)
        await cache.aset(cache_key, compact, ttl=86400)
        return compact

    return await _singleflight(("metadata", tag, cache_key), extract)

"""
player.py — `Track` và `MusicPlayer`: vòng đời phát nhạc của MỘT guild.

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Đây là phần "nóng" nhất của cog
nhạc: auto-recovery 403, preload, inactivity auto-leave, autoplay, resume sau
khi voice reconnect. Code được DI CHUYỂN NGUYÊN VẸN, không sửa logic.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

import discord

from cache import cache
from database import async_get_guild_settings, async_increment_stat
from i18n import tr

try:
    from emojis import e, embed_title, partial
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, partial

from .config import (
    FFMPEG_BEFORE,
    FFMPEG_OPTS_COPY,
    FFMPEG_OPTS_ENCODE,
    MAX_PLAYERS,
    _lower_process_priority,
    load_opus_library,
)
from .embeds import _format_queue_duration, _make_np_embed
from .extractor import (
    _compact_song_info,
    _extract_stream_expire,
    _find_related_track_sync,
    _fmt_duration,
    _get_best_thumbnail,
    _get_stream_acodec,
    _get_stream_url,
    clean_youtube_query,
    extract_info,
)
from .views import MusicControlView

log = logging.getLogger("BotV2.Music")


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
        self._is_reconnecting : bool = False

    def set_reconnecting(self, status: bool):
        """Cập nhật trạng thái reconnecting an toàn và xóa cờ recovery nếu tắt."""
        self._is_reconnecting = bool(status)
        if not status:
            self._recovering = False

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
        if self._manual_stopped or self._recovering or self._is_reconnecting:
            log.debug(f"[Music] _after_play ignored (stopped={self._manual_stopped}, recovering={self._recovering}, reconnecting={self._is_reconnecting})")
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
        if self._manual_stopped or self._skipped or self._is_reconnecting or self._recovering:
            return

        is_live_track = getattr(track, "is_live", False)
        now = time.time()

        # 1. LIVE STREAM AUTO-RECOVERY (Lofi Girl 24/7, Radio, YouTube Live)
        if is_live_track and not self._skipped:
            # Reset recovery counter chỉ khi đã phát ổn định >= 180s (3 phút)
            if elapsed >= 180 or (self._last_recovery_time > 0 and (now - self._last_recovery_time) >= 180):
                track.recovery_attempts = 0

            if getattr(track, "recovery_attempts", 0) < 3:
                track.recovery_attempts = getattr(track, "recovery_attempts", 0) + 1
                self._last_recovery_time = now
                log.warning(
                    f"[Music] Live stream 24/7 '{track.title}' ngắt kết nối tại {elapsed}s (lần {track.recovery_attempts}/3). "
                    f"Đang tự động làm mới stream URL và tiếp tục phát sau 2s..."
                )
                self._recovering = True
                try:
                    await asyncio.sleep(2)
                    if self._skipped or self._manual_stopped or self._is_reconnecting:
                        return
                    track.stream_url = None
                    await self._play(track, seek_offset=0)
                except Exception as rec_err:
                    log.error(f"[Music] Lỗi khôi phục live stream '{track.title}': {rec_err}")
                    await self._on_queue_empty()
                finally:
                    self._recovering = False
                return
            else:
                log.error(f"[Music] Live stream '{track.title}' lỗi liên tục 3 lần, dừng stream.")
                try:
                    if self.text_channel:
                        await self.text_channel.send(
                            embed=discord.Embed(
                                description=f"⚠️ Live stream **{track.title}** bị gián đoạn và không thể kết nối lại sau 3 lần thử.",
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
        # Reset recovery counter nếu sự cố trước đó đã diễn ra cách đây hơn 2 phút (120s)
        if self._last_recovery_time > 0 and (now - self._last_recovery_time) >= 120:
            track.recovery_attempts = 0

        if (error or is_premature) and getattr(track, "recovery_attempts", 0) < 2 and not self._skipped:
            track.recovery_attempts = getattr(track, "recovery_attempts", 0) + 1
            self._last_recovery_time = now
            backoff_delay = 2
            log.warning(
                f"[Music] Bài hát '{track.title}' đứt kết nối tại {elapsed}s (lần {track.recovery_attempts}/2, error={error}, premature={is_premature}). "
                f"Tự động làm mới URL và phát tiếp sau {backoff_delay}s..."
            )
            self._recovering = True
            try:
                await asyncio.sleep(backoff_delay)
                if self._skipped or self._manual_stopped or self._is_reconnecting:
                    return
                if track.is_stream_expired or error:
                    track.stream_url = None
                await self._play(track, seek_offset=elapsed)
            except Exception as rec_err:
                log.error(f"[Music] Lỗi khôi phục bài hát '{track.title}': {rec_err}")
                await self._report_play_failure(track, "music.cannot_decode")
            finally:
                self._recovering = False
            return
        elif (error or is_premature) and getattr(track, "recovery_attempts", 0) >= 2 and not self._skipped:
            log.warning(f"[Music] Bài hát '{track.title}' vượt quá 2 lần khôi phục, bỏ qua và phát bài tiếp theo.")
            await self._report_play_failure(track, "music.cannot_decode")
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
            if self._manual_stopped or self._skipped:
                return

            if self.vc.is_playing() or self.vc.is_paused():
                self.vc.stop()

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
        self._is_reconnecting = False
        cog = getattr(self, "cog", None)
        if cog and hasattr(cog, "_cancel_reconnect_task"):
            try:
                cog._cancel_reconnect_task(self.guild.id)
            except Exception:
                pass
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
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

    async def resume_after_reconnect(self):
        """Phục hồi phát nhạc an toàn sau khi bot reconnect lại voice channel."""
        if self._recovering or self._manual_stopped or self._skipped or not self._is_reconnecting:
            return

        self._recovering = True
        try:
            # Đệm 1s để Discord Voice UDP socket ổn định
            await asyncio.sleep(1)
            if self._manual_stopped or self._skipped or not self._is_reconnecting:
                return

            target_track = self.current
            if not target_track:
                return

            # Cập nhật self.vc từ guild nếu instance cũ bị stale
            g_vc = self.guild.voice_client
            if g_vc and g_vc.is_connected():
                self.vc = g_vc

            if not self.vc or not self.vc.is_connected():
                log.warning(f"[Music] Không thể resume: vc chưa kết nối tại guild {self.guild.id}")
                return

            if self.vc.is_playing():
                log.info(f"[Music] Stream vẫn đang chạy tại guild {self.guild.id}, không cần resume.")
                return

            target_elapsed = self.get_elapsed()
            track_title = getattr(target_track, "title", "Không rõ")
            log.info(f"[Music] Phục hồi bài hát '{track_title}' tại {target_elapsed}s sau khi voice reconnect...")

            # Kiểm tra URL còn hạn không trước khi stream
            if target_track.is_stream_expired:
                log.info(f"[Music] Stream URL cho '{track_title}' đã hết hạn, trích xuất URL mới...")
                target_track.stream_url = None

            if self._manual_stopped or self._skipped:
                return

            await self._play(target_track, seek_offset=target_elapsed)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            track = getattr(self, "current", None)
            track_title = getattr(track, "title", "Không rõ") if track else "Không rõ"
            log.error(f"[Music] Lỗi khi resume_after_reconnect cho '{track_title}': {e}")
            if track:
                await self._report_play_failure(track, "music.cannot_decode")
        finally:
            self._recovering = False
            self._is_reconnecting = False

    async def stop(self):
        self._manual_stopped = True
        self._is_reconnecting = False
        self._reset_inactivity_timer()
        cog = getattr(self, "cog", None)
        if cog and hasattr(cog, "_cancel_reconnect_task"):
            try:
                cog._cancel_reconnect_task(self.guild.id)
            except Exception:
                pass
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

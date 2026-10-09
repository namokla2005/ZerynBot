"""
music.py — Cog nhạc (facade mỏng).

Sau Giai đoạn 3.1, toàn bộ logic đã tách sang package `bot/music/`:
    config.py · extractor.py · embeds.py · views.py · player.py
File này giữ nguyên `class Music` (lệnh slash + task ngầm) và `setup()`.

LƯU Ý QUAN TRỌNG:
  - Loader cog chỉ quét `bot/cogs/*.py` nên file này PHẢI tồn tại.
  - KHÔNG tạo package `bot/cogs/music/` — loader sẽ bỏ qua thư mục đó.
  - Mọi tên công khai được re-export y nguyên để test/tool cũ vẫn chạy
    (`YDL_OPTS`, `FFMPEG_*`, `_get_stream_acodec`, `Track`, ...).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from cache import cache
from database import (
    async_delete_song_cache,
    async_get_guild_settings,
    async_get_song_cache,
    async_get_top_played_songs,
    async_increment_stat,
    async_set_song_cache,
)
from i18n import tr

from music.cog_voice import VoiceLifecycleMixin

try:
    from emojis import e, embed_title, partial
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, partial

# ─── Package nhạc ─────────────────────────────────────────────────────────────
# Mọi entrypoint (main.py, tests/conftest.py) đều đặt `bot/` trên sys.path nên
# tên chuẩn của package là `music`. Chỉ khi thiếu `bot/` mới dùng `bot.music`
# (lúc đó `bot` là namespace package).
# LƯU Ý: khi `bot/` nằm trên sys.path thì `import bot` trỏ tới bot/bot.py —
# KHÔNG phải package — nên `bot.music` sẽ fail; vì vậy thứ tự thử rất quan trọng.
# TUYỆT ĐỐI không import package bằng cả hai tên trong cùng tiến trình: sẽ tạo
# hai bản module riêng (2 semaphore, 2 YDL_OPTS, 2 class Track) gây lỗi ngầm.
try:
    import music as _music_pkg
except ImportError:  # pragma: no cover — chỉ khi thiếu bot/ trong sys.path
    import bot.music as _music_pkg

# Re-export toàn bộ tên công khai của package (deep-link cho code/test cũ).
# Danh sách này được tests/test_music_behavior.py kiểm tra nên không thể lệch.
_FACADE_EXPORTS = (
    "YDL_OPTS", "YDL_OPTS_FLAT", "_COOKIE_FILE",
    "FFMPEG_BEFORE", "FFMPEG_OPTS_COPY", "FFMPEG_OPTS_ENCODE",
    "MAX_PLAYERS", "MAX_BG_LOAD", "MAX_QUEUE_SIZE",
    "_extract_semaphore", "_thread_local", "_get_ydl",
    "_get_ydl_flat", "_lower_process_priority", "_fmt_duration",
    "_get_spotify_session", "_resolve_external_url", "clean_youtube_query",
    "_extract_sync", "_extract_metadata_sync", "_clean_song_title",
    "_is_duplicate_song", "_find_related_track_sync", "_get_stream_url",
    "_get_stream_acodec", "_get_best_thumbnail", "_extract_stream_expire",
    "_compact_song_info", "extract_info", "extract_metadata",
    "_make_progress_bar", "_format_queue_duration", "_make_np_embed",
    "MusicControlView", "RemoveSongSelect", "RemoveSongView",
    "_parse_time_str", "SearchSelect", "SearchSelectView",
    "_clean_track_title", "_fetch_lyrics_from_lrclib", "_chunk_lyrics",
    "LyricsPaginatorView", "Track", "MusicPlayer",
)

for _name in _FACADE_EXPORTS:
    globals()[_name] = getattr(_music_pkg, _name)
try:
    del _name
except NameError:  # pragma: no cover
    pass

log = logging.getLogger("BotV2.Music")

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

class Music(VoiceLifecycleMixin, commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self._players: dict[int, MusicPlayer] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._empty_voice_tasks: dict[int, asyncio.Task] = {}
        self._reconnect_tasks: dict[int, asyncio.Task] = {}
        self._grace_tasks: dict[int, asyncio.Task] = {}
        self.task_cleanup_loop.start()

    def cog_unload(self):
        """Cancel tất cả background tasks khi cog bị unload."""
        self.task_cleanup_loop.cancel()
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()
        for task in self._empty_voice_tasks.values():
            task.cancel()
        self._empty_voice_tasks.clear()
        for task in self._reconnect_tasks.values():
            task.cancel()
        self._reconnect_tasks.clear()
        for task in self._grace_tasks.values():
            task.cancel()
        self._grace_tasks.clear()
        # Session Spotify sống trong package bot/music/extractor.py → phải đọc
        # qua package (không re-export) để luôn lấy giá trị hiện thời, tránh giữ
        # bản sao cũ (None) và rò rỉ ClientSession.
        if _music_pkg._spotify_session and not _music_pkg._spotify_session.closed:
            asyncio.create_task(_music_pkg._spotify_session.close())

    @tasks.loop(seconds=60)
    async def task_cleanup_loop(self):
        """Định kỳ 60s dọn dẹp triệt để các background tasks đã hoàn thành khỏi dict, chống rò rỉ RAM trên Termux ARM64."""
        self._cleanup_stale_tasks()

    @task_cleanup_loop.before_loop
    async def before_task_cleanup(self):
        await self.bot.wait_until_ready()

    # ── Events ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_unavailable(self, guild: discord.Guild):
        """Dọn dẹp player tránh ghost connection khi server Discord gateway báo unavailable."""
        if guild:
            self._cancel_empty_voice_task(guild.id)
            self._cancel_grace_task(guild.id)
            self._cancel_reconnect_task(guild.id)
            self._drop(guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Xử lý sự kiện voice channel: dọn dẹp tức thì khi bot bị kick, và tự động rời phòng sau 3 phút nếu không còn ai."""
        guild = member.guild
        if not guild or getattr(guild, "unavailable", False) or not self.bot.get_guild(guild.id):
            return

        channel_changed = (before.channel != after.channel)
        deaf_changed = (before.self_deaf != after.self_deaf or before.deaf != after.deaf)
        mute_changed = (before.self_mute != after.self_mute or before.mute != after.mute)

        # Tối ưu CPU Helio G85: bỏ qua nếu không thay đổi channel và không thay đổi trạng thái deafen/mute
        if not channel_changed and not deaf_changed and not mute_changed:
            return

        self._cleanup_stale_tasks()
        guild_id = guild.id

        # 1. Xử lý khi chính bot bị thay đổi voice state
        if self.bot.user and member.id == self.bot.user.id:
            if before.channel and after.channel is None:
                # Bot tạm thời rời kênh voice (có thể do Discord voice WS 1006 reconnect hoặc bị kick)
                player = self._players.get(guild_id)
                if not player or player._manual_stopped:
                    return

                log.info(f"[Music] Bot tạm thời rời kênh voice tại guild {guild_id}. Khởi động Grace Period 6s chờ reconnect...")
                player.set_reconnecting(True)

                # Hủy task cũ nếu có
                self._cancel_grace_task(guild_id)
                self._cancel_reconnect_task(guild_id)
                self._cancel_empty_voice_task(guild_id)

                async def _safe_grace_wrapper():
                    try:
                        await asyncio.wait_for(
                            self._handle_voice_disconnect_grace(guild_id),
                            timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        log.warning(f"[Music] Grace task bị timeout 15s tại guild {guild_id}")
                        self._drop(guild_id)
                    except asyncio.CancelledError:
                        pass
                    except Exception as ge:
                        log.error(f"[Music] Lỗi trong grace task tại guild {guild_id}: {ge}")

                grace_task = asyncio.create_task(_safe_grace_wrapper())
                self._grace_tasks[guild_id] = grace_task
                grace_task.add_done_callback(lambda t, gid=guild_id: self._grace_tasks.pop(gid, None))
                return

            elif after.channel:
                # Bot vừa join kênh voice, reconnect xong, hoặc thay đổi deafen
                self._cancel_grace_task(guild_id)
                player = self._players.get(guild_id)
                if player and player._is_reconnecting:
                    log.info(f"[Music] Bot đã kết nối lại voice tại guild {guild_id}. Lên lịch phục hồi phát nhạc...")
                    self._schedule_reconnect_task(guild_id, player)
                elif channel_changed:
                    self._cancel_reconnect_task(guild_id)

                # Luôn kiểm tra tình trạng người nghe trong kênh
                self._check_and_schedule_empty_voice(guild)
            return

        if member.bot:
            return

        # 2. Xử lý khi người dùng (user) vào/ra/chuyển kênh hoặc thay đổi trạng thái nghe (deaf)
        self._check_and_schedule_empty_voice(guild)

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

        is_actually_playing = player.vc and (player.vc.is_playing() or player.vc.is_paused())
        if is_actually_playing:
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
        if not player or not player.vc or not (player.vc.is_playing() or player.vc.is_paused()):
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
        if not player or not player.vc or not (player.vc.is_playing() or player.vc.is_paused()):
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.skip()
        await ctx.send(tr(s, "music.skipped"), ephemeral=True)

    @commands.hybrid_command(name="pause", description="Tạm dừng nhạc")
    async def pause(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.vc or not player.vc.is_playing():
            await ctx.send(tr(s, "music.no_song_playing"))
            return
        player.vc.pause()
        player.pause_start = time.time()
        await ctx.send(tr(s, "music.paused"), ephemeral=True)

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc")
    async def resume(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        player = self._get(ctx.guild.id)
        if not player or not player.vc or not player.vc.is_paused():
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
            await player.add_and_play(track, force_play=True)
            await ctx.send(f"{e('zb_lofi')} " + tr(s, "music.lofi_soma_success", name=stream['name']))
        else:
            info = await extract_info(stream["url"], force_refresh=True)
            if not info:
                await ctx.send(tr(s, "music.lofi_yt_err"))
                return
            track = Track(info, requester=ctx.author)
            track.is_live = True
            await player.add_and_play(track, force_play=True)
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
        }, str(ctx.guild.id))
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
                    if player.vc and not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
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
            if player.vc and not player.vc.is_playing() and not player.vc.is_paused() and not player.current:
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

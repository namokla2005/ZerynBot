"""
music.py — Optimized Music Cog for ARM (yt-dlp + FFmpegOpusAudio).
Không dùng Lavalink. Tối ưu cho thiết bị ARM yếu như Tablet.

Tối ưu:
  - FFmpegOpusAudio thay FFmpegPCMAudio (giảm ~50% CPU)
  - yt-dlp chạy trong asyncio.to_thread() không block event loop
  - URL Cache 5 phút để tái sử dụng
  - Pre-load bài tiếp theo khi bài hiện tại đang chạy
  - FFmpeg flags tối ưu cho ARM (-threads 1, -b:a 96k)
"""
import asyncio
import os
import time
import logging

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from cache import cache

log = logging.getLogger("BotV2")

# ─── FFmpeg options tối ưu cho ARM ─────────────────────────────────────────────
# Thêm -headers Referer/Origin cho googlevideo → giảm 'Connection reset by peer' và 403
FFMPEG_BEFORE = '-loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 1M -analyzeduration 1000000 -user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" -headers "Referer: https://www.youtube.com/\r\nOrigin: https://www.youtube.com\r\n"'
FFMPEG_OPTS_COPY   = "-vn -sn -c:a copy -threads 1"
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1"

MAX_PLAYERS = 6  # Giới hạn player đồng thời (tối ưu cho tablet 4GB, 10+ server)
MAX_BG_LOAD = 50  # Giới hạn số bài nạp ngầm từ playlist (bảo vệ RAM/CPU tablet)

# ─── Stream lofi 24/7 ──────────────────────────────────────────────────────────
# SomaFM = HTTP/Icecast trực tiếp: KHÔNG BAO GIỜ bị 403, không cần yt-dlp, ít CPU.
# YouTube = live stream (cần yt-dlp + config mới, có thể bị chặn nếu YouTube đổi).
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

# Cookie file cho yt-dlp (tùy chọn, giúp live stream ít bị chặn). None = bỏ qua.
_COOKIE_FILE = os.environ.get("YTDLP_COOKIEFILE", None)

YDL_OPTS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    # ── Cho live stream YouTube (tránh 403) ──────────────────────────────────
    # Dùng client android + web_safari: ít bị YouTube chặn hơn web mặc định.
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web_safari"],
            "player_skip": ["webpage"],  # bỏ fetch webpage → nhanh hơn
        }
    },
    "nocheckcertificate": True,
    "ignoreerrors": True,
}
# Cookie hỗ trợ (chỉ thêm key nếu có file, tránh yt-dlp báo lỗi file không tồn tại)
if _COOKIE_FILE and os.path.exists(_COOKIE_FILE):
    YDL_OPTS["cookiefile"] = _COOKIE_FILE

# ─── URL Cache (TTL 5 phút) ────────────────────────────────────────────────────
_url_cache: dict[str, tuple] = {}  # {cache_key: (info_dict, expire_at)}
_cache_lock = asyncio.Lock()

# Giới hạn số yt-dlp extract chạy đồng thời (bảo vệ CPU tablet)
_extract_semaphore = asyncio.Semaphore(3)


def _fmt_duration(seconds) -> str:
    if seconds is None or seconds <= 0:
        return "🔴 LIVE"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def _extract_sync(query: str) -> dict | None:
    """Đồng bộ yt-dlp (chạy trong thread pool)."""
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            if not query.startswith("http"):
                query = f"ytsearch:{query}"
            info = ydl.extract_info(query, download=False)
            if info and info.get("entries"):
                info = info["entries"][0]
            return info
    except Exception as e:
        log.warning(f"[Music] yt-dlp error: {e}")
        return None


async def extract_info(query: str) -> dict | None:
    """Lấy thông tin bài hát (tích hợp Redis + Local Cache Thread-Safe)."""
    key = query.strip().lower()
    cache_key = f"song_info:{key}"

    # 1. Kiểm tra Redis / Cache wrapper
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    # 2. Kiểm tra bộ nhớ tạm RAM (Thread-Safe)
    async with _cache_lock:
        if key in _url_cache:
            info, expire = _url_cache[key]
            if time.time() < expire:
                return info
            else:
                _url_cache.pop(key, None)

    # 3. Chạy yt-dlp trong thread pool (giới hạn đồng thời bằng semaphore)
    async with _extract_semaphore:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, _extract_sync, query)

    if info:
        # Lưu vào Redis
        await cache.aset(cache_key, info, ttl=600)

        # Giới hạn RAM (Thread-Safe)
        async with _cache_lock:
            if len(_url_cache) > 100:
                old_keys = list(_url_cache.keys())[:20]
                for k in old_keys:
                    _url_cache.pop(k, None)
            _url_cache[key] = (info, time.time() + 300)

    return info


def _get_stream_url(info: dict) -> str | None:
    """Lấy URL stream tốt nhất từ info dict."""
    if not info:
        return None
    # Ưu tiên opus/webm (không cần transcode)
    for f in info.get("formats", []):
        if f.get("acodec") == "opus" and f.get("vcodec") == "none" and f.get("url"):
            return f["url"]
    # Fallback: audio-only bất kỳ
    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("url"):
            return f["url"]
    # Cuối cùng: url trực tiếp
    return info.get("url")


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
        self.now_playing_msg : discord.Message | None = None
        self._preload_task : asyncio.Task | None = None

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
        if self.loop_mode == 1 and self.current:
            asyncio.run_coroutine_threadsafe(self._play(self.current), self.loop)
        elif self.loop_mode == 2 and self.current:
            self.queue.append(self.current)
            self._dispatch_next()
        else:
            self._dispatch_next()

    def _dispatch_next(self):
        if self.queue:
            asyncio.run_coroutine_threadsafe(self._play(self.queue.pop(0)), self.loop)
        else:
            self.current = None
            asyncio.run_coroutine_threadsafe(self._on_queue_empty(), self.loop)

    async def _on_queue_empty(self):
        """Xử lý khi hàng chờ hết — xóa embed/disable nút NP cũ và gửi thông báo."""
        if self.now_playing_msg:
            try:
                view = discord.ui.View()  # View rỗng = xóa toàn bộ nút bấm cũ
                await self.now_playing_msg.edit(view=view)
            except Exception:
                pass
            self.now_playing_msg = None

        if self.text_channel:
            try:
                await self.text_channel.send("✅ Hàng chờ nhạc đã hết!")
            except Exception:
                pass

    async def _play(self, track: Track):
        if not self.vc or not self.vc.is_connected():
            return

        # Lấy stream URL tươi mới nếu chưa có hoặc URL đã hết hạn (sau 5.5h)
        if not track.stream_url or track.is_stream_expired:
            info = await extract_info(track.url or track.title)
            if not info:
                log.warning(f"[Music] Cannot get stream URL: {track.title}")
                self._dispatch_next()
                return
            track.stream_url    = _get_stream_url(info)
            track.stream_expire = time.time() + (5.5 * 3600)

        self.current = track

        # Tự động chọn Opus copy mode nếu stream gốc là Opus WebM (giảm 90% CPU)
        is_opus = (
            track.stream_url
            and ("mime=audio%2Fwebm" in track.stream_url or "audio/webm" in track.stream_url)
        )
        try:
            if is_opus:
                source = discord.FFmpegOpusAudio(
                    track.stream_url,
                    before_options=FFMPEG_BEFORE,
                    options=FFMPEG_OPTS_COPY,
                )
            else:
                source = discord.FFmpegOpusAudio(
                    track.stream_url,
                    before_options=FFMPEG_BEFORE,
                    options=FFMPEG_OPTS_ENCODE,
                    bitrate=64,
                )
            self.vc.play(source, after=self._after_play)
        except Exception as e:
            log.error(f"[Music] FFmpeg error cho bài '{track.title}': {e}")
            if is_opus:
                try:
                    log.info(f"[Music] Thử lại bài '{track.title}' bằng FFMPEG_OPTS_ENCODE...")
                    source = discord.FFmpegOpusAudio(
                        track.stream_url,
                        before_options=FFMPEG_BEFORE,
                        options=FFMPEG_OPTS_ENCODE,
                        bitrate=64,
                    )
                    self.vc.play(source, after=self._after_play)
                    await self._send_now_playing()
                    return
                except Exception as retry_err:
                    log.error(f"[Music] FFmpeg retry error cho '{track.title}': {retry_err}")

            if self.text_channel:
                try:
                    await self.text_channel.send(
                        f"⚠️ Không thể giải mã/phát bài: **{track.title}**. Đang chuyển sang bài tiếp theo...",
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
        view  = MusicControlView(self)
        embed = _make_np_embed(self.current, len(self.queue), self.loop_mode)
        try:
            self.now_playing_msg = await self.text_channel.send(embed=embed, view=view)
        except Exception as e:
            log.error(f"[Music] NP embed error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────
    async def add_and_play(self, track: Track):
        if self.vc.is_playing() or self.vc.is_paused():
            self.queue.append(track)
        else:
            await self._play(track)

    def skip(self):
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()

    async def stop(self):
        self.queue.clear()
        self.current   = None
        self.loop_mode = 0
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


# ─── Embeds ────────────────────────────────────────────────────────────────────
def _make_np_embed(track: Track, queue_len: int, loop_mode: int) -> discord.Embed:
    loop_str = {0: "Tắt", 1: "1 bài", 2: "Tất cả"}[loop_mode]

    embed = discord.Embed(
        color=0x3498DB,
        description=(
            f"**Now Playing**\n"
            f"### [{track.title}]({track.url})\n"
            f"**{track.uploader}** — `{track.duration_str}` — {track.requester_mention}\n\n"
            f"**Volume:** `100%` — **Queue:** `{queue_len} bài` — **Loop:** `{loop_str}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
    )

    if track.thumbnail:
        embed.set_image(url=track.thumbnail)

    return embed


# ─── Music Control View ────────────────────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, player: MusicPlayer):
        super().__init__(timeout=None)
        self.player = player
        # Cập nhật trạng thái các nút
        if player.vc.is_paused():
            self.btn_pause.label = "▶️ Tiếp tục"
            self.btn_pause.style = discord.ButtonStyle.success
        else:
            self.btn_pause.label = "⏸️ Tạm dừng"
            self.btn_pause.style = discord.ButtonStyle.secondary

        loop_labels = ["🔄 Lặp lại", "🔂 Lặp 1 bài", "🔁 Lặp tất cả"]
        loop_styles = [discord.ButtonStyle.secondary, discord.ButtonStyle.success, discord.ButtonStyle.primary]
        self.btn_loop.label = loop_labels[player.loop_mode]
        self.btn_loop.style = loop_styles[player.loop_mode]

    async def _check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or interaction.user.voice.channel != self.player.vc.channel:
            await interaction.response.send_message(
                "❌ Bạn phải ở trong cùng kênh voice với bot!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⏸️ Tạm dừng", style=discord.ButtonStyle.secondary, row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        if self.player.vc.is_paused():
            self.player.vc.resume()
            button.label = "⏸️ Tạm dừng"
            button.style = discord.ButtonStyle.secondary
        else:
            self.player.vc.pause()
            button.label = "▶️ Tiếp tục"
            button.style = discord.ButtonStyle.success
        await interaction.message.edit(view=self)

    @discord.ui.button(label="⏭️ Bỏ qua", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.skip()

    @discord.ui.button(label="⏹️ Dừng", style=discord.ButtonStyle.secondary, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        await self.player.stop()

    @discord.ui.button(label="🔄 Lặp lại", style=discord.ButtonStyle.secondary, row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.loop_mode = (self.player.loop_mode + 1) % 3
        loop_labels = ["🔄 Lặp lại", "🔂 Lặp 1 bài", "🔁 Lặp tất cả"]
        loop_styles = [discord.ButtonStyle.secondary, discord.ButtonStyle.success, discord.ButtonStyle.primary]
        button.label = loop_labels[self.player.loop_mode]
        button.style = loop_styles[self.player.loop_mode]
        embed = _make_np_embed(self.player.current, len(self.player.queue), self.player.loop_mode)
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

    @discord.ui.button(label="✅ Xác nhận xóa", style=discord.ButtonStyle.danger, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("❌ Bạn không có quyền thao tác!", ephemeral=True)
        if self.selected_index is None:
            return await interaction.response.send_message("❌ Vui lòng chọn bài hát trước!", ephemeral=True)
        await interaction.response.defer()
        track = self.tracks[self.selected_index]
        import database as db
        await db.async_delete_track_from_playlist(track["id"])
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(
            content=f"✅ Đã xóa **{track.get('title', 'Unknown')}** khỏi playlist **{self.pl['name']}**!",
            embed=None, view=self,
        )
        self.stop()

    @discord.ui.button(label="❌ Hủy bỏ", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("❌ Bạn không có quyền thao tác!", ephemeral=True)
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content="↩️ Đã hủy thao tác.", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⏳ Hết thời gian chờ, thao tác bị hủy.", embed=None, view=self)
            except Exception:
                pass


# ─── Cog ───────────────────────────────────────────────────────────────────────
class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self._players: dict[int, MusicPlayer] = {}
        self._bg_tasks: set[asyncio.Task] = set()

    def cog_unload(self):
        """Cancel tất cả background playlist-load tasks khi cog bị unload."""
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()

    # ── Helpers ────────────────────────────────────────────────────────────
    def _get(self, guild_id: int) -> MusicPlayer | None:
        return self._players.get(guild_id)

    def _drop(self, guild_id: int):
        self._players.pop(guild_id, None)

    async def _ensure(self, ctx: commands.Context) -> MusicPlayer | None:
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return None

        guild_id = ctx.guild.id
        player   = self._players.get(guild_id)

        if player and player.vc.is_connected():
            if player.vc.channel != ctx.author.voice.channel:
                await ctx.send("❌ Bot đang ở kênh voice khác!")
                return None
            player.text_channel = ctx.channel
            return player

        # Kiểm tra giới hạn số player đồng thời
        if guild_id not in self._players and len(self._players) >= MAX_PLAYERS:
            await ctx.send(
                f"⚠️ Bot đang phát nhạc tối đa **{MAX_PLAYERS} server** cùng lúc để bảo vệ hiệu năng hệ thống.\n"
                "Vui lòng thử lại sau!",
                ephemeral=True,
            )
            return None

        try:
            vc = await ctx.author.voice.channel.connect()
        except Exception as e:
            await ctx.send(f"❌ Không thể vào voice: {e}")
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
        """Tự rời kênh sau 30s nếu không còn ai (có kiểm tra Race Condition)."""
        if member.bot:
            return
        player = self._players.get(member.guild.id)
        if not player or not player.vc.is_connected():
            return
        channel = player.vc.channel
        if any(not m.bot for m in channel.members):
            return
            
        await asyncio.sleep(30)
        
        # Sửa Race Condition: Kiểm tra lại player còn tồn tại và nguyên vẹn hay không
        current_player = self._players.get(member.guild.id)
        if current_player is not player:
            return
            
        if any(not m.bot for m in player.vc.channel.members):
            return
            
        if player.text_channel:
            try:
                await player.text_channel.send("👋 Không còn ai trong kênh voice, bot đã tự rời!")
            except Exception:
                pass
        await player.stop()
        self._drop(member.guild.id)

    # ── Basic commands ─────────────────────────────────────────────────────
    @commands.hybrid_command(name="join", description="Gọi bot vào kênh voice")
    async def join(self, ctx: commands.Context):
        if await self._ensure(ctx):
            await ctx.send("✅ Đã tham gia kênh voice!", ephemeral=True)

    @commands.hybrid_command(name="leave", description="Bắt bot rời kênh voice")
    async def leave(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if player:
            await player.stop()
            self._drop(ctx.guild.id)
            await ctx.send("👋 Đã rời kênh voice!")
        else:
            await ctx.send("❌ Bot không ở trong kênh thoại nào!")

    @commands.hybrid_command(name="play", description="Phát nhạc từ YouTube (tên bài hoặc link)")
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    async def play(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        player = await self._ensure(ctx)
        if not player:
            return

        msg = await ctx.send("🔍 Đang tìm kiếm...")
        info = await extract_info(query)
        if not info:
            await msg.edit(content=f"❌ Không tìm thấy nhạc cho: `{query}`")
            return

        track = Track(info, requester=ctx.author)

        if player.vc.is_playing() or player.vc.is_paused():
            player.queue.append(track)
            embed = discord.Embed(
                title="📋 Đã thêm vào hàng chờ",
                description=f"**[{track.title}]({track.url})**",
                color=0x5865F2,
            )
            embed.add_field(name="⏱ Thời lượng",   value=track.duration_str,         inline=True)
            embed.add_field(name="📌 Vị trí",       value=str(len(player.queue)),     inline=True)
            embed.add_field(name="🙋 Yêu cầu bởi", value=ctx.author.mention,         inline=True)
            if track.thumbnail:
                embed.set_image(url=track.thumbnail)
            await msg.edit(content=None, embed=embed)
        else:
            await msg.delete()
            await player.add_and_play(track)

    @commands.hybrid_command(name="stop", description="Dừng nhạc và rời kênh")
    async def stop(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send("❌ Bot không đang phát nhạc!")
            return
        await player.stop()
        self._drop(ctx.guild.id)
        await ctx.send("⏹️ Đã dừng nhạc và rời kênh!")

    @commands.hybrid_command(name="skip", description="Bỏ qua bài hát hiện tại")
    async def skip(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player or not (player.vc.is_playing() or player.vc.is_paused()):
            await ctx.send("❌ Không có nhạc đang phát!")
            return
        player.skip()
        await ctx.send("⏭️ Đã bỏ qua!", ephemeral=True)

    @commands.hybrid_command(name="pause", description="Tạm dừng nhạc")
    async def pause(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player or not player.vc.is_playing():
            await ctx.send("❌ Không có nhạc đang phát!")
            return
        player.vc.pause()
        await ctx.send("⏸️ Đã tạm dừng!", ephemeral=True)

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc")
    async def resume(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player or not player.vc.is_paused():
            await ctx.send("❌ Nhạc không đang tạm dừng!")
            return
        player.vc.resume()
        await ctx.send("▶️ Đã tiếp tục!", ephemeral=True)

    @commands.hybrid_command(name="loop", description="Bật/tắt chế độ lặp lại")
    async def loop(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send("❌ Không có nhạc đang phát!")
            return
        player.loop_mode = (player.loop_mode + 1) % 3
        await ctx.send(["➡️ Đã TẮT lặp lại!", "🔂 Lặp bài hiện tại!", "🔁 Lặp toàn bộ hàng chờ!"][player.loop_mode])

    @commands.hybrid_command(name="queue", description="Xem hàng chờ nhạc")
    async def queue_cmd(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player or (not player.current and not player.queue):
            await ctx.send("❌ Hàng chờ đang trống!")
            return
        desc = ""
        if player.current:
            desc += f"**▶️ Đang phát:** [{player.current.title}]({player.current.url}) `[{player.current.duration_str}]`\n\n"
        if player.queue:
            desc += "**📋 Hàng chờ:**\n"
            for i, t in enumerate(player.queue[:10], 1):
                desc += f"`{i:2}.` [{t.title}]({t.url}) `[{t.duration_str}]`\n"
            if len(player.queue) > 10:
                desc += f"\n*... và {len(player.queue) - 10} bài khác*"
        embed = discord.Embed(title="🎵 Hàng chờ nhạc", description=desc, color=0x5865F2)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="replay", description="Phát lại bài hát từ đầu")
    async def replay(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player or not player.current:
            await ctx.send("❌ Không có bài nào đang phát!")
            return
        player.queue.insert(0, player.current)
        player.skip()
        await ctx.send("⏪ Đã phát lại từ đầu!", ephemeral=True)

    @commands.hybrid_command(name="lofi", description="Phát nhạc Lofi 24/7 (mặc định SomaFM, ổn định)")
    @app_commands.describe(source="Nguồn lofi (mặc định: soma — ổn định, không bị chặn)")
    @app_commands.choices(source=[
        app_commands.Choice(name="SomaFM Groove Salad (ổn định 24/7)", value="soma"),
        app_commands.Choice(name="YouTube Lofi Girl (có thể bị chặn)", value="youtube"),
    ])
    async def lofi(self, ctx: commands.Context, source: str = None):
        await ctx.defer()
        # Hybrid command: slash = Choice value (str), prefix = raw string trực tiếp
        src_key = source if source else "soma"
        if src_key not in LOFI_STREAMS:
            await ctx.send(f"❌ Nguồn không hợp lệ. Dùng: `soma` hoặc `youtube`")
            return
        stream = LOFI_STREAMS.get(src_key, LOFI_STREAMS["soma"])

        player = await self._ensure(ctx)
        if not player:
            return

        if src_key == "soma":
            # Stream HTTP trực tiếp (Icecast): tạo Track giả, KHÔNG cần yt-dlp
            # → không bao giờ bị 403, tốn ít CPU/RAM, lý tưởng cho tablet 24/7
            track = Track(
                {"title": stream["title"], "url": stream["url"], "webpage_url": stream["url"], "duration": -1},
                requester=ctx.author,
            )
            track.stream_url = stream["url"]
            track.stream_expire = float("inf")  # stream sống mãi, không expire
            await player.add_and_play(track)
            await ctx.send(
                f"✅ Đang phát **{stream['name']}** 24/7!\n"
                f"💡 Mẹo: dùng `/lofi youtube` nếu muốn Lofi Girl (có thể bị chặn)."
            )
        else:
            # YouTube path: dùng yt-dlp với config mới + FFmpeg headers
            await ctx.send(f"⏳ Đang tải **{stream['name']}** (YouTube)...")
            await ctx.invoke(self.play, query=stream["url"])

    # ── Playlist commands ──────────────────────────────────────────────────
    @commands.hybrid_group(name="playlist", description="Quản lý playlist nhạc")
    async def playlist_group(self, ctx: commands.Context):
        pass

    @playlist_group.command(name="create", description="Tạo một playlist mới")
    @app_commands.describe(name="Tên playlist muốn tạo")
    async def playlist_create(self, ctx: commands.Context, *, name: str):
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if pl:
            await ctx.send(f"❌ Playlist **{name}** đã tồn tại!")
        else:
            await db.async_create_playlist(str(ctx.guild.id), name, str(ctx.author.id), ctx.author.display_name)
            await ctx.send(f"✅ Đã tạo playlist **{name}**!")

    @playlist_group.command(name="add", description="Thêm bài hát vào playlist")
    @app_commands.describe(query="Link hoặc tên bài hát", name="Tên playlist")
    async def playlist_add(self, ctx: commands.Context, query: str, *, name: str):
        await ctx.defer()
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist **{name}**! Tạo bằng `/playlist create {name}`")
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền thêm vào playlist của người khác!")
            return
        info = await extract_info(query)
        if not info:
            await ctx.send("❌ Không tìm thấy bài hát!")
            return

        thumbnail = _get_best_thumbnail(info)

        await db.async_add_track_to_playlist(pl["id"], {
            "title": info.get("title", "Unknown"),
            "id":    info.get("id", ""),
            "webpage_url": info.get("webpage_url") or info.get("url", ""),
            "duration": info.get("duration") or -1,
            "uploader": info.get("uploader") or info.get("channel") or "—",
            "thumbnail": thumbnail,
            "url": "",
        })
        await ctx.send(f"✅ Đã thêm **{info.get('title')}** vào playlist **{name}**!")

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
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl or not pl.get("tracks"):
            await ctx.send(f"❌ Không tìm thấy hoặc playlist **{name}** đang trống!")
            return
        player = await self._ensure(ctx)
        if not player:
            return
        
        tracks = pl["tracks"]
        msg = await ctx.send(f"⏳ Đang tải bài 1 từ playlist **{name}**...")
        
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
                await msg.edit(content=f"▶️ Đang phát bài 1 và nạp ngầm **{len(tracks) - 1}** bài còn lại từ **{name}**...")
            else:
                await msg.edit(content=f"▶️ Đã nạp playlist **{name}**!")
        else:
            await msg.edit(content=f"⚠️ Không thể tải bài 1. Đang nạp các bài tiếp theo từ playlist **{name}**...")

        # 2. Nạp ngầm các bài còn lại ở background task
        if len(tracks) > 1:
            task = asyncio.create_task(self._load_playlist_background(player, tracks[1:], ctx.author))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

    @playlist_group.command(name="show", description="Xem danh sách bài trong playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_show(self, ctx: commands.Context, *, name: str):
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl or not pl.get("tracks"):
            await ctx.send(f"❌ Không tìm thấy hoặc playlist **{name}** đang trống!")
            return
        desc = ""
        for i, t in enumerate(pl["tracks"], 1):
            title = t.get("title", "Unknown")
            dur   = _fmt_duration(t.get("duration", 0))
            desc += f"`{i:2}.` **{title}** `[{dur}]`\n"
            if i >= 15:
                rem = len(pl["tracks"]) - 15
                if rem > 0:
                    desc += f"\n*... và {rem} bài khác*"
                break
        embed = discord.Embed(title=f"🎵 Playlist: {pl['name']}", description=desc, color=0x5865F2)
        if pl.get("creator_name"):
            embed.set_footer(text=f"Tạo bởi: {pl['creator_name']} • {len(pl['tracks'])} bài hát")
        await ctx.send(embed=embed)

    @playlist_group.command(name="remove", description="Xóa playlist do bạn tạo")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_remove(self, ctx: commands.Context, *, name: str):
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist **{name}**!")
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền xóa playlist của người khác!")
            return
        await db.async_delete_playlist(pl["id"], str(ctx.guild.id))
        await ctx.send(f"✅ Đã xóa playlist **{name}**!")

    @playlist_group.command(name="removesong", description="Xóa một bài hát khỏi playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_removesong(self, ctx: commands.Context, *, name: str):
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist **{name}**!")
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền chỉnh sửa playlist của người khác!")
            return
        if not pl.get("tracks"):
            await ctx.send(f"❌ Playlist **{name}** đang trống!")
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
            title=f"🗑️ Xóa bài hát khỏi: {pl['name']}",
            description=desc,
            color=discord.Color.red(),
        )
        embed.set_footer(text="Chọn bài từ menu ↓ rồi bấm Xác nhận")
        view = RemoveSongView(ctx, pl, pl["tracks"])
        view.message = await ctx.send(embed=embed, view=view)

    @playlist_group.command(name="loop", description="Đổi chế độ lặp lại hàng chờ")
    async def playlist_loop(self, ctx: commands.Context):
        player = self._get(ctx.guild.id)
        if not player:
            await ctx.send("❌ Không có nhạc đang phát!")
            return
        player.loop_mode = (player.loop_mode + 1) % 3
        await ctx.send(["➡️ Đã TẮT lặp lại!", "🔂 Lặp bài hiện tại!", "🔁 Lặp toàn bộ hàng chờ!"][player.loop_mode])


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

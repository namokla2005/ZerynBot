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
import time
import logging

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

log = logging.getLogger("BotV2")

# ─── FFmpeg options tối ưu cho ARM ─────────────────────────────────────────────
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS   = "-vn -b:a 96k -ar 48000 -ac 2 -threads 1"

YDL_OPTS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

# ─── URL Cache (TTL 5 phút) ────────────────────────────────────────────────────
_url_cache: dict[str, tuple] = {}  # {cache_key: (info_dict, expire_at)}


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
    """Lấy thông tin bài hát (có cache). Không block event loop."""
    key = query.strip().lower()

    # Cache hit
    if key in _url_cache:
        info, expire = _url_cache[key]
        if time.time() < expire:
            return info

    # Cache miss → extract trong thread riêng
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _extract_sync, query)

    if info:
        _url_cache[key] = (info, time.time() + 300)  # 5 phút TTL

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


# ─── Track ─────────────────────────────────────────────────────────────────────
class Track:
    __slots__ = ("title", "url", "stream_url", "duration", "uploader", "thumbnail", "requester")

    def __init__(self, info: dict, requester: discord.Member | None = None):
        self.title      = info.get("title", "Unknown")
        self.url        = info.get("webpage_url") or info.get("url", "")
        self.stream_url = _get_stream_url(info)
        self.duration   = info.get("duration")
        self.uploader   = info.get("uploader") or info.get("channel") or "—"
        self.thumbnail  = info.get("thumbnail")
        self.requester  = requester

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
        if nxt.stream_url:
            return
        try:
            info = await extract_info(nxt.url or nxt.title)
            if info:
                nxt.stream_url = _get_stream_url(info)
        except Exception as e:
            log.debug(f"[Music] Preload error: {e}")

    def _after_play(self, error=None):
        if error:
            log.warning(f"[Music] Player error: {error}")
        loop = self.guild._state.loop
        if self.loop_mode == 1 and self.current:
            asyncio.run_coroutine_threadsafe(self._play(self.current), loop)
        elif self.loop_mode == 2 and self.current:
            self.queue.append(self.current)
            self._dispatch_next(loop)
        else:
            self._dispatch_next(loop)

    def _dispatch_next(self, loop):
        if self.queue:
            asyncio.run_coroutine_threadsafe(self._play(self.queue.pop(0)), loop)
        else:
            self.current = None
            asyncio.run_coroutine_threadsafe(self._notify_empty(), loop)

    async def _notify_empty(self):
        if self.text_channel:
            try:
                await self.text_channel.send("✅ Hàng chờ nhạc đã hết!")
            except Exception:
                pass

    async def _play(self, track: Track):
        if not self.vc or not self.vc.is_connected():
            return

        # Lấy stream URL nếu chưa có
        if not track.stream_url:
            info = await extract_info(track.url or track.title)
            if not info:
                log.warning(f"[Music] Cannot get stream URL: {track.title}")
                self._dispatch_next(self.guild._state.loop)
                return
            track.stream_url = _get_stream_url(info)

        self.current = track

        try:
            source = discord.FFmpegOpusAudio(
                track.stream_url,
                before_options=FFMPEG_BEFORE,
                options=FFMPEG_OPTS,
            )
            self.vc.play(source, after=self._after_play)
        except Exception as e:
            log.error(f"[Music] FFmpeg error: {e}")
            self._dispatch_next(self.guild._state.loop)
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
    loop_icons = {0: "➡️ Tắt", 1: "🔂 1 bài", 2: "🔁 Tất cả"}
    desc = (
        f"### [{track.title}]({track.url})\n"
        f"```ansi\n"
        f"\u001b[1;34m⏱ Thời lượng  \u001b[0m {track.duration_str}\n"
        f"\u001b[1;34m👤 Kênh       \u001b[0m {track.uploader}\n"
        f"\u001b[1;34m🙋 Yêu cầu bởi\u001b[0m {track.requester_mention}\n"
        f"\u001b[1;34m🔄 Lặp lại    \u001b[0m {loop_icons[loop_mode]}\n"
        f"\u001b[1;34m📋 Hàng chờ   \u001b[0m {queue_len} bài\n"
        f"```\n"
        f"▬▬▬🔘▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    embed = discord.Embed(title="🎵 Đang phát nhạc", description=desc, color=0x5865F2)
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    embed.set_footer(text="Zeryn Music • Powered by yt-dlp")
    return embed


# ─── Music Control View ────────────────────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, player: MusicPlayer):
        super().__init__(timeout=None)
        self.player = player
        # Cập nhật label Pause/Resume
        if player.vc.is_paused():
            self.btn_pause.label = "▶️ Tiếp tục"
            self.btn_pause.style = discord.ButtonStyle.success
        else:
            self.btn_pause.label = "⏸️ Tạm dừng"
            self.btn_pause.style = discord.ButtonStyle.secondary

    async def _check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or interaction.user.voice.channel != self.player.vc.channel:
            await interaction.response.send_message(
                "❌ Bạn phải ở trong cùng kênh voice với bot!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⏸️ Tạm dừng", style=discord.ButtonStyle.secondary, emoji=None, row=0)
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

    @discord.ui.button(label="⏭️ Bỏ qua", style=discord.ButtonStyle.primary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.skip()

    @discord.ui.button(label="⏹️ Dừng", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        guild_id = self.player.guild.id
        await self.player.stop()
        # Cleanup will happen in cog

    @discord.ui.button(label="🔄 Lặp lại", style=discord.ButtonStyle.secondary, row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        await interaction.response.defer()
        self.player.loop_mode = (self.player.loop_mode + 1) % 3
        labels = ["🔄 Lặp lại", "🔂 Lặp 1 bài", "🔁 Lặp tất cả"]
        styles = [discord.ButtonStyle.secondary, discord.ButtonStyle.success, discord.ButtonStyle.primary]
        button.label = labels[self.player.loop_mode]
        button.style = styles[self.player.loop_mode]
        embed = _make_np_embed(self.player.current, len(self.player.queue), self.player.loop_mode)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="❤️ Yêu thích", style=discord.ButtonStyle.secondary, row=1)
    async def btn_like(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not self.player.current:
            await interaction.followup.send("❌ Không có bài nào đang phát!", ephemeral=True)
            return
        import database as db
        guild_id_str = str(self.player.guild.id)
        pl = await db.async_get_playlist_by_name(guild_id_str, "Yêu thích")
        if not pl:
            pl_id = await db.async_create_playlist(
                guild_id_str, "Yêu thích",
                str(interaction.user.id), interaction.user.display_name
            )
        else:
            pl_id = pl["id"]
        t = self.player.current
        await db.async_add_track_to_playlist(pl_id, {
            "title": t.title, "id": "", "webpage_url": t.url,
            "duration": t.duration or -1, "uploader": t.uploader, "url": "",
        })
        await interaction.followup.send(
            f"❤️ Đã lưu **{t.title}** vào playlist **Yêu thích**!", ephemeral=True
        )


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
        """Tự rời kênh sau 30s nếu không còn ai."""
        if member.bot:
            return
        player = self._players.get(member.guild.id)
        if not player or not player.vc.is_connected():
            return
        channel = player.vc.channel
        if any(not m.bot for m in channel.members):
            return
        await asyncio.sleep(30)
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
                embed.set_thumbnail(url=track.thumbnail)
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

    @commands.hybrid_command(name="lofi", description="Phát kênh Lofi Girl 24/7")
    async def lofi(self, ctx: commands.Context):
        await ctx.invoke(self.play, query="https://www.youtube.com/watch?v=jfKfPfyJRdk")

    # ── Playlist commands ──────────────────────────────────────────────────
    @commands.hybrid_group(name="playlist", description="Quản lý playlist nhạc")
    async def playlist_group(self, ctx: commands.Context):
        pass

    @playlist_group.command(name="name", description="Tạo một playlist mới")
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
            await ctx.send(f"❌ Không tìm thấy playlist **{name}**! Tạo bằng `/playlist name {name}`")
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền thêm vào playlist của người khác!")
            return
        info = await extract_info(query)
        if not info:
            await ctx.send("❌ Không tìm thấy bài hát!")
            return
        await db.async_add_track_to_playlist(pl["id"], {
            "title": info.get("title", "Unknown"),
            "id":    info.get("id", ""),
            "webpage_url": info.get("webpage_url") or info.get("url", ""),
            "duration": info.get("duration") or -1,
            "uploader": info.get("uploader") or info.get("channel") or "—",
            "url": "",
        })
        await ctx.send(f"✅ Đã thêm **{info.get('title')}** vào playlist **{name}**!")

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
        msg = await ctx.send(f"⏳ Đang tải playlist **{name}**...")
        added = 0
        for t in pl["tracks"]:
            query = t.get("webpage_url") or t.get("title", "")
            info  = await extract_info(query)
            if not info:
                continue
            track = Track(info, requester=ctx.author)
            if not player.vc.is_playing() and not player.vc.is_paused() and added == 0:
                await player.add_and_play(track)
            else:
                player.queue.append(track)
            added += 1
        await msg.edit(content=f"▶️ Đã thêm **{added}** bài từ playlist **{name}** vào hàng chờ!")

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

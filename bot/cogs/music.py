"""
music.py — High-quality Music Cog for Bot v2.
Supports both Slash and Prefix/Mention commands seamlessly.
Requires: yt-dlp + FFmpeg in system PATH + PyNaCl.

Updates:
- Custom progress bar and blue card layout.
- Added persistent MusicControlView with action buttons (Autoplay, Stop, Pause/Resume, Skip, Like).
- Like button automatically creates or appends to a "Yêu thích" playlist.
- Hybrid command group: /playlist name, /playlist add, /playlist play, /playlist loop.
- Loop queue logic to repeat playlist when enabled.
"""
import asyncio
import sys
import os
import logging

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

log = logging.getLogger("BotV2")

# ─── Configuration ─────────────────────────────────────────────────────────────
YDL_OPTS_PLAY = {
    "quiet":       True,
    "no_warnings": True,
    "format":      "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist":  True,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "nocheckcertificate": True,
    "socket_timeout": 5,
}

YDL_OPTS_LIVE = {
    "quiet":         True,
    "no_warnings":   True,
    "format":        "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist":    True,
    "live_from_start": False,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "nocheckcertificate": True,
    "socket_timeout": 5,
}

YDL_OPTS_SEARCH = {
    "quiet":         True,
    "no_warnings":   True,
    "extract_flat":  True,
    "skip_download": True,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "nocheckcertificate": True,
    "socket_timeout": 3,
}

FFMPEG_OPTS = {
    "before_options": (
        "-nostdin "
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 10 "
        "-analyzeduration 0 "
        "-probesize 32"
    ),
    "options": "-vn",
}

LOFI_URL = "https://www.youtube.com/c/LofiGirl/live"
NUMS     = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def _fmt_duration(seconds) -> str:
    if seconds is None or seconds == 0:
        return "🔴 LIVE"
    if int(seconds) < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _now_playing_embed(track: dict, mq: "MusicQueue") -> discord.Embed:
    title_link = f"[{track['title']}]({track.get('webpage_url', '')})"
    duration_str = _fmt_duration(track.get("duration"))
    requester = track.get("requester_mention") or "—"
    
    # Calculate queue statistics
    queue_len = len(mq.queue)
    total_seconds = sum(t.get("duration") or 0 for t in mq.queue)
    if track.get("duration"):
        total_seconds += track["duration"]
    total_duration_str = _fmt_duration(total_seconds)
    
    desc = f"**{title_link}**\n"
    desc += f"CLOUD MUSIC — `{duration_str}` — {requester}\n\n"
    desc += f"**Volume:** `100%` — **Queue:** `{queue_len} songs` — **Total duration:** `{total_duration_str}`\n\n"
    desc += "▬▬▬▬▬▬▬▬▬🔘▬▬▬▬▬▬▬▬▬▬▬▬▬"
    
    e = discord.Embed(
        title       = "Now Playing",
        description = desc,
        color       = 0x5865F2,  # discord blue/blurple
    )
    if track.get("thumbnail"):
        e.set_thumbnail(url=track["thumbnail"])
    return e


class MusicQueue:
    def __init__(self):
        self.queue:    list[dict]  = []
        self.current:  dict | None = None
        self.loop:     bool = False
        self.loop_queue: bool = False
        self.autoplay: bool = False
        self._transitioning: bool = False
        self.last_message: discord.Message | None = None


# ─── Interactive Controls View ───────────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Bot không ở trong kênh voice nào!", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel.id != vc.channel.id:
            await interaction.response.send_message("❌ Bạn cần ở trong cùng kênh voice với Bot để điều khiển!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Autoplay", style=discord.ButtonStyle.secondary, emoji="♾️")
    async def autoplay_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        mq = self.cog.get_queue(self.guild_id)
        mq.autoplay = not mq.autoplay
        await interaction.response.defer()

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary, emoji="🟦")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            mq = self.cog.get_queue(self.guild_id)
            mq.queue.clear()
            mq.current = None
            mq._transitioning = True
            vc.stop()
            await vc.disconnect()
        await interaction.response.defer()

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            if vc.is_paused():
                vc.resume()
                button.label = "Pause"
                button.emoji = "⏸️"
            elif vc.is_playing():
                vc.pause()
                button.label = "Resume"
                button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Like", style=discord.ButtonStyle.secondary, emoji="❤️")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        mq = self.cog.get_queue(self.guild_id)
        if not mq.current:
            await interaction.response.defer()
            return
        
        await interaction.response.defer()
        import database as db
        guild_id_str = str(self.guild_id)
        pl = await db.async_get_playlist_by_name(guild_id_str, "Yêu thích")
        if not pl:
            pl_id = await db.async_create_playlist(guild_id_str, "Yêu thích")
        else:
            pl_id = pl["id"]
        
        await db.async_add_track_to_playlist(pl_id, mq.current)


# ─── Search UI Dropdown ────────────────────────────────────────────────────────
class SearchSelect(discord.ui.Select):
    def __init__(self, entries: list, cog: "Music", invoker_id: int):
        self.entries    = entries
        self.cog        = cog
        self.invoker_id = invoker_id

        options = []
        for i, e in enumerate(entries):
            title = (e.get("title") or "Unknown")[:80]
            dur   = _fmt_duration(e.get("duration"))
            ch    = (e.get("uploader") or e.get("channel") or "")[:40]
            options.append(discord.SelectOption(
                label       = title,
                value       = str(i),
                description = f"⏱ {dur}  |  {ch}"[:100],
                emoji       = NUMS[i],
            ))

        super().__init__(
            placeholder = "🎵 Chọn bài hát muốn phát...",
            options     = options,
            min_values  = 1,
            max_values  = 1,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "❌ Đây không phải lệnh của bạn!", ephemeral=True)
            return

        idx   = int(self.values[0])
        entry = self.entries[idx]
        url   = f"https://www.youtube.com/watch?v={entry['id']}"

        await interaction.response.defer()

        self.disabled = True
        try:
            await interaction.edit_original_response(view=self.view)
        except Exception:
            pass

        track = await self.cog._fetch_info(url, YDL_OPTS_PLAY)
        if not track or not track.get("url"):
            await interaction.followup.send("❌ Không thể tải bài hát!", ephemeral=True)
            self.view.stop()
            return

        guild = interaction.guild
        vc    = guild.voice_client
        if not vc:
            try:
                vc = await interaction.user.voice.channel.connect(self_deaf=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Lỗi kết nối Voice: {e}", ephemeral=True)
                self.view.stop()
                return

        track["requester_mention"] = interaction.user.mention
        mq = self.cog.get_queue(guild.id)
        if vc.is_playing() or vc.is_paused():
            mq.queue.append(track)
            embed = discord.Embed(
                title       = "📋 Đã thêm vào hàng chờ",
                description = f"[{track['title']}]({track.get('webpage_url', '')})",
                color       = discord.Color.blurple(),
            )
            embed.add_field(name="Vị trí",     value=str(len(mq.queue)),               inline=True)
            embed.add_field(name="Thời lượng", value=_fmt_duration(track.get("duration")), inline=True)
            await interaction.followup.send(embed=embed)
        else:
            await self.cog._play_track(vc, guild.id, track, interaction)

        self.view.stop()


class SearchView(discord.ui.View):
    def __init__(self, entries: list, cog: "Music", invoker_id: int):
        super().__init__(timeout=30)
        self._select = SearchSelect(entries, cog, invoker_id)
        self._msg: discord.Message | None = None
        self.add_item(self._select)

    async def on_timeout(self):
        self._select.disabled = True
        if self._msg:
            try:
                await self._msg.edit(view=self)
                await self._msg.channel.send("⏰ Hết thời gian. Hủy tìm kiếm.")
            except Exception:
                pass


# ─── Music Cog ─────────────────────────────────────────────────────────────────
class Music(commands.Cog, name="Music"):
    """🎵 Lệnh âm nhạc."""

    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self._queues: dict[int, MusicQueue] = {}

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            return
        from database import async_is_module_enabled
        enabled = await async_is_module_enabled(str(ctx.guild.id), "music")
        if not enabled:
            await ctx.send("❌ Module **Music** đã bị tắt trong server này!")
            raise commands.CommandError("Module disabled")

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue()
        return self._queues[guild_id]

    async def _fetch_info(self, query: str, opts: dict) -> dict | None:
        loop = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                try:
                    info = ydl.extract_info(query, download=False)
                    if info and "entries" in info:
                        return info["entries"][0] if info["entries"] else None
                    return info
                except Exception as exc:
                    log.warning(f"[Music] yt-dlp error for '{query}': {exc}")
                    return None

        return await loop.run_in_executor(None, _run)

    async def _ensure_voice(self, ctx: commands.Context) -> discord.VoiceClient | None:
        """Connect/move to the author's voice channel. Returns None on failure."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return None

        target_channel = ctx.author.voice.channel
        guild = ctx.guild
        vc = guild.voice_client

        try:
            if vc is None:
                vc = await target_channel.connect(self_deaf=True)
            elif not vc.is_connected():
                log.info("[Music] Stale voice client detected, reconnecting...")
                await vc.disconnect(force=True)
                self._queues.pop(guild.id, None)
                vc = await target_channel.connect(self_deaf=True)
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
        except Exception as e:
            log.error(f"[Music] Voice connect error: {e}")
            await ctx.send(f"❌ Không thể kết nối kênh voice: `{e}`")
            return None

        return vc

    async def _play_track(
        self,
        vc:            discord.VoiceClient,
        guild_id:      int,
        track:         dict,
        channel:       discord.abc.Messageable,
        is_transition: bool = False,
    ) -> None:
        mq = self.get_queue(guild_id)
        mq.current = track
        mq._transitioning = False

        if not track.get("url") and track.get("webpage_url") and not track.get("is_live"):
            fresh = await self._fetch_info(track["webpage_url"], YDL_OPTS_PLAY)
            if fresh and fresh.get("url"):
                track = {**mq.current, **{k: v for k, v in fresh.items() if v}}
                mq.current = track
            else:
                log.warning(f"[Music] Could not re-fetch URL for '{track.get('title')}', using cached URL.")

        if not track.get("url"):
            if isinstance(channel, commands.Context):
                await channel.send("❌ Không thể lấy link phát nhạc!")
            elif isinstance(channel, discord.Interaction):
                await channel.followup.send("❌ Không thể lấy link phát nhạc!")
            else:
                await channel.send("❌ Không thể lấy link phát nhạc!")
            return

        headers = track.get("http_headers") or {}
        if "User-Agent" not in headers:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        
        headers_list = []
        for k, v in headers.items():
            if k and v:
                headers_list.append(f"{k}: {v}")
        headers_str = "\r\n".join(headers_list) + "\r\n"

        before_opts = (
            "-nostdin "
            "-reconnect 1 "
            "-reconnect_streamed 1 "
            "-reconnect_delay_max 10 "
            "-analyzeduration 0 "
            "-probesize 32 "
            f'-headers "{headers_str}"'
        )

        source = discord.FFmpegPCMAudio(track["url"], before_options=before_opts, options="-vn -b:a 128k")
        source = discord.PCMVolumeTransformer(source, volume=0.5)

        def _after(error):
            if error:
                log.error(f"[Music] Playback error in guild {guild_id}: {error}")

            mq = self.get_queue(guild_id)

            if mq._transitioning:
                return
            mq._transitioning = True

            if mq.loop and mq.current:
                asyncio.run_coroutine_threadsafe(
                    self._play_track(vc, guild_id, mq.current, channel, is_transition=True),
                    self.bot.loop,
                )
            elif mq.queue:
                next_track = mq.queue.pop(0)
                if getattr(mq, "loop_queue", False) and mq.current:
                    mq.queue.append(mq.current)
                asyncio.run_coroutine_threadsafe(
                    self._play_track(vc, guild_id, next_track, channel, is_transition=True),
                    self.bot.loop,
                )
            elif getattr(mq, "loop_queue", False) and mq.current:
                asyncio.run_coroutine_threadsafe(
                    self._play_track(vc, guild_id, mq.current, channel, is_transition=True),
                    self.bot.loop,
                )
            elif mq.autoplay and mq.current:
                asyncio.run_coroutine_threadsafe(
                    self._do_autoplay(vc, guild_id, mq.current, channel),
                    self.bot.loop,
                )
            else:
                mq.current = None
                mq._transitioning = False

        if vc.is_playing():
            vc.stop()
        vc.play(source, after=_after)

        view = MusicControlView(self, guild_id)

        # 1. If it's an automatic transition, try to edit the last message
        if is_transition and mq.last_message:
            try:
                await mq.last_message.edit(embed=_now_playing_embed(track, mq), view=view)
                return
            except Exception:
                pass

        # 2. Otherwise, delete the old message to keep only one active player card
        if mq.last_message:
            try:
                await mq.last_message.delete()
            except Exception:
                pass

        # 3. Send/reply the new card
        if isinstance(channel, commands.Context):
            msg = await channel.send(embed=_now_playing_embed(track, mq), view=view)
            mq.last_message = msg
        elif isinstance(channel, discord.Interaction):
            msg = await channel.followup.send(embed=_now_playing_embed(track, mq), view=view)
            mq.last_message = msg
        else:
            msg = await channel.send(embed=_now_playing_embed(track, mq), view=view)
            mq.last_message = msg

    async def _do_autoplay(self, vc, guild_id, current, channel):
        query = f"ytsearch1:{current.get('title', '')} song"
        loop  = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(YDL_OPTS_SEARCH) as ydl:
                try:
                    info = ydl.extract_info(query, download=False)
                    entries = (info or {}).get("entries", [])
                    return entries[0] if entries else None
                except Exception:
                    return None

        entry = await loop.run_in_executor(None, _run)
        if not entry or not entry.get("id"):
            mq = self.get_queue(guild_id)
            mq._transitioning = False
            return
        url   = f"https://www.youtube.com/watch?v={entry['id']}"
        track = await self._fetch_info(url, YDL_OPTS_PLAY)
        if track:
            await self._play_track(vc, guild_id, track, channel)

    # ─── Commands ──────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="join", description="Bot vào kênh voice của bạn")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return
        vc = await self._ensure_voice(ctx)
        if vc:
            await ctx.send(f"✅ Đã vào **{vc.channel.name}**! (Tự động tắt tai nghe)")

    @commands.hybrid_command(name="leave", description="Bot rời kênh voice và xóa hàng chờ")
    async def leave(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if not vc:
            await ctx.send("❌ Bot không ở trong kênh voice nào!")
            return
        mq = self.get_queue(ctx.guild.id)
        mq.queue.clear()
        mq.current = None
        await vc.disconnect()
        await ctx.send("👋 Đã rời kênh voice!")

    @commands.hybrid_command(name="play", description="Phát nhạc từ YouTube (tên bài hoặc link)")
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return

        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        is_url = query.startswith(("http://", "https://"))
        search = query if is_url else f"ytsearch1:{query}"

        track = await self._fetch_info(search, YDL_OPTS_PLAY)
        if not track or not track.get("url"):
            await ctx.send("❌ Không tìm thấy hoặc không thể tải bài hát!")
            return

        track["requester_mention"] = ctx.author.mention
        mq = self.get_queue(ctx.guild.id)

        if vc.is_playing() or vc.is_paused():
            mq.queue.append(track)
            embed = discord.Embed(
                title       = "📋 Đã thêm vào hàng chờ",
                description = f"[{track['title']}]({track.get('webpage_url', '')})",
                color       = discord.Color.blurple(),
            )
            embed.add_field(name="Vị trí",     value=str(len(mq.queue)),                 inline=True)
            embed.add_field(name="Thời lượng", value=_fmt_duration(track.get("duration")), inline=True)
            await ctx.send(embed=embed)
        else:
            try:
                await self._play_track(vc, ctx.guild.id, track, ctx)
            except Exception as e:
                log.error(f"[Music] play error: {e}")
                await ctx.send(f"❌ Lỗi khi phát nhạc: {e}")

    @commands.hybrid_command(name="search", description="Tìm kiếm nhạc và chọn từ 5 kết quả")
    @app_commands.describe(query="Tên bài hát muốn tìm kiếm")
    async def search(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return

        await ctx.defer()
        loop = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(YDL_OPTS_SEARCH) as ydl:
                try:
                    return ydl.extract_info(f"ytsearch5:{query}", download=False)
                except Exception:
                    return None

        raw = await loop.run_in_executor(None, _run)
        if not raw or not raw.get("entries"):
            await ctx.send("❌ Không tìm thấy kết quả nào!")
            return

        entries = [e for e in raw["entries"] if e][:5]
        if not entries:
            await ctx.send("❌ Không tìm thấy kết quả nào!")
            return

        lines = [
            f"{NUMS[i]}  **{e.get('title','Unknown')}** — `{_fmt_duration(e.get('duration'))}`"
            for i, e in enumerate(entries)
        ]
        embed = discord.Embed(
            title       = f"🔍 Kết quả tìm kiếm: {query}",
            description = "\n".join(lines) + "\n\n*Chọn bài bằng menu bên dưới*",
            color       = discord.Color.blurple(),
        )

        view = SearchView(entries, self, ctx.author.id)
        new_msg = await ctx.send(embed=embed, view=view)
        view._msg = new_msg

    @commands.hybrid_command(name="stop", description="Dừng nhạc và xóa toàn bộ hàng chờ")
    async def stop(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await ctx.send("❌ Bot không đang phát nhạc!")
            return
        mq = self.get_queue(ctx.guild.id)
        mq.queue.clear()
        mq.current = None
        mq.loop = False
        mq._transitioning = True
        vc.stop()
        await ctx.send("⏹️ Đã dừng nhạc và xóa hàng chờ!")

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc đang tạm dừng")
    async def resume(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if not vc or not vc.is_paused():
            await ctx.send("❌ Nhạc không bị tạm dừng!")
            return
        vc.resume()
        await ctx.send("▶️ Đã tiếp tục phát!")

    @commands.hybrid_command(name="loop", description="Bật/tắt chế độ lặp lại bài hiện tại")
    async def loop_cmd(self, ctx: commands.Context):
        mq = self.get_queue(ctx.guild.id)
        mq.loop = not mq.loop
        msg = "🔂 Đã **bật** chế độ lặp lại!" if mq.loop else "➡️ Đã **tắt** chế độ lặp lại!"
        await ctx.send(msg)

    @commands.hybrid_command(name="autoplay", description="Bật/tắt tự động phát bài tiếp theo")
    async def autoplay(self, ctx: commands.Context):
        mq = self.get_queue(ctx.guild.id)
        mq.autoplay = not mq.autoplay
        msg = "♾️ Đã **bật** Autoplay!" if mq.autoplay else "⛔ Đã **tắt** Autoplay!"
        await ctx.send(msg)

    @commands.hybrid_command(name="replay", description="Phát lại bài hát hiện tại từ đầu")
    async def replay(self, ctx: commands.Context):
        mq = self.get_queue(ctx.guild.id)
        vc = ctx.guild.voice_client
        if not mq.current or not vc:
            await ctx.send("❌ Không có bài nào đang phát!")
            return
        await ctx.send("🔁 Đang phát lại bài hiện tại...")
        await self._play_track(vc, ctx.guild.id, mq.current, ctx)

    @commands.hybrid_command(name="lofi", description="Phát kênh Lofi Girl 24/7")
    async def lofi(self, ctx: commands.Context):
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return

        await ctx.defer()
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        track = await self._fetch_info(LOFI_URL, YDL_OPTS_LIVE)
        if not track or not track.get("url"):
            await ctx.send("❌ Không thể kết nối Lofi stream! YouTube có thể đang giới hạn truy cập.")
            return

        track["requester_mention"] = ctx.author.mention
        mq = self.get_queue(ctx.guild.id)
        mq.queue.clear()

        await ctx.send("📻 **Lofi Girl 24/7** đang bật... ☕🌙")
        await self._play_track(vc, ctx.guild.id, track, ctx)

    # ─── Playlist Commands ─────────────────────────────────────────────────────────

    @commands.hybrid_group(name="playlist", description="Quản lý danh sách phát")
    async def playlist_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("❌ Vui lòng nhập lệnh phụ: `/playlist name`, `/playlist add`, `/playlist play`, `/playlist loop`")

    @playlist_group.command(name="name", description="Tạo hoặc hiển thị playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_name(self, ctx: commands.Context, name: str):
        await ctx.defer()
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await db.async_create_playlist(str(ctx.guild.id), name)
            await ctx.send(f"✅ Đã tạo playlist mới với tên: **{name}**!")
        else:
            tracks = pl.get("tracks") or []
            if not tracks:
                await ctx.send(f"📂 Playlist **{name}** đang trống!")
                return
            lines = [f"{i+1}. **{t['title']}** — `{_fmt_duration(t['duration'])}`" for i, t in enumerate(tracks[:20])]
            if len(tracks) > 20:
                lines.append(f"... và {len(tracks) - 20} bài hát khác.")
            embed = discord.Embed(
                title=f"📂 Playlist: {pl['name']}",
                description="\n".join(lines),
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)

    @playlist_group.command(name="add", description="Thêm bài hát vào playlist")
    @app_commands.describe(name="Tên của playlist", query="Tên bài hát hoặc link YouTube")
    async def playlist_add(self, ctx: commands.Context, name: str, query: str):
        await ctx.defer()
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist nào tên **{name}**! Hãy tạo trước bằng `/playlist name {name}`")
            return
        
        import aiohttp
        import re
        
        video_id = None
        webpage_url = None
        
        try:
            if query.startswith(("http://", "https://")):
                webpage_url = query
                match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})", webpage_url)
                if match:
                    video_id = match.group(1)
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}") as resp:
                        text = await resp.text()
                        match = re.search(r"\"videoId\":\"([0-9A-Za-z_-]{11})\"", text)
                        if match:
                            video_id = match.group(1)
                            webpage_url = f"https://www.youtube.com/watch?v={video_id}"
            
            if not video_id or not webpage_url:
                await ctx.send("❌ Không tìm thấy bài hát!")
                return
                
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://www.youtube.com/oembed?url={webpage_url}&format=json") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        track = {
                            "title": data.get("title", "Unknown"),
                            "id": video_id,
                            "webpage_url": webpage_url,
                            "duration": -1,
                            "uploader": data.get("author_name", "—"),
                            "url": ""
                        }
                    else:
                        track = {
                            "title": query[:50] + "..." if not query.startswith("http") else "Video YouTube",
                            "id": video_id,
                            "webpage_url": webpage_url,
                            "duration": -1,
                            "uploader": "—",
                            "url": ""
                        }
        except Exception as e:
            log.error(f"[Playlist Add Fast] Error: {e}")
            await ctx.send("❌ Đã xảy ra lỗi khi tìm kiếm bài hát!")
            return
        
        await db.async_add_track_to_playlist(pl["id"], track)
        await ctx.send(f"✅ Đã thêm **{track['title']}** vào playlist **{pl['name']}**!")

    @playlist_group.command(name="play", description="Phát toàn bộ bài hát trong playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_play(self, ctx: commands.Context, name: str):
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return

        await ctx.defer()
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl or not pl.get("tracks"):
            await ctx.send(f"❌ Không tìm thấy hoặc playlist **{name}** đang trống!")
            return
        
        vc = await self._ensure_voice(ctx)
        if not vc:
            return

        tracks = pl["tracks"]
        for t in tracks:
            t["requester_mention"] = ctx.author.mention
            
        mq = self.get_queue(ctx.guild.id)
        
        if vc.is_playing() or vc.is_paused():
            mq.queue.extend(tracks)
            await ctx.send(f"📋 Đã thêm **{len(tracks)}** bài hát từ playlist **{pl['name']}** vào hàng chờ!")
        else:
            first_track = tracks.pop(0)
            mq.queue.extend(tracks)
            await ctx.send(f"▶️ Bắt đầu phát playlist **{pl['name']}** (**{len(tracks) + 1}** bài hát)!")
            try:
                # Truyền ctx.channel để fix Unknown Message
                import asyncio
                asyncio.create_task(self._play_track(vc, ctx.guild.id, first_track, ctx.channel))
            except Exception as e:
                log.error(f"[Music] playlist play error: {e}")
                await ctx.channel.send(f"❌ Lỗi khi phát nhạc: {e}")

    @playlist_group.command(name="loop", description="Bật/tắt lặp lại toàn bộ playlist/hàng chờ")
    async def playlist_loop(self, ctx: commands.Context):
        mq = self.get_queue(ctx.guild.id)
        mq.loop_queue = not getattr(mq, "loop_queue", False)
        status = "BẬT" if mq.loop_queue else "TẮT"
        await ctx.send(f"🔁 Đã **{status}** chế độ lặp lại hàng chờ (Loop Queue)!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

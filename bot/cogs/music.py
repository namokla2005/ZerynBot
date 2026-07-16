"""
music.py — Wavelink (Lavalink) Music Cog cho Bot v2.
Tối ưu hóa hoàn toàn để chạy trên Termux không tốn CPU.
"""
import asyncio
import os
import sys
import logging

import discord
from discord import app_commands
from discord.ext import commands
import wavelink

log = logging.getLogger("BotV2")

def _fmt_duration(seconds) -> str:
    if seconds is None or seconds <= 0:
        return "🔴 LIVE"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def _now_playing_embed(track: wavelink.Playable, queue: wavelink.Queue) -> discord.Embed:
    title_link = f"[{track.title}]({track.uri})"
    duration_str = _fmt_duration(track.length / 1000) if track.length else "🔴 LIVE"
    requester = getattr(track, "requester_mention", "@Người ẩn danh")
    
    # Calculate queue statistics
    queue_len = len(queue)
    total_seconds = sum((t.length / 1000) for t in queue if getattr(t, "length", None))
    if track.length:
        total_seconds += (track.length / 1000)
    total_duration_str = _fmt_duration(total_seconds)
    
    desc = f"**{title_link}**\n"
    desc += f"CLOUD MUSIC — `{duration_str}` — {requester}\n\n"
    desc += f"**Volume:** `100%` — **Queue:** `{queue_len} songs` — **Total duration:** `{total_duration_str}`\n\n"
    desc += "▬▬🔘▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    
    e = discord.Embed(
        title       = "Now Playing",
        description = desc,
        color       = 0x5865F2,
    )
    if track.artwork:
        e.set_thumbnail(url=track.artwork)
    return e
class RemoveSongSelect(discord.ui.Select):
    def __init__(self, tracks):
        options = []
        for i, track in enumerate(tracks[:25]):
            title = track.get("title", "Unknown")
            if len(title) > 90:
                title = title[:87] + "..."
            options.append(discord.SelectOption(
                label=f"{i+1}. {title}",
                value=str(i)
            ))
        super().__init__(placeholder="Chọn bài hát muốn xóa...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_index = int(self.values[0])
        await interaction.response.defer()

class RemoveSongView(discord.ui.View):
    def __init__(self, ctx, pl, tracks):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.pl = pl
        self.tracks = tracks
        self.selected_index = None
        self.add_item(RemoveSongSelect(tracks))

    @discord.ui.button(label="Xác nhận", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("❌ Bạn không có quyền thao tác!", ephemeral=True)
        if self.selected_index is None:
            return await interaction.response.send_message("❌ Vui lòng chọn bài hát từ menu trước!", ephemeral=True)
            
        await interaction.response.defer()
        track_to_delete = self.tracks[self.selected_index]
        import database as db
        await db.async_delete_track_from_playlist(track_to_delete["id"])
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content=f"✅ Đã xóa bài hát **{track_to_delete.get('title', 'Unknown')}** khỏi playlist!", embed=None, view=self)
        self.stop()

    @discord.ui.button(label="Hủy bỏ", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("❌ Bạn không có quyền thao tác!", ephemeral=True)
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content="✅ Đã hủy thao tác.", embed=None, view=self)
        self.stop()
        
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(content="⏳ Đã hết thời gian chờ, thao tác bị hủy.", embed=None, view=self)
        except Exception:
            pass

# ─── UI Components ─────────────────────────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        
        # Cập nhật trạng thái nút Pause/Resume
        guild = cog.bot.get_guild(guild_id)
        if guild:
            player: wavelink.Player = guild.voice_client
            if player and player.paused:
                self.btn_pause.label = "Resume"
                self.btn_pause.emoji = "▶️"
            else:
                self.btn_pause.label = "Pause"
                self.btn_pause.emoji = "⏸️"

    async def get_player(self, interaction: discord.Interaction) -> wavelink.Player:
        if not interaction.guild:
            return None
        player: wavelink.Player = interaction.guild.voice_client
        if not player:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Bot không phát nhạc ở server này!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Bot không phát nhạc ở server này!", ephemeral=True)
            return None
        if not interaction.user.voice or interaction.user.voice.channel != player.channel:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Bạn phải ở trong cùng kênh thoại với bot!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Bạn phải ở trong cùng kênh thoại với bot!", ephemeral=True)
            return None
        return player

    @discord.ui.button(label="Autoplay", style=discord.ButtonStyle.secondary, emoji="🔀")
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = await self.get_player(interaction)
        if not player: return
        
        if player.queue.mode == wavelink.QueueMode.auto_play:
            player.queue.mode = wavelink.QueueMode.normal
        else:
            player.queue.mode = wavelink.QueueMode.auto_play

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary, emoji="⏹️")
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = await self.get_player(interaction)
        if not player: return
        player.queue.clear()
        await player.disconnect()

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️")
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = await self.get_player(interaction)
        if not player: return
        
        if player.paused:
            await player.pause(False)
            button.label = "Pause"
            button.emoji = "⏸️"
        else:
            await player.pause(True)
            button.label = "Resume"
            button.emoji = "▶️"
            
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = await self.get_player(interaction)
        if not player: return
        await player.skip(force=True)

    @discord.ui.button(label="Like", style=discord.ButtonStyle.secondary, emoji="❤️")
    async def btn_like(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        player = await self.get_player(interaction)
        if not player or not player.current:
            return
            
        import database as db
        guild_id_str = str(self.guild_id)
        pl = await db.async_get_playlist_by_name(guild_id_str, "Yêu thích")
        if not pl:
            pl_id = await db.async_create_playlist(guild_id_str, "Yêu thích")
        else:
            pl_id = pl["id"]
        
        track_dict = {
            "title": player.current.title,
            "id": player.current.identifier,
            "webpage_url": player.current.uri,
            "duration": int(player.current.length / 1000) if player.current.length else -1,
            "uploader": player.current.author or "—",
            "url": ""
        }
        await db.async_add_track_to_playlist(pl_id, track_dict)
        await interaction.followup.send(f"❤️ Đã lưu **{track_dict['title']}** vào playlist **Yêu thích**!")
class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Tạo kết nối đến Lavalink
        self.bot.loop.create_task(self.connect_nodes())

    async def connect_nodes(self):
        await self.bot.wait_until_ready()
        # Thay thế bằng public lavalink node
        # Danh sách node: https://lavalink.darrennathanael.com/No-TTS/Public-Lavalink/
        node = wavelink.Node(
            uri="https://lavalinkv4.serenetia.com:443", 
            password="https://dsc.gg/ajidevserver"
        )
        try:
            import aiohttp
            connector = aiohttp.TCPConnector(ssl=False)
            session = aiohttp.ClientSession(connector=connector)
            
            await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100, client_session=session)
            log.info("[Wavelink] Connected to Lavalink Node!")
        except Exception as e:
            log.error(f"[Wavelink] Failed to connect: {e}")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        log.info(f"[Wavelink] Node {payload.node.identifier} is ready!")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        if not player or not player.channel:
            return
        
        # Gửi thông báo Now Playing
        view = MusicControlView(self, player.guild.id)
        embed = _now_playing_embed(payload.track, player.queue)
        
        # Xóa tin nhắn cũ nếu có
        old_msg = getattr(player, "now_playing_msg", None)
        if old_msg:
            try:
                await old_msg.delete()
            except Exception:
                pass
        
        channel = getattr(player, "text_channel", None)
        if not channel:
            channel = self.bot.get_channel(player.channel.id)
        
        if channel:
            try:
                msg = await channel.send(embed=embed, view=view)
                player.now_playing_msg = msg
            except Exception as e:
                log.error(f"[Wavelink] Lỗi gửi embed: {e}")

    async def _ensure_voice(self, ctx: commands.Context) -> wavelink.Player:
        if not ctx.author.voice:
            await ctx.send("❌ Bạn cần vào kênh voice trước!")
            return None
        
        player: wavelink.Player = ctx.guild.voice_client
        if not player:
            try:
                player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
                player.autoplay = wavelink.AutoPlayMode.enabled
            except Exception as e:
                await ctx.send(f"❌ Không thể vào voice: {e}")
                return None
        
        player.text_channel = ctx.channel
        return player

    @commands.hybrid_command(name="join", description="Gọi bot vào kênh voice")
    async def join(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if player:
            await ctx.send("✅ Đã tham gia kênh thoại!")

    @commands.hybrid_command(name="leave", description="Bắt bot rời kênh voice")
    async def leave(self, ctx: commands.Context):
        player: wavelink.Player = ctx.guild.voice_client
        if player:
            await player.disconnect()
            await ctx.send("👋 Đã rời kênh voice!")
        else:
            await ctx.send("❌ Bot không ở trong kênh thoại nào!")

    @commands.hybrid_command(name="play", description="Phát nhạc từ YouTube (nhanh nhất)")
    @app_commands.describe(query="Tên bài hát hoặc link")
    async def play(self, ctx: commands.Context, *, query: str):
        await ctx.defer()
        player = await self._ensure_voice(ctx)
        if not player: return

        tracks: wavelink.Search = await wavelink.Playable.search(query)
        if not tracks:
            await ctx.send(f"❌ Không tìm thấy nhạc cho: `{query}`")
            return

        track = tracks[0]
        track.requester_mention = ctx.author.mention

        if player.playing or player.paused:
            player.queue.put(track)
            embed = discord.Embed(
                title       = "📋 Đã thêm vào hàng chờ",
                description = f"[{track.title}]({track.uri})",
                color       = discord.Color.blurple(),
            )
            embed.add_field(name="Vị trí", value=str(len(player.queue)), inline=True)
            embed.add_field(name="Thời lượng", value=_fmt_duration(track.length / 1000) if track.length else "—", inline=True)
            await ctx.send(embed=embed)
        else:
            await player.play(track)
            embed = discord.Embed(
                title       = "▶️ Đã nhận yêu cầu",
                description = f"Đang tải dữ liệu cho **[{track.title}]({track.uri})**...",
                color       = discord.Color.blurple(),
            )
            await ctx.send(embed=embed)
    @commands.hybrid_group(name="playlist", description="Quản lý playlist cá nhân")
    async def playlist_group(self, ctx: commands.Context):
        pass

    @playlist_group.command(name="name", description="Tạo một playlist mới")
    @app_commands.describe(name="Tên playlist muốn tạo")
    async def playlist_name(self, ctx: commands.Context, name: str):
        import database as db
        guild_id_str = str(ctx.guild.id)
        pl = await db.async_get_playlist_by_name(guild_id_str, name)
        if pl:
            await ctx.send(f"❌ Playlist **{name}** đã tồn tại trong server!")
        else:
            await db.async_create_playlist(guild_id_str, name, str(ctx.author.id), ctx.author.display_name)
            await ctx.send(f"✅ Đã tạo playlist mới: **{name}**!")

    @playlist_group.command(name="add", description="Thêm một bài hát vào playlist")
    @app_commands.describe(query="Link hoặc tên bài hát", name="Tên playlist")
    async def playlist_add(self, ctx: commands.Context, query: str, name: str):
        await ctx.defer()
        import database as db
        pl = await db.async_get_playlist_by_name(str(ctx.guild.id), name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist nào tên **{name}**! Hãy tạo trước bằng `/playlist name {name}`")
            return
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền thêm bài hát vào playlist của người khác!")
            return
        
        tracks: wavelink.Search = await wavelink.Playable.search(query)
        if not tracks:
            await ctx.send("❌ Không tìm thấy bài hát!")
            return

        t = tracks[0]
        track_dict = {
            "title": t.title,
            "id": t.identifier,
            "webpage_url": t.uri,
            "duration": int(t.length / 1000) if t.length else -1,
            "uploader": t.author or "—",
            "url": ""
        }
        await db.async_add_track_to_playlist(pl["id"], track_dict)
        await ctx.send(f"✅ Đã thêm **{t.title}** vào playlist **{pl['name']}**!")

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
        
        player = await self._ensure_voice(ctx)
        if not player:
            return

        tracks = pl["tracks"]
        added = 0
        for t in tracks:
            # Chuyển đổi track dict thành query URL để wavelink tự lấy
            query = t.get("webpage_url") or f"https://www.youtube.com/watch?v={t['id']}"
            search_res: wavelink.Search = await wavelink.Playable.search(query)
            if search_res:
                playable = search_res[0]
                playable.requester_mention = ctx.author.mention
                player.queue.put(playable)
                added += 1

        if not player.playing and not player.paused and not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track)
            await ctx.send(f"▶️ Bắt đầu phát playlist **{pl['name']}** ({added} bài hát)!")
        else:
            await ctx.send(f"📋 Đã thêm **{added}** bài hát từ playlist **{pl['name']}** vào hàng chờ!")

    @playlist_group.command(name="loop", description="Đổi chế độ lặp lại")
    async def playlist_loop(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        
        if player.queue.mode == wavelink.QueueMode.normal:
            player.queue.mode = wavelink.QueueMode.loop_all
            await ctx.send("🔁 Đã BẬT lặp lại toàn bộ hàng chờ!")
        elif player.queue.mode == wavelink.QueueMode.loop_all:
            player.queue.mode = wavelink.QueueMode.loop
            await ctx.send("🔂 Đã BẬT lặp lại 1 bài hát!")
        else:
            player.queue.mode = wavelink.QueueMode.normal
            await ctx.send("➡️ Đã TẮT lặp lại!")

    @playlist_group.command(name="show", description="Xem danh sách bài hát trong playlist")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_show(self, ctx: commands.Context, name: str):
        import database as db
        guild_id_str = str(ctx.guild.id)
        pl = await db.async_get_playlist_by_name(guild_id_str, name)
        if not pl or not pl.get("tracks"):
            await ctx.send(f"❌ Không tìm thấy hoặc playlist **{name}** đang trống!")
            return
            
        desc = ""
        for i, track in enumerate(pl["tracks"], 1):
            title = track.get("title", "Unknown")
            duration = _fmt_duration(track.get("duration", 0))
            desc += f"`{i}.` **{title}** `[{duration}]`\n"
            if i >= 15:
                desc += f"... và {len(pl['tracks']) - 15} bài khác.\n"
                break
                
        embed = discord.Embed(
            title=f"🎵 Playlist: {pl['name']}",
            description=desc,
            color=discord.Color.blurple()
        )
        if pl.get("creator_name"):
            embed.set_footer(text=f"Tạo bởi: {pl['creator_name']}")
            
        await ctx.send(embed=embed)

    @playlist_group.command(name="remove", description="Xóa một playlist do bạn tạo")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_remove(self, ctx: commands.Context, name: str):
        import database as db
        guild_id_str = str(ctx.guild.id)
        pl = await db.async_get_playlist_by_name(guild_id_str, name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist nào tên **{name}**!")
            return
            
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền xóa playlist của người khác!")
            return
            
        await db.async_delete_playlist(pl["id"], guild_id_str)
        await ctx.send(f"✅ Đã xóa playlist **{name}**!")

    @playlist_group.command(name="removesong", description="Xóa một bài hát khỏi playlist của bạn")
    @app_commands.describe(name="Tên của playlist")
    async def playlist_removesong(self, ctx: commands.Context, name: str):
        import database as db
        guild_id_str = str(ctx.guild.id)
        pl = await db.async_get_playlist_by_name(guild_id_str, name)
        if not pl:
            await ctx.send(f"❌ Không tìm thấy playlist nào tên **{name}**!")
            return
            
        if pl.get("creator_id") and pl["creator_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Bạn không có quyền chỉnh sửa playlist của người khác!")
            return
            
        if not pl.get("tracks"):
            await ctx.send(f"❌ Playlist **{name}** đang trống!")
            return
            
        desc = ""
        for i, track in enumerate(pl["tracks"], 1):
            title = track.get("title", "Unknown")
            duration = _fmt_duration(track.get("duration", 0))
            desc += f"`{i}.` **{title}** `[{duration}]`\n"
            if i >= 20:
                desc += f"... và {len(pl['tracks']) - 20} bài khác.\n"
                break
                
        embed = discord.Embed(
            title=f"🗑️ Xóa bài hát khỏi: {pl['name']}",
            description=desc + "\n\n👉 **Vui lòng chọn bài hát cần xóa ở menu bên dưới (hỗ trợ hiển thị tối đa 25 bài đầu tiên) và bấm Xác nhận.**",
            color=discord.Color.red()
        )
        
        view = RemoveSongView(ctx, pl, pl["tracks"])
        view.message = await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="stop", description="Dừng nhạc và xóa toàn bộ hàng chờ")
    async def stop(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        player.queue.clear()
        await player.disconnect()
        await ctx.send("⏹️ Đã dừng nhạc và rời kênh!")

    @commands.hybrid_command(name="pause", description="Tạm dừng phát nhạc")
    async def pause(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        await player.pause(True)
        await ctx.send("⏸️ Đã tạm dừng nhạc!")

    @commands.hybrid_command(name="resume", description="Tiếp tục phát nhạc đang tạm dừng")
    async def resume(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        await player.pause(False)
        await ctx.send("▶️ Đã tiếp tục phát nhạc!")

    @commands.hybrid_command(name="loop", description="Bật/tắt chế độ lặp lại bài hiện tại")
    async def loop(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        if player.queue.mode == wavelink.QueueMode.loop:
            player.queue.mode = wavelink.QueueMode.normal
            await ctx.send("➡️ Đã TẮT lặp lại bài hát!")
        else:
            player.queue.mode = wavelink.QueueMode.loop
            await ctx.send("🔂 Đã BẬT lặp lại bài hát hiện tại!")

    @commands.hybrid_command(name="autoplay", description="Bật/tắt tự động phát bài tiếp theo")
    async def autoplay(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player: return
        if player.queue.mode == wavelink.QueueMode.auto_play:
            player.queue.mode = wavelink.QueueMode.normal
            await ctx.send("➡️ Đã TẮT Autoplay!")
        else:
            player.queue.mode = wavelink.QueueMode.auto_play
            await ctx.send("🔀 Đã BẬT Autoplay (Tự động phát nhạc tương tự)!")

    @commands.hybrid_command(name="replay", description="Phát lại bài hát hiện tại từ đầu")
    async def replay(self, ctx: commands.Context):
        player = await self._ensure_voice(ctx)
        if not player or not player.current: return
        await player.seek(0)
        await ctx.send("⏪ Đã phát lại bài hát từ đầu!")

    @commands.hybrid_command(name="lofi", description="Phát kênh Lofi Girl 24/7")
    async def lofi(self, ctx: commands.Context):
        await ctx.invoke(self.play, query="http://lofi.stream.laut.fm/lofi")

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

"""
views.py — View/Select UI của trình phát nhạc (nút điều khiển, hàng đợi, tìm
kiếm, phân trang lời bài hát).

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). `player` chỉ được import lúc
type-check (`from __future__ import annotations`) nên `player.py` có thể import
`MusicControlView` mà không sinh vòng import.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from cache import cache
from database import async_get_guild_settings
from i18n import tr

try:
    from emojis import e, embed_title, partial
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, partial

from .config import MAX_QUEUE_SIZE
from .embeds import _make_np_embed
from .extractor import (
    _clean_song_title,
    _fmt_duration,
    extract_info,
)

if TYPE_CHECKING:  # tránh vòng import với player.py
    from .player import MusicPlayer, Track

log = logging.getLogger("BotV2.Music")


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

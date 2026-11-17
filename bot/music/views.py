"""
views.py — View/Select UI của trình phát nhạc (nút điều khiển, hàng đợi, tìm
kiếm, phân trang lời bài hát).

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Import runtime của `Track` nằm
trong callback tìm kiếm, nên `player.py` có thể import `MusicControlView`
mà không sinh vòng import.
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
from i18n import t, tr

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


def _player_voice_error(player, interaction, cog=None) -> str | None:
    """Validate a live player without storing interaction state on a shared view."""
    guild = interaction.guild
    if guild is None or player is None:
        return "music.not_in_voice"
    if getattr(getattr(player, "guild", None), "id", guild.id) != guild.id:
        return "music.not_in_voice"
    cog = cog or getattr(player, "cog", None)
    if cog is not None and cog._get(guild.id) is not player:
        return "music.not_in_voice"
    if any(getattr(player, flag, False) for flag in ("_cleanup_done", "_manual_stopped", "_is_stopping")):
        return "music.not_in_voice"
    vc = player.vc
    if not vc or not vc.channel or (hasattr(vc, "is_connected") and not vc.is_connected()):
        return "music.not_in_voice"
    voice = getattr(interaction.user, "voice", None)
    if not voice or voice.channel != vc.channel:
        return "music.same_voice_err"
    return None


class MusicControlView(discord.ui.View):
    def __init__(self, player: MusicPlayer | None = None, settings: dict | None = None, cog=None):
        super().__init__(timeout=None)
        # Label cua nut bi Discord luu vin vien trong payload tin nhan, nen phai gan
        # theo ngon ngu cua server DUNG LUC dung view (khong the doi ve sau).
        if settings:
            for _ch in self.children:
                if getattr(_ch, "custom_id", None) == "music_loop":
                    _ch.label = tr(settings, "music.btn_loop")
        self.player = player
        self.settings = settings or {}
        self.cog = cog or getattr(player, "cog", None)
        if player is None:
            # Vo persistent (bot.add_view): nhan vat trong payload giu nguyen custom_id
            # de nut van dispatch duoc SAU khi bot restart. Trang thai that (player,
            # ngon ngu, style nut) duoc nap lai trong _check() tu interaction.
            return

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

    async def _resolve(self, interaction: discord.Interaction):
        # The registered shell is shared by every guild. Never hydrate it with
        # guild state: even response.defer() lets another callback run.
        guild = interaction.guild
        player = self.player
        settings = self.settings if player is not None and guild is not None and player.guild.id == guild.id else {}
        if self.cog is not None and guild is not None:
            player = self.cog._get(guild.id)
            try:
                settings = await async_get_guild_settings(str(guild.id))
            except Exception as exc:
                log.debug(f"[Music] _check không đọc được guild settings, dùng bản cu: {exc}")
        error = _player_voice_error(player, interaction, self.cog)
        if error:
            await interaction.response.send_message(tr(settings, error), ephemeral=True)
            return None
        return player, settings

    async def _check(self, interaction: discord.Interaction) -> bool:
        # Keep the historical boolean check API, not its unsafe shell mutation.
        return await self._resolve(interaction) is not None

    async def _defer_control(self, interaction: discord.Interaction):
        state = await self._resolve(interaction)
        if state is None:
            return None
        player, settings = state
        await interaction.response.defer()
        error = _player_voice_error(player, interaction, self.cog)
        if error:
            await interaction.followup.send(tr(settings, error), ephemeral=True)
            return None
        return state

    async def _edit_control(self, interaction, player, settings):
        track = player.current
        if track is None:
            await interaction.followup.send(tr(settings, "music.no_song_playing"), ephemeral=True)
            return
        # A fresh view snapshots button labels/styles for this message only.
        view = MusicControlView(player, settings, cog=self.cog)
        source = getattr(player, "_active_source", None)
        is_opus_copy = bool(
            getattr(player, "_using_opus_copy", False) and source is not None
            and player.vc and getattr(player.vc, "source", None) is source
        )
        embed = _make_np_embed(track, player.queue, player.loop_mode, player.volume, player.get_elapsed(), settings, is_opus_copy=is_opus_copy)
        await interaction.message.edit(embed=embed, view=view)

    @discord.ui.button(label=t("music.btn_autoplay"), custom_id="music_autoplay", style=discord.ButtonStyle.secondary, emoji="♾️", row=0)
    async def btn_autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._defer_control(interaction)
        if state is None:
            return
        player, settings = state
        player.autoplay = not player.autoplay
        await self._edit_control(interaction, player, settings)

    @discord.ui.button(label=t("music.btn_stop"), custom_id="music_stop", style=discord.ButtonStyle.secondary, emoji="⏹️", row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._defer_control(interaction)
        if state is None:
            return
        player, settings = state
        channel = player.text_channel or interaction.channel
        await player.stop()
        if channel:
            try:
                await channel.send(tr(settings, "music.stopped_left"), delete_after=60)
            except Exception:
                pass

    @discord.ui.button(label=t("music.btn_pause"), custom_id="music_pause", style=discord.ButtonStyle.secondary, emoji=partial("zb_pause", "⏸️"), row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._defer_control(interaction)
        if state is None:
            return
        player, settings = state
        if player.current is None:
            return await self._edit_control(interaction, player, settings)
        if player.vc.is_paused():
            player.vc.resume()
            if player.pause_start > 0:
                player.total_paused_time += time.time() - player.pause_start
                player.pause_start = 0.0
        else:
            player.vc.pause()
            player.pause_start = time.time()
        await self._edit_control(interaction, player, settings)

    @discord.ui.button(label=t("music.btn_skip"), custom_id="music_skip", style=discord.ButtonStyle.secondary, emoji=partial("zb_skip", "⏭️"), row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._defer_control(interaction)
        if state is None:
            return
        player, _ = state
        player.skip()

    @discord.ui.button(label=t("music.btn_loop"), custom_id="music_loop", style=discord.ButtonStyle.secondary, emoji=partial("zb_loop", "🔁"), row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._defer_control(interaction)
        if state is None:
            return
        player, settings = state
        player.loop_mode = (player.loop_mode + 1) % 3
        await self._edit_control(interaction, player, settings)

class RemoveSongSelect(discord.ui.Select):
    def __init__(self, tracks: list, settings: dict | None = None):
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
            placeholder=tr(settings, "music.chon_bai_hat_muon_xoa") if settings else t("music.chon_bai_hat_muon_xoa"),
            min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.view.interaction_check(interaction):
            return
        if not self.view._busy and not self.view.is_finished():
            try:
                index = int(self.values[0])
            except (ValueError, IndexError):
                index = -1
            if not 0 <= index < min(25, len(self.view.tracks)):
                return await interaction.response.send_message(tr(self.view.settings, "music.select_song_first"), ephemeral=True)
            self.view.selected_index = index
        await interaction.response.defer()

class RemoveSongView(discord.ui.View):
    def __init__(self, ctx: commands.Context, pl: dict, tracks: list, settings: dict | None = None):
        super().__init__(timeout=60)
        self.ctx            = ctx
        self.settings       = settings or {}
        self.pl             = pl
        self.tracks         = tracks
        self.selected_index : int | None = None
        self.message        : discord.Message | None = None
        self._busy = False
        self.add_item(RemoveSongSelect(tracks, self.settings))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        import database as db
        # Snapshot before any DB/defer await; another selection cannot change
        # the identity being confirmed while Discord or SQLite is responding.
        index = self.selected_index
        track = self.tracks[index].copy() if index is not None and 0 <= index < len(self.tracks) else None
        if not await self.interaction_check(interaction):
            return
        if self._busy or self.is_finished():
            return await interaction.response.defer()
        if track is None:
            return await interaction.response.send_message(tr(self.settings, "music.select_song_first"), ephemeral=True)
        self._busy = True
        try:
            s = await db.async_get_guild_settings(str(interaction.guild.id))
            await interaction.response.defer()
            await db.async_delete_track_from_playlist(track["id"])
            for item in self.children:
                item.disabled = True
            self.stop()
            await interaction.message.edit(
                content=tr(s, "music.song_removed_from_pl", track=track.get('title', 'Unknown'), pl=self.pl['name']),
                embed=None, view=self,
            )
        finally:
            self._busy = False

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        import database as db
        if not await self.interaction_check(interaction):
            return
        if self._busy or self.is_finished():
            return await interaction.response.defer()
        self._busy = True
        try:
            s = await db.async_get_guild_settings(str(interaction.guild.id))
            await interaction.response.defer()
            for item in self.children:
                item.disabled = True
            self.stop()
            await interaction.message.edit(content=tr(s, "music.op_cancelled"), embed=None, view=self)
        finally:
            self._busy = False

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
        self.results = [dict(item) for item in results[:5]]
        self.requester = requester
        self.player = player
        self.settings = settings
        self._voice_channel = player.vc.channel if player.vc else None
        self._claimed = False

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

    def _selection_error(self, interaction) -> str | None:
        if self.view.is_finished():
            return "music.search_timeout"
        error = _player_voice_error(self.player, interaction)
        if error:
            return error
        if self.player.vc.channel != self._voice_channel:
            return "music.same_voice_err"
        return None

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester.id:
            return await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)
        if self._claimed or self.view.is_finished():
            return await interaction.response.defer()
        try:
            idx = int(self.values[0])
        except (ValueError, IndexError):
            idx = -1
        if not 0 <= idx < len(self.results):
            return await interaction.response.send_message(tr(self.settings, "music.search_timeout"), ephemeral=True)
        error = self._selection_error(interaction)
        if error:
            return await interaction.response.send_message(tr(self.settings, error), ephemeral=True)

        # Claim and snapshot before defer: discord.py can dispatch a second click
        # (and replace Select.values) while the first callback is still awaiting.
        self._claimed = True
        chosen = self.results[idx]
        query = chosen.get("webpage_url") or chosen.get("url") or chosen.get("title")
        try:
            await interaction.response.defer()
            error = self._selection_error(interaction)
            if error:
                return await interaction.followup.send(tr(self.settings, error), ephemeral=True)
            info = await extract_info(query)
            if not info:
                return await interaction.followup.send(tr(self.settings, "music.not_found", query=query), ephemeral=True)
            error = self._selection_error(interaction)
            if error:
                return await interaction.followup.send(tr(self.settings, error), ephemeral=True)
            if len(self.player.queue) >= MAX_QUEUE_SIZE:
                return await interaction.followup.send(tr(self.settings, "music.queue_full", max=MAX_QUEUE_SIZE), ephemeral=True)

            # Runtime-only import avoids the player -> views import cycle.
            from .player import Track
            track = Track(info, requester=self.requester)
            is_active = self.player.vc.is_playing() or self.player.vc.is_paused() or self.player.current
            admitted = await self.player.add_and_play(track)
            if admitted is False:
                error = self._selection_error(interaction)
                if not error:
                    error = "music.queue_full" if len(self.player.queue) >= MAX_QUEUE_SIZE else "music.cannot_decode"
                return await interaction.followup.send(tr(self.settings, error, max=MAX_QUEUE_SIZE, title=track.title), ephemeral=True)

            for child in self.view.children:
                child.disabled = True
            self.view.stop()
            if is_active:
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
                await interaction.followup.send(f"▶️ **{track.title}** (`{track.duration_str}`)", ephemeral=True)
            try:
                await interaction.message.edit(view=self.view)
            except Exception:
                pass
        finally:
            if not self.view.is_finished():
                self._claimed = False

class SearchSelectView(discord.ui.View):
    def __init__(self, results: list[dict], requester: discord.Member, player: MusicPlayer, settings: dict):
        super().__init__(timeout=60)
        self.message = None
        self.settings = settings
        self.add_item(SearchSelect(results, requester, player, settings))

    async def on_timeout(self):
        self.stop()
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
            embed.set_footer(text=tr(self.settings, "music.trang_nguon_lrclib_view", page=self.current_page + 1, total=len(self.pages), requested=tr(self.settings, "common.requested_by", user=interaction.user.display_name)))
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
            embed.set_footer(text=tr(self.settings, "music.trang_nguon_lrclib_view", page=self.current_page + 1, total=len(self.pages), requested=tr(self.settings, "common.requested_by", user=interaction.user.display_name)))
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

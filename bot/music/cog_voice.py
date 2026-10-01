"""
cog_voice.py — Mixin `VoiceLifecycleMixin`: quản lý vòng đời voice của cog nhạc.

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Chỉ gồm các **method thuần**
(không decorator) nên có thể đặt trong mixin mà không ảnh hưởng tới
`commands.CogMeta`:

`CogMeta` chỉ đăng ký command / task loop / listener được khai báo TRỰC TIẾP trong
namespace của class cog, nên mọi `@app_commands.command`, `@tasks.loop`,
`on_voice_state_update` BẮT BUỘC phải nằm trong `bot/cogs/music.py`. Các helper
thuần như ở đây thì an toàn khi đưa ra mixin.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from database import async_get_guild_settings
from i18n import tr

from .config import MAX_PLAYERS
from .player import MusicPlayer

log = logging.getLogger("BotV2.Music")


class VoiceLifecycleMixin:
    """Helper vòng đời voice: hàng đợi player, task grace/reconnect, tự rời phòng."""

    # ── Helpers ────────────────────────────────────────────────────────────
    def _get(self, guild_id: int) -> MusicPlayer | None:
        return self._players.get(guild_id)


    def _drop(self, guild_id: int):
        self._cancel_reconnect_task(guild_id)
        self._cancel_grace_task(guild_id)
        self._cancel_empty_voice_task(guild_id)
        player = self._players.pop(guild_id, None)
        if player:
            player._is_reconnecting = False
            try:
                loop = getattr(self.bot, "loop", None)
                if loop and loop.is_running():
                    asyncio.create_task(player.stop())
            except Exception:
                pass


    def _cleanup_stale_tasks(self):
        """Dọn dẹp triệt để các task đã hoàn thành để chống rò rỉ RAM trên Termux ARM64."""
        for gid in list(self._reconnect_tasks.keys()):
            t = self._reconnect_tasks.get(gid)
            if not t or t.done():
                self._reconnect_tasks.pop(gid, None)
        for gid in list(self._grace_tasks.keys()):
            t = self._grace_tasks.get(gid)
            if not t or t.done():
                self._grace_tasks.pop(gid, None)
        for gid in list(self._empty_voice_tasks.keys()):
            t = self._empty_voice_tasks.get(gid)
            if not t or t.done():
                self._empty_voice_tasks.pop(gid, None)


    def _cancel_grace_task(self, guild_id: int):
        task = self._grace_tasks.pop(guild_id, None)
        if task and not task.done():
            try:
                loop = getattr(self.bot, "loop", None)
                if loop and loop.is_running():
                    try:
                        cur_loop = asyncio.get_running_loop()
                        if cur_loop == loop:
                            task.cancel()
                        else:
                            loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception:
                pass


    def _cancel_reconnect_task(self, guild_id: int):
        task = self._reconnect_tasks.pop(guild_id, None)
        if task and not task.done():
            try:
                loop = getattr(self.bot, "loop", None)
                if loop and loop.is_running():
                    try:
                        cur_loop = asyncio.get_running_loop()
                        if cur_loop == loop:
                            task.cancel()
                        else:
                            loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception:
                pass
        player = self._players.get(guild_id)
        if player:
            player.set_reconnecting(False)


    def _schedule_reconnect_task(self, guild_id: int, player: MusicPlayer):
        """Khởi tạo và quản lý vòng đời của reconnect task an toàn với timeout 30s chống rò rỉ bộ nhớ."""
        self._cancel_reconnect_task(guild_id)
        try:
            async def _safe_resume_wrapper():
                try:
                    await asyncio.wait_for(player.resume_after_reconnect(), timeout=30.0)
                except asyncio.TimeoutError:
                    log.warning(f"[Music] Reconnect task bị timeout sau 30s tại guild {guild_id}")
                    player.set_reconnecting(False)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    log.error(f"[Music] Lỗi trong reconnect task tại guild {guild_id}: {e}")
                    player.set_reconnecting(False)

            rec_task = asyncio.create_task(_safe_resume_wrapper())
            self._reconnect_tasks[guild_id] = rec_task
            rec_task.add_done_callback(lambda t, gid=guild_id: self._reconnect_tasks.pop(gid, None))
        except Exception as e:
            log.error(f"[Music] Không thể tạo reconnect task tại guild {guild_id}: {e}")
            player.set_reconnecting(False)


    def _cancel_empty_voice_task(self, guild_id: int):
        task = self._empty_voice_tasks.pop(guild_id, None)
        if task and not task.done():
            try:
                loop = getattr(self.bot, "loop", None)
                if loop and loop.is_running():
                    try:
                        cur_loop = asyncio.get_running_loop()
                        if cur_loop == loop:
                            task.cancel()
                        else:
                            loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception:
                pass


    async def _ensure(self, ctx: commands.Context) -> MusicPlayer | None:
        _t0 = time.time()
        s = await async_get_guild_settings(str(ctx.guild.id))
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(tr(s, "music.join_voice_first"))
            return None

        guild_id = ctx.guild.id
        player   = self._players.get(guild_id)
        g_vc     = ctx.guild.voice_client

        # Trường hợp 1: Player đang sống và vc đang kết nối
        if player and player.vc and player.vc.is_connected():
            if player.vc.channel != ctx.author.voice.channel:
                await ctx.send(tr(s, "music.bot_in_other_voice"))
                return None
            player.text_channel = ctx.channel
            # Đảm bảo bot luôn tự động tắt nghe (self_deaf)
            if ctx.guild.me.voice and not ctx.guild.me.voice.self_deaf:
                try:
                    await ctx.guild.change_voice_state(channel=player.vc.channel, self_deaf=True)
                except Exception:
                    pass
            return player

        # Trường hợp 2: Desync recovery — discord.py voice_client đã kết nối nhưng player bị mất
        if g_vc and g_vc.is_connected():
            log.info(f"[Music] Phát hiện voice_client đã kết nối tại guild {guild_id}, tự động đồng bộ lại player.")
            if g_vc.channel != ctx.author.voice.channel:
                try:
                    await g_vc.move_to(ctx.author.voice.channel)
                except Exception:
                    await ctx.send(tr(s, "music.bot_in_other_voice"))
                    return None
            if player:
                player.vc = g_vc
                player.text_channel = ctx.channel
            else:
                player = MusicPlayer(ctx.guild, ctx.channel, g_vc, cog=self)
                self._players[guild_id] = player
            if ctx.guild.me.voice and not ctx.guild.me.voice.self_deaf:
                try:
                    await ctx.guild.change_voice_state(channel=g_vc.channel, self_deaf=True)
                except Exception:
                    pass
            return player

        # Kiểm tra giới hạn số player đồng thời
        if guild_id not in self._players and len(self._players) >= MAX_PLAYERS:
            await ctx.send(
                tr(s, "music.max_players_err", max=MAX_PLAYERS),
                ephemeral=True,
            )
            return None

        try:
            vc = await ctx.author.voice.channel.connect(self_deaf=True)
        except Exception as e:
            if "already connected" in str(e).lower() and ctx.guild.voice_client:
                vc = ctx.guild.voice_client
            else:
                await ctx.send(tr(s, "music.cannot_connect", err=e))
                return None

        log.info(f"[Music][timing] voice connected in {time.time() - _t0:.2f}s")
        player = MusicPlayer(ctx.guild, ctx.channel, vc, cog=self)
        self._players[guild_id] = player
        return player


    def _check_and_schedule_empty_voice(self, guild: discord.Guild):
        """Kiểm tra kênh voice của bot, nếu không còn ai ngoài bot thì lên lịch tự động out sau 30s."""
        guild_id = guild.id
        vc = guild.voice_client
        bot_channel = vc.channel if (vc and vc.is_connected()) else (guild.me.voice.channel if (guild.me and guild.me.voice) else None)

        if not bot_channel:
            # Bot không ở trong kênh voice nào, hủy task đếm ngược nếu có
            task = self._empty_voice_tasks.pop(guild_id, None)
            if task and not task.done():
                task.cancel()
            return

        # Kiểm tra xem có người thật (không phải bot) trong kênh của bot không
        has_human = any(not m.bot for m in bot_channel.members)

        if has_human:
            # Có người trong phòng -> Hủy bộ đếm 30s nếu đang chạy
            task = self._empty_voice_tasks.pop(guild_id, None)
            if task and not task.done():
                task.cancel()
                log.debug(f"[Music] Người dùng đã vào lại phòng '{bot_channel.name}' tại guild {guild_id}. Đã hủy timer 30s.")
            return

        # Phòng không có người nào ngoài bot -> Khởi động bộ đếm 30s tự động rời phòng
        existing_task = self._empty_voice_tasks.get(guild_id)
        if existing_task and not existing_task.done():
            return  # Đã có timer 30s đang đếm ngược

        log.info(f"[Music] Kênh voice '{bot_channel.name}' không còn ai (guild {guild_id}). Bắt đầu đếm ngược 30s tự động out.")
        task = asyncio.create_task(self._handle_empty_voice(guild_id, bot_channel.id))
        self._empty_voice_tasks[guild_id] = task


    async def _handle_empty_voice(self, guild_id: int, channel_id: int):
        """Xử lý rời kênh khi phòng voice trống sau 30 giây (không block event loop)."""
        try:
            await asyncio.sleep(30)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            vc = guild.voice_client
            bot_channel = vc.channel if (vc and vc.is_connected()) else (guild.me.voice.channel if (guild.me and guild.me.voice) else None)

            # Nếu bot không còn ở trong kênh ban đầu hoặc đã rời
            if not bot_channel or bot_channel.id != channel_id:
                return

            # Kiểm tra lần cuối xem có người nào vào lại không
            if any(not m.bot for m in bot_channel.members):
                return

            player = self._players.get(guild_id)
            log.info(f"[Music] Phòng voice '{bot_channel.name}' đã trống 30s tại guild {guild_id}. Bot tự động rời kênh.")

            # Gửi thông báo nếu có kênh text
            channel_to_notify = player.text_channel if player else None
            if channel_to_notify:
                try:
                    s = await async_get_guild_settings(str(guild_id))
                    await channel_to_notify.send(tr(s, "music.empty_voice_left"), delete_after=60)
                except Exception:
                    pass

            # Dừng và rời kênh an toàn
            if player:
                await player.stop()
                self._drop(guild_id)
            elif vc and vc.is_connected():
                try:
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            elif guild.me and guild.me.voice and guild.me.voice.channel:
                try:
                    await guild.change_voice_state(channel=None)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"[Music] empty voice handler error: {e}")
        finally:
            self._empty_voice_tasks.pop(guild_id, None)


    async def _handle_voice_disconnect_grace(self, guild_id: int):
        """Grace Period 6s: chờ discord.py reconnect voice websocket trước khi quyết định dọn dẹp player."""
        player = self._players.get(guild_id)
        try:
            await asyncio.sleep(6)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                if player:
                    player.set_reconnecting(False)
                return

            vc = guild.voice_client
            me = getattr(guild, "me", None)
            me_voice = getattr(me, "voice", None) if me else None
            bot_channel = vc.channel if (vc and vc.is_connected()) else (me_voice.channel if me_voice else None)

            # Nếu sau 6s bot không còn ở trong bất kỳ kênh voice nào -> Xác nhận bot đã thực sự bị kick / disconnect
            if not bot_channel:
                log.info(f"[Music] Hết 6s Grace Period, bot không còn ở trong kênh voice nào tại guild {guild_id}. Dọn dẹp player.")
                if player:
                    player.set_reconnecting(False)
                self._drop(guild_id)
            else:
                log.info(f"[Music] Bot vẫn duy trì/tái kết nối tại guild {guild_id} ({bot_channel.name}).")
                active_player = self._players.get(guild_id)
                if active_player and active_player.current and not (vc and (vc.is_playing() or vc.is_paused())):
                    self._schedule_reconnect_task(guild_id, active_player)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"[Music] Lỗi trong _handle_voice_disconnect_grace: {e}")
            if player:
                player.set_reconnecting(False)
            self._cancel_reconnect_task(guild_id)
            self._cancel_grace_task(guild_id)

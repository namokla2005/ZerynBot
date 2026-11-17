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
import taskbag

from .config import INACTIVITY_TIMEOUT, MAX_PLAYERS
from .player import MusicPlayer

log = logging.getLogger("BotV2.Music")


class VoiceLifecycleMixin:
    """Helper vòng đời voice: hàng đợi player, task grace/reconnect, tự rời phòng."""

    # ── Helpers ────────────────────────────────────────────────────────────
    def _get(self, guild_id: int) -> MusicPlayer | None:
        return self._players.get(guild_id)


    def _drop(self, guild_id: int, expected_player: MusicPlayer | None = None):
        if expected_player is not None and self._players.get(guild_id) is not expected_player:
            return
        self._cancel_reconnect_task(guild_id)
        self._cancel_grace_task(guild_id)
        self._cancel_empty_voice_task(guild_id)
        player = self._players.pop(guild_id, None)
        if player:
            player._is_reconnecting = False
            if not getattr(player, "_cleanup_done", False) and not getattr(player, "_is_stopping", False):
                try:
                    loop = getattr(self.bot, "loop", None)
                    if loop and loop.is_running():
                        taskbag.spawn(player.stop())
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


    @staticmethod
    def _discard_voice_task(tasks: dict, guild_id: int, task: asyncio.Task):
        """A completed generation may only remove its own registry entry."""
        if tasks.get(guild_id) is task:
            tasks.pop(guild_id, None)


    def _cancel_voice_task(self, task: asyncio.Task | None):
        if not task or task.done():
            return
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        # Grace handlers can run inside wait_for's child task. Cancelling their
        # wrapper also cancels that child, interrupting stop() at its next await.
        if task is current or task is getattr(current, "_music_voice_owner", None):
            return
        try:
            loop = task.get_loop()
            try:
                on_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                on_loop = False
            if loop.is_running() and not on_loop:
                loop.call_soon_threadsafe(task.cancel)
            else:
                task.cancel()
        except Exception:
            pass


    def _cancel_grace_task(self, guild_id: int):
        self._cancel_voice_task(self._grace_tasks.pop(guild_id, None))


    def _cancel_reconnect_task(
        self, guild_id: int, clear_flag: bool = True,
        expected_player: MusicPlayer | None = None,
    ):
        player = self._players.get(guild_id)
        if expected_player is not None and player is not expected_player:
            return
        self._cancel_voice_task(self._reconnect_tasks.pop(guild_id, None))
        if player and clear_flag:
            player.set_reconnecting(False)


    def _schedule_reconnect_task(self, guild_id: int, player: MusicPlayer):
        """Coalesce duplicate voice events; only the owning task clears state."""
        if self._players.get(guild_id) is not player:
            return
        existing = self._reconnect_tasks.get(guild_id)
        if (existing and not existing.done()
                and not getattr(existing, "cancelling", lambda: 0)()
                and getattr(existing, "_music_player", None) is player):
            return
        self._cancel_reconnect_task(guild_id, clear_flag=False)
        player.set_reconnecting(True)

        async def _safe_resume_wrapper():
            task = asyncio.current_task()
            # Await directly so stop() executes in the registered task, not a
            # wait_for child whose parent cancellation would interrupt cleanup.
            def expire():
                log.warning(f"[Music] Reconnect task bị timeout sau 30s tại guild {guild_id}")
                task.cancel()

            timeout = asyncio.get_running_loop().call_later(30.0, expire)
            try:
                await player.resume_after_reconnect()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"[Music] Lỗi trong reconnect task tại guild {guild_id}: {e}")
            finally:
                timeout.cancel()
                if self._reconnect_tasks.get(guild_id) is task:
                    if self._players.get(guild_id) is player:
                        player.set_reconnecting(False)
                    self._discard_voice_task(self._reconnect_tasks, guild_id, task)

        wrapper = _safe_resume_wrapper()
        try:
            rec_task = asyncio.create_task(wrapper)
            rec_task._music_player = player
            self._reconnect_tasks[guild_id] = rec_task
            rec_task.add_done_callback(
                lambda t: self._discard_voice_task(self._reconnect_tasks, guild_id, t)
            )
        except Exception as e:
            wrapper.close()
            log.error(f"[Music] Không thể tạo reconnect task tại guild {guild_id}: {e}")
            player.set_reconnecting(False)


    def _cancel_empty_voice_task(self, guild_id: int):
        self._cancel_voice_task(self._empty_voice_tasks.pop(guild_id, None))


    _JOIN_DRAIN_TIMEOUT = 5.0
    _JOIN_DISCONNECT_TIMEOUT = 3.0

    def _join_is_current(self):
        if getattr(self, "_unloading", False):
            return False
        get_cog = getattr(self.bot, "get_cog", None)
        active_cog = get_cog("Music") if get_cog else None
        return active_cog is None or active_cog is self

    async def _disconnect_abandoned_join(self, guild, vc):
        # disconnect() sends a guild-wide voice-state update and removes the
        # registered voice client. Never call it after another owner adopts VC.
        if vc is None or guild.voice_client is not vc:
            return
        owner = self._players.get(guild.id)
        if owner is not None and owner.vc is vc:
            return
        get_cog = getattr(self.bot, "get_cog", None)
        active_cog = get_cog("Music") if get_cog else None
        if active_cog is not None and active_cog is not self:
            owner = active_cog._get(guild.id)
            if owner is not None and owner.vc is vc:
                return
        try:
            await asyncio.wait_for(vc.disconnect(force=True), self._JOIN_DISCONNECT_TIMEOUT)
        except Exception as exc:
            log.warning("[Music] Abandoned join cleanup failed: %s", type(exc).__name__)

    async def _ensure(self, ctx: commands.Context) -> MusicPlayer | None:
        if not self._join_is_current():
            return None
        if not hasattr(self, "_join_tasks"):
            self._join_tasks = set()
        task = asyncio.current_task()
        self._join_tasks.add(task)
        try:
            return await self._ensure_voice(ctx)
        finally:
            self._join_tasks.discard(task)

    async def _ensure_voice(self, ctx: commands.Context) -> MusicPlayer | None:
        _t0 = time.time()
        guild_id = ctx.guild.id
        s = await async_get_guild_settings(str(guild_id))
        if not self._join_is_current():
            return None
        lock = self._player_locks.setdefault(guild_id, asyncio.Lock())

        # Channel checks and desync adoption belong under the same lock as join.
        # A waiting requester must not inherit another room's freshly made player.
        async with lock:
            if not self._join_is_current():
                return None
            voice = ctx.author.voice
            if not voice or not voice.channel:
                await ctx.send(tr(s, "music.join_voice_first"))
                return None
            player = self._players.get(guild_id)
            vc = player.vc if player and player.vc and player.vc.is_connected() else ctx.guild.voice_client
            if vc and vc.is_connected() and getattr(vc, "channel", None) != voice.channel:
                await ctx.send(tr(s, "music.bot_in_other_voice"))
                return None

            reserved = False
            if player is None:
                # Connected-but-unregistered clients consume a slot too. Reserve
                # globally before any await so concurrent guilds cannot exceed 6.
                async with self._registry_lock:
                    if not self._join_is_current():
                        return None
                    over_limit = (len(self._players) + len(self._connecting)) >= MAX_PLAYERS
                    if not over_limit:
                        self._connecting.add(guild_id)
                        reserved = True
                if over_limit:
                    await ctx.send(tr(s, "music.max_players_err", max=MAX_PLAYERS), ephemeral=True)
                    return None

            joining_vc = None
            try:
                # Registry lock acquisition can yield; never connect using a
                # VoiceState or voice client captured before that await.
                if not self._join_is_current() or self._players.get(guild_id) is not player:
                    return None
                voice = ctx.author.voice
                if not voice or not voice.channel:
                    await ctx.send(tr(s, "music.join_voice_first"))
                    return None
                vc = player.vc if player and player.vc and player.vc.is_connected() else ctx.guild.voice_client
                if vc and vc.is_connected():
                    if getattr(vc, "channel", None) != voice.channel:
                        await ctx.send(tr(s, "music.bot_in_other_voice"))
                        return None
                else:
                    def make_voice_client(client, channel):
                        nonlocal joining_vc
                        # discord.py registers this object BEFORE awaiting the
                        # handshake. Retain exact ownership even if it raises.
                        joining_vc = discord.VoiceClient(client, channel)
                        return joining_vc

                    try:
                        vc = await voice.channel.connect(self_deaf=True, cls=make_voice_client)
                        joining_vc = vc
                    except Exception as e:
                        if not self._join_is_current():
                            return None
                        vc = ctx.guild.voice_client
                        if not ("already connected" in str(e).lower() and vc and vc.is_connected()):
                            await ctx.send(tr(s, "music.cannot_connect", err=e))
                            return None
                    # Joining can race a requester leaving or moving. Keep the
                    # new idle connection tracked for cleanup, but reject play.
                    log.info(f"[Music][timing] voice connected in {time.time() - _t0:.2f}s")

                if not self._join_is_current() or self._players.get(guild_id) is not player:
                    return None
                if player is None:
                    player = MusicPlayer(ctx.guild, ctx.channel, vc, cog=self)
                    self._players[guild_id] = player
                else:
                    player.vc = vc
                joining_vc = None  # Ownership transferred synchronously to player.
                # Commit the reservation synchronously with registration. The
                # self-deaf API below can yield and must not count this guild twice.
                if reserved:
                    self._connecting.discard(guild_id)
                    reserved = False
                if not player.current and not player.queue:
                    player._start_inactivity_timer()

                voice = ctx.author.voice
                if not voice or not voice.channel:
                    await ctx.send(tr(s, "music.join_voice_first"))
                    return None
                if getattr(vc, "channel", None) != voice.channel:
                    await ctx.send(tr(s, "music.bot_in_other_voice"))
                    return None
                me_voice = getattr(ctx.guild.me, "voice", None)
                if me_voice and not me_voice.self_deaf:
                    try:
                        await ctx.guild.change_voice_state(channel=vc.channel, self_deaf=True)
                    except Exception:
                        pass
                    if not self._join_is_current() or self._players.get(guild_id) is not player:
                        return None
                    voice = ctx.author.voice
                    if not voice or not voice.channel:
                        await ctx.send(tr(s, "music.join_voice_first"))
                        return None
                    if getattr(vc, "channel", None) != voice.channel:
                        await ctx.send(tr(s, "music.bot_in_other_voice"))
                        return None
                player.text_channel = ctx.channel
                return player
            finally:
                if reserved:
                    self._connecting.discard(guild_id)
                if joining_vc is not None:
                    await self._disconnect_abandoned_join(ctx.guild, joining_vc)


    def _check_and_schedule_empty_voice(self, guild: discord.Guild):
        """Kiểm tra kênh voice của bot, nếu không còn ai nghe nhạc (trống hoặc tất cả đều deafen) thì đếm INACTIVITY_TIMEOUT (180s) tự động rời kênh."""
        if not guild or getattr(guild, "unavailable", False) or not self.bot.get_guild(guild.id):
            return

        guild_id = guild.id
        vc = guild.voice_client
        bot_channel = vc.channel if (vc and vc.is_connected()) else (guild.me.voice.channel if (guild.me and guild.me.voice) else None)

        if not bot_channel:
            # Bot không ở trong kênh voice nào, hủy task đếm ngược nếu có
            self._cancel_empty_voice_task(guild_id)
            return

        # Kiểm tra xem có người đang nghe nhạc không (người thật và KHÔNG tắt tai nghe / deafen)
        has_listener = any(
            not m.bot and not (m.voice and (m.voice.self_deaf or m.voice.deaf))
            for m in bot_channel.members
        )

        if has_listener:
            # Có người đang nghe nhạc trong phòng -> Hủy bộ đếm nếu đang chạy
            self._cancel_empty_voice_task(guild_id)
            return

        # Phòng không có ai nghe nhạc -> Khởi động bộ đếm INACTIVITY_TIMEOUT (180s) tự động rời phòng
        existing_task = self._empty_voice_tasks.get(guild_id)
        if existing_task:
            if not existing_task.done():
                return  # Đã có timer đang đếm ngược
            self._empty_voice_tasks.pop(guild_id, None)

        log.info(f"[Music] Kênh voice '{bot_channel.name}' không còn ai nghe nhạc (guild {guild_id}). Bắt đầu đếm ngược {INACTIVITY_TIMEOUT}s tự động out.")
        task = asyncio.create_task(self._handle_empty_voice(guild_id, bot_channel.id))
        self._empty_voice_tasks[guild_id] = task
        task.add_done_callback(
            lambda t: self._discard_voice_task(self._empty_voice_tasks, guild_id, t)
        )


    async def _handle_empty_voice(self, guild_id: int, channel_id: int):
        """Xử lý rời kênh khi phòng voice trống hoặc không ai nghe sau INACTIVITY_TIMEOUT (180s = 3 phút).
        Dùng time.monotonic() chống clock drift trên Helio G85 và kiểm tra heartbeat mỗi 15s."""
        try:
            start_t = time.monotonic()
            timeout = max(30, INACTIVITY_TIMEOUT)
            while (time.monotonic() - start_t) < timeout:
                await asyncio.sleep(min(15.0, timeout - (time.monotonic() - start_t)))
                guild = getattr(self.bot, "get_guild", lambda _: None)(guild_id)
                if not guild or getattr(guild, "unavailable", False):
                    return
                vc = getattr(guild, "voice_client", None)
                me = getattr(guild, "me", None)
                me_voice = getattr(me, "voice", None) if me else None
                bot_channel = (
                    getattr(vc, "channel", None)
                    if (vc and getattr(vc, "is_connected", lambda: False)())
                    else (getattr(me_voice, "channel", None) if me_voice else None)
                )
                if not bot_channel or getattr(bot_channel, "id", None) != channel_id:
                    return
                # Heartbeat: nếu có người nghe quay trở lại hoặc undeafen -> dừng đếm
                members = getattr(bot_channel, "members", [])
                if any(
                    not getattr(m, "bot", True)
                    and not (getattr(m, "voice", None) and (getattr(m.voice, "self_deaf", False) or getattr(m.voice, "deaf", False)))
                    for m in members
                ):
                    return

            guild = getattr(self.bot, "get_guild", lambda _: None)(guild_id)
            if not guild or getattr(guild, "unavailable", False):
                return
            vc = getattr(guild, "voice_client", None)
            me = getattr(guild, "me", None)
            me_voice = getattr(me, "voice", None) if me else None
            bot_channel = (
                getattr(vc, "channel", None)
                if (vc and getattr(vc, "is_connected", lambda: False)())
                else (getattr(me_voice, "channel", None) if me_voice else None)
            )

            # Nếu bot không còn ở trong kênh ban đầu hoặc đã rời
            if not bot_channel or getattr(bot_channel, "id", None) != channel_id:
                return

            # Kiểm tra lần cuối xem có người nghe nào không
            members = getattr(bot_channel, "members", [])
            if any(
                not getattr(m, "bot", True)
                and not (getattr(m, "voice", None) and (getattr(m.voice, "self_deaf", False) or getattr(m.voice, "deaf", False)))
                for m in members
            ):
                return

            player = self._players.get(guild_id)
            if player and getattr(player, "_cleanup_done", False):
                return

            ch_name = getattr(bot_channel, "name", "Voice")
            log.info(f"[Music] Phòng voice '{ch_name}' đã trống {int(timeout)}s tại guild {guild_id}. Bot tự động rời kênh.")

            # Gửi thông báo nếu có kênh text
            channel_to_notify = player.text_channel if player else None
            if channel_to_notify:
                try:
                    s = await async_get_guild_settings(str(guild_id))
                    await channel_to_notify.send(tr(s, "music.empty_voice_left"), delete_after=60)
                except Exception as send_err:
                    log.debug(f"[Music] send empty_voice_left error: {send_err}")

            # Dừng và rời kênh an toàn
            if player:
                try:
                    await player.stop()
                except Exception as stop_err:
                    log.error(f"[Music] player.stop in empty_voice error: {stop_err}")
                self._drop(guild_id, expected_player=player)
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
            log.error(f"[Music] empty voice handler error: {e}", exc_info=e)
        finally:
            self._discard_voice_task(self._empty_voice_tasks, guild_id, asyncio.current_task())


    async def _handle_voice_disconnect_grace(self, guild_id: int):
        """Grace Period 6s: chờ discord.py reconnect voice websocket trước khi quyết định dọn dẹp player."""
        player = self._players.get(guild_id)
        task = asyncio.current_task()
        owner = self._grace_tasks.get(guild_id)
        task._music_voice_owner = owner
        try:
            await asyncio.sleep(6)
            if ((owner is not None and self._grace_tasks.get(guild_id) is not owner)
                    or self._players.get(guild_id) is not player):
                return
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
                self._drop(guild_id, expected_player=player)
            else:
                log.info(f"[Music] Bot vẫn duy trì/tái kết nối tại guild {guild_id} ({bot_channel.name}).")
                active_player = self._players.get(guild_id)
                if active_player and active_player.current and not (vc and (vc.is_playing() or vc.is_paused())):
                    self._schedule_reconnect_task(guild_id, active_player)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"[Music] Lỗi trong _handle_voice_disconnect_grace: {e}")
            if ((owner is None or self._grace_tasks.get(guild_id) is owner)
                    and self._players.get(guild_id) is player):
                self._cancel_reconnect_task(guild_id, expected_player=player)
                self._cancel_grace_task(guild_id)

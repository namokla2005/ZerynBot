"""Offline regressions for voice task ownership and serialized channel joins."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from music import cog_voice as cv


class VoiceClient:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.moves = []

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return False

    def is_paused(self):
        return False

    async def disconnect(self, **kwargs):
        await asyncio.sleep(0)
        self.connected = False

    async def move_to(self, channel):
        self.moves.append(channel)
        self.channel = channel


class Player:
    def __init__(self, guild=None, text_channel=None, vc=None, cog=None):
        self.guild, self.text_channel, self.vc, self.cog = guild, text_channel, vc, cog
        self._is_reconnecting = False
        self._cleanup_done = False
        self.current = None
        self.queue = []
        self.resumed = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.inactivity_started = False

    def set_reconnecting(self, value):
        self._is_reconnecting = value

    async def resume_after_reconnect(self):
        self.resumed += 1
        self.started.set()
        await self.release.wait()

    def _start_inactivity_timer(self):
        self.inactivity_started = True

    async def stop(self):
        self._cleanup_done = True
        self.cog._cancel_reconnect_task(self.guild.id)
        self.cog._drop(self.guild.id)
        await self.vc.disconnect(force=True)


def cog_for(guild=None):
    cog = cv.VoiceLifecycleMixin()
    cog._players = {}
    cog._reconnect_tasks = {}
    cog._grace_tasks = {}
    cog._empty_voice_tasks = {}
    cog._player_locks = {}
    cog._registry_lock = asyncio.Lock()
    cog._connecting = set()
    cog.bot = NS(loop=asyncio.get_running_loop(), get_guild=lambda gid: guild)
    return cog


def context(guild, room):
    sent = []

    async def send(message, **kwargs):
        sent.append(message)

    return NS(guild=guild, author=NS(voice=NS(channel=room)), channel=object(), send=send, sent=sent)


def room_for(guild, room_id, entered=None, release=None):
    room = NS(id=room_id, name=str(room_id), members=[], connects=0)

    async def connect(**kwargs):
        room.connects += 1
        if entered:
            entered.set()
        if release:
            await release.wait()
        vc = VoiceClient(room)
        guild.voice_client = vc
        return vc

    room.connect = connect
    return room


@pytest.fixture
def offline(monkeypatch):
    async def settings(_):
        return {"language": "en"}

    monkeypatch.setattr(cv, "async_get_guild_settings", settings)
    monkeypatch.setattr(cv, "tr", lambda settings, key, **kwargs: key)
    monkeypatch.setattr(cv, "MusicPlayer", Player)


def test_duplicate_resume_events_coalesce_even_for_mute_deaf_updates():
    async def run():
        cog = cog_for()
        player = Player()
        cog._players[7] = player
        cog._schedule_reconnect_task(7, player)
        first = cog._reconnect_tasks[7]
        await player.started.wait()
        try:
            # Join, mute, self-deaf and server-deaf callbacks reach this same boundary.
            for _ in range(3):
                cog._schedule_reconnect_task(7, player)
                assert cog._reconnect_tasks[7] is first
            assert player.resumed == 1
        finally:
            player.release.set()
            await asyncio.gather(first, *cog._reconnect_tasks.values())

    asyncio.run(run())


def test_cancelled_old_reconnect_cannot_clear_replacement_flag_or_registry():
    async def run():
        cog = cog_for()
        player = Player()
        cog._players[7] = player
        cog._schedule_reconnect_task(7, player)
        old = cog._reconnect_tasks[7]
        await player.started.wait()
        cog._cancel_reconnect_task(7, clear_flag=False)
        cog._schedule_reconnect_task(7, player)
        replacement = cog._reconnect_tasks[7]
        try:
            await old
            await asyncio.sleep(0)
            assert cog._reconnect_tasks.get(7) is replacement
            assert player._is_reconnecting is True
        finally:
            player.release.set()
            await replacement
        assert player._is_reconnecting is False

    asyncio.run(run())


def test_real_player_cancelled_resume_cannot_clear_replacement_state():
    from music.player import MusicPlayer

    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)
        vc = guild.voice_client = VoiceClient(room)
        vc.client = NS(loop=asyncio.get_running_loop())
        cog = cog_for(guild)
        player = MusicPlayer(guild, None, vc, cog=cog)
        cog._players[7] = player
        cog._schedule_reconnect_task(7, player)
        old = cog._reconnect_tasks[7]
        await asyncio.sleep(0)  # real resume is now in its stabilization sleep
        assert player._recovering
        cog._cancel_reconnect_task(7, clear_flag=False)
        cog._schedule_reconnect_task(7, player)
        replacement = cog._reconnect_tasks[7]
        try:
            await old
            await asyncio.sleep(0)
            assert player._is_reconnecting, "old MusicPlayer finally cleared the new generation"
            assert cog._reconnect_tasks.get(7) is replacement
        finally:
            cog._cancel_reconnect_task(7)
            await replacement

    asyncio.run(run())


@pytest.mark.parametrize("clear_flag", [False, True])
def test_explicit_reconnect_cancel_preserves_clear_flag(clear_flag):
    async def run():
        cog = cog_for()
        player = Player()
        cog._players[7] = player
        cog._schedule_reconnect_task(7, player)
        task = cog._reconnect_tasks[7]
        await player.started.wait()
        cog._cancel_reconnect_task(7, clear_flag=clear_flag)
        await task
        assert player._is_reconnecting is (not clear_flag)
        assert 7 not in cog._reconnect_tasks

    asyncio.run(run())


@pytest.mark.parametrize("registry,cancel", [
    ("_grace_tasks", "_cancel_grace_task"),
    ("_reconnect_tasks", "_cancel_reconnect_task"),
    ("_empty_voice_tasks", "_cancel_empty_voice_task"),
])
def test_cancel_helpers_do_not_cancel_the_running_cleanup(registry, cancel):
    async def run():
        cog = cog_for()
        completed = []

        async def cleanup():
            getattr(cog, registry)[7] = asyncio.current_task()
            getattr(cog, cancel)(7)
            await asyncio.sleep(0)
            completed.append(True)

        task = asyncio.create_task(cleanup())
        await asyncio.gather(task, return_exceptions=True)
        assert completed == [True]
        assert not task.cancelled()
        assert 7 not in getattr(cog, registry)

    asyncio.run(run())


def test_reconnect_stop_completes_without_cancelling_its_wrapper():
    async def run():
        guild = NS(id=7, voice_client=None)
        room = room_for(guild, 10)
        vc = VoiceClient(room)
        cog = cog_for(guild)
        player = Player(guild, None, vc, cog)
        cog._players[7] = player

        async def resume_and_stop():
            await player.stop()

        player.resume_after_reconnect = resume_and_stop
        cog._schedule_reconnect_task(7, player)
        await cog._reconnect_tasks[7]
        assert vc.connected is False
        assert 7 not in cog._players

    asyncio.run(run())


def test_empty_voice_finally_and_callback_preserve_new_timer():
    async def run():
        listener = NS(bot=False, voice=NS(self_deaf=True, deaf=False))
        guild = NS(id=7, unavailable=False, me=NS(voice=None))
        room = room_for(guild, 10)
        room.members = [listener]
        guild.voice_client = VoiceClient(room)
        cog = cog_for(guild)
        cog._check_and_schedule_empty_voice(guild)
        old = cog._empty_voice_tasks[7]
        await asyncio.sleep(0)
        # Undeafen cancels, then deafen immediately schedules a new timer.
        listener.voice.self_deaf = False
        cog._check_and_schedule_empty_voice(guild)
        listener.voice.self_deaf = True
        cog._check_and_schedule_empty_voice(guild)
        replacement = cog._empty_voice_tasks[7]
        try:
            await old
            await asyncio.sleep(0)
            assert cog._empty_voice_tasks.get(7) is replacement
        finally:
            replacement.cancel()
            await replacement

    asyncio.run(run())


def test_drop_with_old_owner_leaves_replacement_and_tasks_untouched():
    async def run():
        cog = cog_for()
        old, replacement = Player(), Player()
        cog._players[7] = replacement
        task = asyncio.create_task(asyncio.sleep(60))
        cog._reconnect_tasks[7] = task
        try:
            cog._drop(7, expected_player=old)
            assert cog._players[7] is replacement
            assert cog._reconnect_tasks[7] is task
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_competing_first_joins_from_different_rooms_are_rejected(offline):
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        entered, release = asyncio.Event(), asyncio.Event()
        first_room = room_for(guild, 10, entered, release)
        second_room = room_for(guild, 20)
        cog = cog_for(guild)
        first_ctx, second_ctx = context(guild, first_room), context(guild, second_room)
        first = asyncio.create_task(cog._ensure(first_ctx))
        await entered.wait()
        second = asyncio.create_task(cog._ensure(second_ctx))
        await asyncio.sleep(0)
        release.set()
        first_player, second_player = await asyncio.gather(first, second)
        assert first_player is cog._players[7]
        assert second_player is None
        assert second_ctx.sent == ["music.bot_in_other_voice"]
        assert first_player.text_channel is first_ctx.channel
        assert second_room.connects == 0

    asyncio.run(run())


def test_desync_recovery_cannot_move_bot_to_foreign_requester(offline):
    async def run():
        guild = NS(id=7, me=NS(voice=None))
        original, foreign = room_for(guild, 10), room_for(guild, 20)
        guild.voice_client = VoiceClient(original)
        cog = cog_for(guild)
        ctx = context(guild, foreign)
        assert await cog._ensure(ctx) is None
        assert guild.voice_client.channel is original
        assert guild.voice_client.moves == []
        assert not cog._players

    asyncio.run(run())


def test_desync_appearing_while_waiting_for_guild_lock_is_adopted(offline):
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)
        cog = cog_for(guild)
        lock = asyncio.Lock()
        cog._player_locks[7] = lock
        await lock.acquire()
        task = asyncio.create_task(cog._ensure(context(guild, room)))
        await asyncio.sleep(0)
        guild.voice_client = VoiceClient(room)
        lock.release()
        player = await task
        assert player.vc is guild.voice_client
        assert room.connects == 0
        assert player.inactivity_started

    asyncio.run(run())


def test_requester_leaving_while_waiting_for_guild_lock_never_connects(offline):
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)
        cog = cog_for(guild)
        lock = asyncio.Lock()
        cog._player_locks[7] = lock
        ctx = context(guild, room)
        await lock.acquire()
        task = asyncio.create_task(cog._ensure(ctx))
        await asyncio.sleep(0)
        ctx.author.voice = None
        lock.release()
        assert await task is None
        assert ctx.sent == ["music.join_voice_first"]
        assert room.connects == 0
        assert not cog._connecting

    asyncio.run(run())


def test_desync_recovery_obeys_global_player_limit(offline):
    async def run():
        guild = NS(id=7, me=NS(voice=None))
        room = room_for(guild, 10)
        guild.voice_client = VoiceClient(room)
        cog = cog_for(guild)
        cog._players = {gid: Player() for gid in range(cv.MAX_PLAYERS)}
        assert await cog._ensure(context(guild, room)) is None
        assert len(cog._players) == cv.MAX_PLAYERS
        assert not cog._connecting

    asyncio.run(run())


def test_global_join_reservations_never_exceed_six(offline):
    async def run():
        cog = cog_for()
        release = asyncio.Event()
        contexts = []
        for gid in range(8):
            guild = NS(id=gid, voice_client=None, me=NS(voice=None))
            contexts.append(context(guild, room_for(guild, gid + 10, release=release)))
        tasks = [asyncio.create_task(cog._ensure(ctx)) for ctx in contexts]
        await asyncio.sleep(0)
        assert len(cog._players) + len(cog._connecting) == cv.MAX_PLAYERS
        release.set()
        results = await asyncio.gather(*tasks)
        assert sum(player is not None for player in results) == cv.MAX_PLAYERS
        assert len(cog._players) == cv.MAX_PLAYERS
        assert not cog._connecting

    asyncio.run(run())


def test_registered_players_are_not_double_counted_during_self_deaf(offline):
    async def run():
        cog = cog_for()
        entered, release = asyncio.Event(), asyncio.Event()
        guild = NS(id=7, voice_client=None, me=NS(voice=NS(self_deaf=False)))
        room = room_for(guild, 10)

        async def self_deaf(**kwargs):
            entered.set()
            await release.wait()

        guild.change_voice_state = self_deaf
        cog._players = {gid: Player() for gid in range(cv.MAX_PLAYERS - 2)}
        first = asyncio.create_task(cog._ensure(context(guild, room)))
        await entered.wait()
        another_guild = NS(id=8, voice_client=None, me=NS(voice=None))
        try:
            second = await cog._ensure(context(another_guild, room_for(another_guild, 20)))
            assert second is not None
            assert len(cog._players) == cv.MAX_PLAYERS
        finally:
            release.set()
            await first

    asyncio.run(run())


def test_requester_leaving_during_registry_lock_wait_never_connects(offline):
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)
        cog = cog_for(guild)
        ctx = context(guild, room)
        await cog._registry_lock.acquire()
        task = asyncio.create_task(cog._ensure(ctx))
        await asyncio.sleep(0)
        ctx.author.voice = None
        cog._registry_lock.release()
        assert await task is None
        assert ctx.sent == ["music.join_voice_first"]
        assert room.connects == 0
        assert not cog._connecting

    asyncio.run(run())


@pytest.mark.parametrize("with_player", [False, True])
def test_empty_voice_timeout_finishes_disconnect_without_self_cancel(monkeypatch, with_player):
    # Advance only the mixin clock, not the event loop's monotonic clock.
    clock = iter([0.0, 1000.0])
    monkeypatch.setattr(cv, "time", NS(monotonic=lambda: next(clock)))

    async def run():
        guild = NS(id=7, unavailable=False, me=NS(voice=None))
        room = room_for(guild, 10)
        vc = guild.voice_client = VoiceClient(room)
        cog = cog_for(guild)
        if with_player:
            cog._players[7] = Player(guild, None, vc, cog)
        cog._check_and_schedule_empty_voice(guild)
        task = cog._empty_voice_tasks[7]
        await task
        assert vc.connected is False
        assert not cog._players
        assert not cog._empty_voice_tasks
        assert not task.cancelled()

    asyncio.run(run())


def test_requester_leaving_during_self_deaf_await_is_rechecked(offline):
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=NS(self_deaf=False)))
        room = room_for(guild, 10)
        ctx = context(guild, room)
        cog = cog_for(guild)

        async def self_deaf(**kwargs):
            await asyncio.sleep(0)
            ctx.author.voice = None

        guild.change_voice_state = self_deaf
        assert await cog._ensure(ctx) is None
        assert ctx.sent == ["music.join_voice_first"]
        assert cog._players[7].inactivity_started
        assert not cog._connecting

    asyncio.run(run())


def test_reconnect_timeout_keeps_cleanup_and_warning(monkeypatch, caplog):
    async def run():
        cog = cog_for()
        player = Player()
        cog._players[7] = player
        loop = asyncio.get_running_loop()
        original_call_later = loop.call_later
        callbacks = []

        def call_later(delay, callback, *args, **kwargs):
            if delay == 30.0:
                callbacks.append(callback)
            return original_call_later(delay, callback, *args, **kwargs)

        monkeypatch.setattr(loop, "call_later", call_later)
        cog._schedule_reconnect_task(7, player)
        task = cog._reconnect_tasks[7]
        await player.started.wait()
        assert len(callbacks) == 1
        callbacks[0]()  # advance the watchdog without a 30-second wall-clock wait
        await task
        assert not player._is_reconnecting
        assert not cog._reconnect_tasks
        assert "30s" in caplog.text

    asyncio.run(run())


def test_grace_wait_for_child_can_drop_without_cancelling_parent():
    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)
        vc = VoiceClient(room)
        vc.connected = False
        cog = cog_for(guild)
        player = Player(guild, None, vc, cog)
        cog._players[7] = player
        stopped = asyncio.Event()
        original_stop = player.stop

        async def stop():
            await original_stop()
            stopped.set()

        player.stop = stop

        async def grace_wrapper():
            await asyncio.wait_for(cog._handle_voice_disconnect_grace(7), timeout=15)

        task = asyncio.create_task(grace_wrapper())
        cog._grace_tasks[7] = task
        await task
        await asyncio.wait_for(stopped.wait(), timeout=1)
        assert not task.cancelled()
        assert not cog._players
        assert not cog._grace_tasks

    asyncio.run(run())


@pytest.mark.parametrize("registry", ["_grace_tasks", "_reconnect_tasks", "_empty_voice_tasks"])
def test_completion_helper_cannot_discard_replacement(registry):
    async def run():
        cog = cog_for()
        old = asyncio.create_task(asyncio.sleep(0))
        replacement = asyncio.create_task(asyncio.sleep(0))
        tasks = getattr(cog, registry)
        tasks[7] = replacement
        await old
        cog._discard_voice_task(tasks, 7, old)
        assert tasks[7] is replacement
        await replacement
        cog._discard_voice_task(tasks, 7, replacement)
        assert not tasks

    asyncio.run(run())


def test_disconnected_voice_client_is_unregistered_before_next_join():
    from music.player import MusicPlayer

    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)

        class RegisteredVoiceClient(VoiceClient):
            def __init__(self):
                super().__init__(room)
                self.connected = False
                self.source = None
                self.disconnect_calls = 0

            def stop(self):
                pass

            async def disconnect(self, **kwargs):
                self.disconnect_calls += 1
                self.connected = False
                if guild.voice_client is self:
                    guild.voice_client = None

        vc = RegisteredVoiceClient()
        guild.voice_client = vc
        cog = cog_for(guild)
        player = MusicPlayer(guild, None, vc, cog=cog)
        cog._players[guild.id] = player

        await player.stop()

        assert vc.disconnect_calls == 1
        assert guild.voice_client is None

    asyncio.run(run())


def test_stale_stop_retry_cannot_unregister_replacement_voice_client():
    from music.player import MusicPlayer

    async def run():
        guild = NS(id=7, voice_client=None, me=NS(voice=None))
        room = room_for(guild, 10)

        class StaleVoiceClient(VoiceClient):
            def __init__(self):
                super().__init__(room)
                self.connected = False
                self.source = None
                self.disconnect_calls = 0

            def stop(self):
                pass

            async def disconnect(self, **kwargs):
                self.disconnect_calls += 1
                # discord.py cleanup removes by guild key, not VC identity.
                guild.voice_client = None

        stale_vc = StaleVoiceClient()
        replacement_vc = VoiceClient(room)
        guild.voice_client = replacement_vc
        cog = cog_for(guild)
        stale_player = MusicPlayer(guild, None, stale_vc, cog=cog)
        replacement_player = Player(guild, None, replacement_vc, cog=cog)
        cog._players[guild.id] = replacement_player

        await stale_player.stop()

        assert stale_vc.disconnect_calls == 0
        assert guild.voice_client is replacement_vc
        assert cog._players[guild.id] is replacement_player

    asyncio.run(run())

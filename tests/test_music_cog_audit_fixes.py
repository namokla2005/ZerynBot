"""Offline behavior regressions for cog shutdown, admission and saved playlists."""
import asyncio
import inspect
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from discord.ext import commands

from cogs import music as m
from music import extractor


class Player:
    def __init__(self, *, busy=False):
        self.guild = NS(id=1)
        self.vc = NS(channel=object(), is_connected=lambda: True,
                     is_playing=lambda: busy, is_paused=lambda: False)
        self.current = object() if busy else None
        self.queue = []
        self._manual_stopped = False
        self._is_reconnecting = False
        self.admitted = []
        self.update_now_playing = AsyncMock()
        self.stop = AsyncMock()

    def set_reconnecting(self, value):
        self._is_reconnecting = value

    async def add_and_play(self, track, **kwargs):
        if self._manual_stopped or len(self.queue) >= m.MAX_QUEUE_SIZE:
            return False
        self.admitted.append(track)
        if self.current is not None:
            self.queue.append(track)
        else:
            self.current = track
        return True


def cog_for(player):
    cog = object.__new__(m.Music)
    cog._players = {1: player}
    cog._player_locks = {}
    cog._connecting = set()
    cog._bg_tasks = set()
    cog._empty_voice_tasks = {}
    cog._reconnect_tasks = {}
    cog._grace_tasks = {}
    cog.bot = NS(user=NS(id=9), get_guild=lambda gid: NS(id=gid))
    return cog


def context(player):
    message = NS(delete=AsyncMock(), edit=AsyncMock())
    ctx = NS(guild=NS(id=1), author=NS(id=2, mention='@requester',
             voice=NS(channel=player.vc.channel)), interaction=None,
             command=NS(name='seek'), send=AsyncMock(return_value=message), defer=AsyncMock())
    return ctx


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(m, 'async_get_guild_settings', AsyncMock(return_value={'language': 'en'}))


def stored(n):
    return {'title': f'song {n}', 'webpage_url': f'https://youtube.com/watch?v={n}',
            'duration': 120 + n, 'thumbnail': f'https://images/{n}'}


async def drain(cog):
    while cog._bg_tasks:
        await asyncio.gather(*list(cog._bg_tasks))


@pytest.mark.asyncio
async def test_unload_awaits_players_and_cancelled_tasks_when_extractor_close_raises(monkeypatch):
    player = Player()
    cog = cog_for(player)
    finalized = asyncio.Event()

    async def background():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            finalized.set()

    task = asyncio.create_task(background())
    await asyncio.sleep(0)
    cog._bg_tasks.add(task)
    monkeypatch.setattr(extractor, 'close_extractor_resources', AsyncMock(side_effect=RuntimeError('close failed')))
    monkeypatch.setattr(m, 'close_extractor_resources', extractor.close_extractor_resources, raising=False)
    try:
        result = cog.cog_unload()
        assert inspect.isawaitable(result), 'discord.py supports awaited cog cleanup'
        await result
        assert finalized.is_set()
        player.stop.assert_awaited_once()
        assert not cog._players
        assert not cog._bg_tasks
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_seek_guard_denies_outsider():
    player = Player(busy=True)
    cog = cog_for(player)
    ctx = context(player)
    ctx.author.voice.channel = object()
    with pytest.raises(commands.CheckFailure, match='music_same_voice_channel'):
        await cog.cog_before_invoke(ctx)
    assert ctx.send.await_count == 1


@pytest.mark.asyncio
async def test_seek_rechecks_voice_after_defer():
    player = Player(busy=True)
    player.current = m.Track(stored(1))
    player._play = AsyncMock()
    cog = cog_for(player)
    ctx = context(player)

    async def move_away():
        ctx.author.voice.channel = object()

    ctx.defer.side_effect = move_away
    try:
        await m.Music.seek_cmd.callback(cog, ctx, '20')
    except commands.CheckFailure:
        pass
    player._play.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_background_queue_does_not_extract_or_admit(monkeypatch):
    player = Player(busy=True)
    player.queue.extend([object()] * m.MAX_QUEUE_SIZE)
    cog = cog_for(player)
    extract = AsyncMock(return_value=stored(1))
    monkeypatch.setattr(m, 'extract_info', extract)
    await cog._load_playlist_background(player, [stored(i) for i in range(8)], None)
    extract.assert_not_awaited()
    assert not player.admitted


@pytest.mark.asyncio
async def test_background_metadata_preserves_order_and_queue_identity(monkeypatch):
    player = Player(busy=True)
    cog = cog_for(player)
    queue = player.queue
    extract = AsyncMock(return_value=stored(99))
    monkeypatch.setattr(m, 'extract_info', extract)
    await cog._load_playlist_background(player, [stored(i) for i in range(4)], None)
    assert player.queue is queue
    assert [t.title for t in queue] == [f'song {i}' for i in range(4)]
    assert [t.duration for t in queue] == [120 + i for i in range(4)]
    assert all(t.stream_url is None for t in queue)
    assert player.admitted == queue
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_saved_playlist_resolves_only_first_viable_track(monkeypatch):
    import database
    player = Player()
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    tracks = [stored(i) for i in range(4)]
    monkeypatch.setattr(database, 'async_get_playlist_by_name', AsyncMock(return_value={'tracks': tracks}))
    calls = []

    async def extract(query):
        calls.append(query)
        if query in (tracks[0]['webpage_url'], tracks[0]['title']):
            return None
        return {**stored(1), 'stream_url': 'https://cdn/audio'}

    monkeypatch.setattr(m, 'extract_info', extract)
    await m.Music.playlist_play.callback(cog, context(player), name='saved')
    await drain(cog)
    assert calls == [tracks[0]['webpage_url'], tracks[0]['title'], tracks[1]['webpage_url']]
    assert player.current.title == 'song 1'
    assert [t.title for t in player.queue] == ['song 2', 'song 3']
    assert all(t.stream_url is None for t in player.queue)


@pytest.mark.asyncio
@pytest.mark.parametrize('invalidate', ['stop', 'replace'])
async def test_playlist_first_resolution_cannot_admit_to_stopped_or_replaced_player(monkeypatch, invalidate):
    import database
    player = Player()
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    monkeypatch.setattr(database, 'async_get_playlist_by_name', AsyncMock(return_value={'tracks': [stored(1), stored(2)]}))

    async def extract(query):
        if invalidate == 'stop':
            player._manual_stopped = True
        else:
            cog._players[1] = Player()
        return stored(1)

    monkeypatch.setattr(m, 'extract_info', extract)
    await m.Music.playlist_play.callback(cog, context(player), name='saved')
    await drain(cog)
    assert not player.admitted
    assert not player.queue


@pytest.mark.asyncio
async def test_duplicate_same_channel_bot_events_do_not_schedule_reconnect():
    player = Player()
    player._is_reconnecting = True
    cog = cog_for(player)
    cog._schedule_reconnect_task = Mock()
    cog._check_and_schedule_empty_voice = Mock()
    member = NS(id=9, guild=NS(id=1), bot=True)
    before = NS(channel=player.vc.channel, self_deaf=False, deaf=False, self_mute=False, mute=False)
    after = NS(channel=player.vc.channel, self_deaf=True, deaf=False, self_mute=False, mute=False)
    await cog.on_voice_state_update(member, before, after)
    await cog.on_voice_state_update(member, after, before)
    cog._schedule_reconnect_task.assert_not_called()


@pytest.mark.asyncio
async def test_play_uses_atomic_admission_for_busy_player(monkeypatch):
    player = Player(busy=True)
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    monkeypatch.setattr(m, 'extract_info', AsyncMock(return_value=stored(1)))
    ctx = context(player)
    await m.Music.play.callback(cog, ctx, query='a song')
    assert len(player.admitted) == 1
    assert player.queue == player.admitted
    assert ctx.send.call_args.kwargs.get('embed') is not None


@pytest.mark.asyncio
async def test_search_uses_shared_extraction_runner(monkeypatch):
    player = Player()
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(m, 'run_extraction_job', runner, raising=False)
    monkeypatch.setattr(m, '_get_ydl_flat', lambda: NS(extract_info=lambda *a, **kw: None))
    await m.Music.search_cmd.callback(cog, context(player), query='song')
    runner.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_grace_callback_does_not_remove_replacement():
    player = Player()
    cog = cog_for(player)
    cog._handle_voice_disconnect_grace = AsyncMock()
    member = NS(id=9, guild=NS(id=1), bot=True)
    before = NS(channel=player.vc.channel, self_deaf=False, deaf=False, self_mute=False, mute=False)
    after = NS(channel=None, self_deaf=False, deaf=False, self_mute=False, mute=False)
    replacement = asyncio.create_task(asyncio.Event().wait())
    try:
        await cog.on_voice_state_update(member, before, after)
        old = cog._grace_tasks[1]
        cog._grace_tasks[1] = replacement
        await old
        await asyncio.sleep(0)
        assert cog._grace_tasks.get(1) is replacement
    finally:
        replacement.cancel()
        await asyncio.gather(replacement, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', ['queue', 'background'])
async def test_metadata_loader_obeys_capacity_and_background_limit(monkeypatch, limit):
    player = Player(busy=True)
    cog = cog_for(player)
    extract = AsyncMock()
    monkeypatch.setattr(m, 'extract_info', extract)
    # Use a small background limit to keep this offline regression fast.
    monkeypatch.setattr(m, 'MAX_BG_LOAD', 3)
    if limit == 'queue':
        player.queue.extend([object()] * (m.MAX_QUEUE_SIZE - 1))
    await cog._load_playlist_background(player, [stored(i) for i in range(8)], None)
    assert len(player.admitted) == (1 if limit == 'queue' else 3)
    assert len(player.queue) <= m.MAX_QUEUE_SIZE
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_playlist_queues_metadata_without_resolving_first(monkeypatch):
    import database
    player = Player(busy=True)
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    monkeypatch.setattr(database, 'async_get_playlist_by_name', AsyncMock(return_value={'tracks': [stored(1), stored(2)]}))
    extract = AsyncMock()
    monkeypatch.setattr(m, 'extract_info', extract)
    await m.Music.playlist_play.callback(cog, context(player), name='saved')
    await drain(cog)
    assert [t.title for t in player.queue] == ['song 1', 'song 2']
    assert all(t.stream_url is None for t in player.queue)
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_does_not_drop_replacement_and_survives_player_failure(monkeypatch):
    player = Player()
    cog = cog_for(player)
    replacement = Player()

    async def replace_then_fail():
        cog._players[1] = replacement
        raise RuntimeError('stop failure')

    player.stop.side_effect = replace_then_fail
    closer = AsyncMock()
    monkeypatch.setattr(m, 'close_extractor_resources', closer)
    await cog.cog_unload()
    assert cog._players[1] is replacement
    assert not replacement._manual_stopped
    closer.assert_awaited_once()


@pytest.mark.asyncio
async def test_grace_timeout_does_not_drop_replacement():
    player = Player()
    cog = cog_for(player)
    replacement = Player()

    async def replaced_timeout(guild_id):
        cog._players[guild_id] = replacement
        raise asyncio.TimeoutError

    cog._handle_voice_disconnect_grace = replaced_timeout
    member = NS(id=9, guild=NS(id=1), bot=True)
    before = NS(channel=player.vc.channel, self_deaf=False, deaf=False, self_mute=False, mute=False)
    after = NS(channel=None, self_deaf=False, deaf=False, self_mute=False, mute=False)
    await cog.on_voice_state_update(member, before, after)
    await cog._grace_tasks[1]
    assert cog._players.get(1) is replacement


@pytest.mark.asyncio
async def test_lofi_extraction_does_not_admit_after_player_replacement(monkeypatch):
    player = Player()
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)

    async def extract(*args, **kwargs):
        cog._players[1] = Player()
        return stored(1)

    monkeypatch.setattr(m, 'extract_info', extract)
    ctx = context(player)
    await m.Music.lofi.callback(cog, ctx, 'youtube')
    assert not player.admitted
    ctx.send.assert_not_awaited()


class JoiningVC:
    def __init__(self, client, channel):
        self.client, self.channel = client, channel
        self.connected = True
        self.source = None
        self.disconnects = 0

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return False

    def is_paused(self):
        return False

    async def disconnect(self, **kwargs):
        self.disconnects += 1
        self.connected = False


def joining_cog(monkeypatch):
    from music import cog_voice as cv
    guild = NS(id=1, voice_client=None, me=NS(voice=None))
    cog = cog_for(Player())
    cog._players.clear()
    cog._registry_lock = asyncio.Lock()
    cog.bot.loop = asyncio.get_running_loop()
    cog.bot.get_cog = lambda name: cog
    room = NS(name='room')
    ctx = context(Player())
    ctx.guild, ctx.channel, ctx.author.voice.channel = guild, object(), room
    monkeypatch.setattr(cv, 'async_get_guild_settings', AsyncMock(return_value={'language': 'en'}))
    monkeypatch.setattr(cv.discord, 'VoiceClient', JoiningVC)
    monkeypatch.setattr(m, 'close_extractor_resources', AsyncMock())
    return cog, ctx, room


@pytest.mark.asyncio
async def test_unload_cannot_register_late_connection_and_drains_join(monkeypatch):
    cog, ctx, room = joining_cog(monkeypatch)
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    connections = []

    async def connect(**kwargs):
        vc = JoiningVC(cog.bot, room)
        connections.append(vc)
        ctx.guild.voice_client = vc
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Model a handshake that completes while cancellation is being delivered.
            cancelled.set()
            await release.wait()
        return vc

    room.connect = connect
    join = asyncio.create_task(m.Music.join.callback(cog, ctx))
    await entered.wait()
    unload = asyncio.create_task(cog.cog_unload())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(unload, 1)
    await asyncio.gather(join, return_exceptions=True)
    assert cancelled.is_set(), 'unload did not cancel/drain the in-flight join'
    assert not cog._players
    assert not cog._connecting
    assert not connections[0].is_connected()
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['entry', 'settings', 'lock'])
async def test_ensure_rejects_unloaded_generation_at_entry_and_wait_boundaries(monkeypatch, boundary):
    from music import cog_voice as cv
    cog, ctx, room = joining_cog(monkeypatch)
    room.connect = AsyncMock(return_value=JoiningVC(cog.bot, room))
    entered, release = asyncio.Event(), asyncio.Event()
    if boundary == 'entry':
        await cog.cog_unload()
        assert await cog._ensure(ctx) is None
    else:
        if boundary == 'settings':
            async def settings(guild_id):
                entered.set()
                await release.wait()
                return {'language': 'en'}
            monkeypatch.setattr(cv, 'async_get_guild_settings', settings)
        else:
            lock = cog._player_locks.setdefault(1, asyncio.Lock())
            await lock.acquire()
        task = asyncio.create_task(cog._ensure(ctx))
        if boundary == 'settings':
            await entered.wait()
        else:
            await asyncio.sleep(0)
        await cog.cog_unload()
        release.set()
        if boundary == 'lock':
            lock.release()
        result = await asyncio.gather(task, return_exceptions=True)
        assert result[0] is None or isinstance(result[0], asyncio.CancelledError)
    room.connect.assert_not_awaited()
    assert not cog._players and not cog._connecting


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['cancel', 'exception'])
async def test_partial_join_cleanup_releases_reservation_on_failure(monkeypatch, failure):
    cog, ctx, room = joining_cog(monkeypatch)
    entered = asyncio.Event()
    created = []

    async def connect(**kwargs):
        # Match discord.py: cls is constructed and registered before its handshake.
        vc = kwargs.get('cls', JoiningVC)(cog.bot, room)
        created.append(vc)
        ctx.guild.voice_client = vc
        entered.set()
        if failure == 'exception':
            raise RuntimeError('handshake failed')
        await asyncio.Event().wait()

    room.connect = connect
    task = asyncio.create_task(cog._ensure(ctx))
    await entered.wait()
    if failure == 'cancel':
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not cog._connecting
    assert not cog._players
    assert not created[0].is_connected()


@pytest.mark.asyncio
@pytest.mark.parametrize('same_client', [False, True])
async def test_abandoned_join_does_not_disconnect_replacement_owned_voice(monkeypatch, same_client):
    cog, ctx, room = joining_cog(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    created = []

    async def connect(**kwargs):
        vc = kwargs.get('cls', JoiningVC)(cog.bot, room)
        created.append(vc)
        ctx.guild.voice_client = vc
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return vc

    room.connect = connect
    task = asyncio.create_task(cog._ensure(ctx))
    await entered.wait()
    replacement_vc = created[0] if same_client else JoiningVC(cog.bot, room)
    replacement = NS(_get=lambda guild_id: NS(vc=replacement_vc))
    cog.bot.get_cog = lambda name: replacement
    ctx.guild.voice_client = replacement_vc
    unload = asyncio.create_task(cog.cog_unload())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(unload, 1)
    await asyncio.gather(task, return_exceptions=True)
    assert replacement_vc.disconnects == 0
    assert replacement_vc.is_connected()
    assert not cog._players and not cog._connecting


@pytest.mark.asyncio
async def test_unload_deadline_rejects_connection_released_after_unload_finishes(monkeypatch):
    cog, ctx, room = joining_cog(monkeypatch)
    cog._JOIN_DRAIN_TIMEOUT = 0.02
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    created = []

    async def connect(**kwargs):
        vc = kwargs['cls'](cog.bot, room)
        created.append(vc)
        ctx.guild.voice_client = vc
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return vc

    room.connect = connect
    task = asyncio.create_task(m.Music.join.callback(cog, ctx))
    await entered.wait()
    try:
        await asyncio.wait_for(cog.cog_unload(), 1)
        assert cancelled.is_set() and not task.done()
        assert not cog._connecting
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert not cog._players and not cog._join_tasks
    assert not created[0].is_connected()
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_during_self_deaf_await_stops_registered_player_and_rejects_join(monkeypatch):
    cog, ctx, room = joining_cog(monkeypatch)
    vc = JoiningVC(cog.bot, room)

    async def connect(**kwargs):
        ctx.guild.voice_client = vc
        return vc

    room.connect = connect
    ctx.guild.me.voice = NS(channel=room, self_deaf=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def change_voice_state(**kwargs):
        if kwargs.get('self_deaf'):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        else:
            ctx.guild.me.voice = None

    ctx.guild.change_voice_state = change_voice_state
    task = asyncio.create_task(m.Music.join.callback(cog, ctx))
    await entered.wait()
    player = cog._get(1)
    assert isinstance(player, m.MusicPlayer)
    unload = asyncio.create_task(cog.cog_unload())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(unload, 1)
    await asyncio.gather(task, return_exceptions=True)
    assert player._manual_stopped and not cog._players
    assert not cog._connecting and not cog._join_tasks
    assert not vc.is_connected()
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_playlist_does_not_start_title_fallback_after_queue_fills(monkeypatch):
    import database
    player = Player()
    cog = cog_for(player)
    cog._ensure = AsyncMock(return_value=player)
    data = stored(1)
    monkeypatch.setattr(database, 'async_get_playlist_by_name', AsyncMock(return_value={'tracks': [data]}))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def extract(query):
        calls.append((query, len(player.queue)))
        entered.set()
        await release.wait()
        return None

    monkeypatch.setattr(m, 'extract_info', extract)
    ctx = context(player)
    task = asyncio.create_task(m.Music.playlist_play.callback(cog, ctx, name='saved'))
    await entered.wait()
    player.queue.extend([object()] * m.MAX_QUEUE_SIZE)
    release.set()
    await task
    assert calls == [(data['webpage_url'], 0)]
    assert not player.admitted and not cog._bg_tasks
    assert ctx.send.await_args.args == (m.tr({'language': 'en'}, 'music.queue_full', max=m.MAX_QUEUE_SIZE),)
    assert ctx.send.await_args.kwargs == {'ephemeral': True}
    ctx.send.return_value.delete.assert_awaited_once()

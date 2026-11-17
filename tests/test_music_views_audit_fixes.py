"""Offline regressions for music component ownership and async interleaving."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import database
import music.views as views
from music.player import Track


class Response:
    def __init__(self, hook=None):
        self.hook = hook
        self.messages = []
        self.deferred = False

    async def defer(self):
        self.deferred = True
        if self.hook:
            await self.hook()

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class Voice:
    def __init__(self, channel):
        self.channel = channel
        self.paused = False
        self.connected = True
        self.pause_calls = 0

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return not self.paused

    def is_paused(self):
        return self.paused

    def pause(self):
        self.paused = True
        self.pause_calls += 1

    def resume(self):
        self.paused = False


class Player:
    def __init__(self, gid, channel):
        self.guild = SimpleNamespace(id=gid)
        self.vc = Voice(channel)
        self.cog = None
        self.autoplay = False
        self.loop_mode = 0
        self.volume = 1.0
        self.pause_start = 0.0
        self.total_paused_time = 0.0
        self.current = Track({"title": f"Guild {gid}", "duration": 60})
        self.queue = []
        self.text_channel = SimpleNamespace(send=AsyncMock())
        self._cleanup_done = False
        self._manual_stopped = False
        self.skips = 0
        self.stops = 0
        self.admissions = []

    def get_elapsed(self):
        return 0

    def skip(self):
        self.skips += 1

    async def stop(self):
        self.stops += 1
        self._cleanup_done = True

    async def add_and_play(self, track):
        self.admissions.append(track)
        self.queue.append(track)


def interaction(player, hook=None, user=None):
    if user is None:
        user = SimpleNamespace(id=10, mention="<@10>", voice=SimpleNamespace(channel=player.vc.channel))
    return SimpleNamespace(
        guild=player.guild, guild_id=player.guild.id, user=user,
        response=Response(hook), followup=SimpleNamespace(send=AsyncMock()),
        message=SimpleNamespace(edit=AsyncMock()), channel=player.text_channel,
    )


def attach_players(*players):
    registry = {p.guild.id: p for p in players}
    cog = SimpleNamespace(_get=registry.get)
    for player in players:
        player.cog = cog
    return cog, registry


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    monkeypatch.setattr(views, "async_get_guild_settings", AsyncMock(side_effect=lambda gid: {"language": "en" if gid == "1" else "fr"}))
    monkeypatch.setattr(database, "async_get_guild_settings", AsyncMock(return_value={"language": "en"}))


@pytest.mark.parametrize("action", ["skip", "stop", "pause", "loop", "autoplay"])
def test_persistent_controls_keep_each_guild_local_across_defer(action):
    async def scenario():
        first, second = Player(1, object()), Player(2, object())
        cog, _ = attach_players(first, second)
        shell = views.MusicControlView(cog=cog)
        entered, release = asyncio.Event(), asyncio.Event()

        async def wait():
            entered.set()
            await release.wait()

        a, b = interaction(first, wait), interaction(second)
        button = getattr(shell, f"btn_{action}")
        pending = asyncio.create_task(button.callback(a))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            await button.callback(b)
        finally:
            release.set()
        await pending
        if action == "skip":
            assert (first.skips, second.skips) == (1, 1)
        elif action == "stop":
            assert (first.stops, second.stops) == (1, 1)
            assert first.text_channel.send.await_count == second.text_channel.send.await_count == 1
        else:
            attribute = {"pause": "pause_calls", "loop": "loop_mode", "autoplay": "autoplay"}[action]
            targets = (first.vc, second.vc) if action == "pause" else (first, second)
            assert [getattr(p, attribute) for p in targets] == [1, 1]
            rendered = [i.message.edit.await_args.kwargs["view"] for i in (a, b)]
            assert rendered[0] is not rendered[1] and shell not in rendered
            assert [v.player for v in rendered] == [first, second]
            assert [v.settings["language"] for v in rendered] == ["en", "fr"]
        assert shell.player is None and shell.settings == {}
    asyncio.run(scenario())


def test_persistent_check_is_boolean_without_retaining_guild_state():
    async def scenario():
        player = Player(1, object())
        cog, _ = attach_players(player)
        shell = views.MusicControlView(cog=cog)
        assert await shell._check(interaction(player)) is True
        assert shell.player is None and shell.settings == {}
        assert shell.is_persistent()
        assert {c.custom_id for c in shell.children} == {
            "music_skip", "music_stop", "music_pause", "music_loop", "music_autoplay",
        }
    asyncio.run(scenario())


def test_control_settings_await_does_not_change_validated_guild(monkeypatch):
    async def scenario():
        first, second = Player(1, object()), Player(2, object())
        cog, _ = attach_players(first, second)
        entered, release = asyncio.Event(), asyncio.Event()

        async def settings(gid):
            if gid == "1":
                entered.set()
                await release.wait()
            return {"language": "en"}

        monkeypatch.setattr(views, "async_get_guild_settings", settings)
        shell = views.MusicControlView(cog=cog)
        a = interaction(first)
        pending = asyncio.create_task(shell.btn_skip.callback(a))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            await shell.btn_skip.callback(interaction(second))
        finally:
            release.set()
        await pending
        assert (first.skips, second.skips) == (1, 1)
    asyncio.run(scenario())


def test_settings_failure_does_not_reuse_another_guild_language(monkeypatch):
    async def scenario():
        first, second = Player(1, object()), Player(2, object())
        cog, _ = attach_players(first, second)
        shell = views.MusicControlView(cog=cog)
        assert await shell._check(interaction(first)) is True
        monkeypatch.setattr(views, "async_get_guild_settings", AsyncMock(side_effect=RuntimeError("database is locked")))
        inter = interaction(second)
        await shell.btn_loop.callback(inter)
        rendered = inter.message.edit.await_args.kwargs["view"]
        assert rendered.player is second
        assert rendered.settings == {}
        assert second.loop_mode == 1
        assert shell.player is None and shell.settings == {}
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["replaced", "left_voice", "stopped"])
def test_control_revalidates_after_defer(change):
    async def scenario():
        player = Player(1, object())
        cog, registry = attach_players(player)
        inter = interaction(player)

        async def mutate():
            if change == "replaced":
                registry[1] = Player(1, player.vc.channel)
            elif change == "left_voice":
                inter.user.voice = None
            else:
                player._cleanup_done = True

        inter.response.hook = mutate
        await views.MusicControlView(cog=cog).btn_skip.callback(inter)
        assert player.skips == 0
        assert inter.followup.send.await_count == 1
    asyncio.run(scenario())


def make_search():
    player = Player(1, object())
    _, registry = attach_players(player)
    inter = interaction(player)
    results = [{"title": "Selected", "webpage_url": "https://example.test/song", "duration": 60}]
    view = views.SearchSelectView(results, inter.user, player, {"language": "en"})
    select = view.children[0]
    select._values = ["0"]
    return player, registry, inter, view, select, results[0]


def test_search_runtime_track_and_existing_admission_api(monkeypatch):
    async def scenario():
        player, _, inter, view, select, info = make_search()
        queue = player.queue
        monkeypatch.setattr(views, "extract_info", AsyncMock(return_value=info))
        await select.callback(inter)
        assert len(player.admissions) == 1
        assert isinstance(player.admissions[0], Track)
        assert player.admissions[0].requester is inter.user
        assert player.queue is queue
        assert view.is_finished() and select.disabled
        assert inter.followup.send.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["replaced", "stopped", "left_voice", "moved_voice", "disconnected", "timeout"])
def test_search_rejects_stale_state_after_extraction(monkeypatch, change):
    async def scenario():
        player, registry, inter, view, select, info = make_search()
        entered, release = asyncio.Event(), asyncio.Event()

        async def extract(query):
            entered.set()
            await release.wait()
            return info

        monkeypatch.setattr(views, "extract_info", extract)
        pending = asyncio.create_task(select.callback(inter))
        await asyncio.wait_for(entered.wait(), timeout=2)
        if change == "replaced":
            registry[1] = Player(1, player.vc.channel)
        elif change == "stopped":
            player._cleanup_done = True
            player._manual_stopped = True
        elif change == "left_voice":
            inter.user.voice = None
        elif change == "moved_voice":
            # Even moving the bot and requester together must invalidate the old search.
            player.vc.channel = object()
            inter.user.voice.channel = player.vc.channel
        elif change == "disconnected":
            player.vc.connected = False
        else:
            await view.on_timeout()
        release.set()
        await pending
        assert not player.queue and not player.admissions
        assert inter.followup.send.await_count == 1
    asyncio.run(scenario())


def test_search_double_click_admits_once_and_snapshots_selection(monkeypatch):
    async def scenario():
        player, _, first, _, select, info = make_search()
        second = interaction(player, user=first.user)
        entered, release = asyncio.Event(), asyncio.Event()
        queries = []

        async def wait():
            entered.set()
            await release.wait()

        async def extract(query):
            queries.append(query)
            return info

        monkeypatch.setattr(views, "extract_info", extract)
        first.response.hook = wait
        pending = asyncio.create_task(select.callback(first))
        await asyncio.wait_for(entered.wait(), timeout=2)
        select._values = ["999"]
        try:
            await select.callback(second)
        finally:
            release.set()
        await pending
        assert len(player.admissions) == 1
        assert queries == [info["webpage_url"]]
    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["-1", "5", "invalid"])
def test_search_rejects_invalid_selection_without_extraction(monkeypatch, value):
    async def scenario():
        player, _, inter, _, select, _ = make_search()
        extract = AsyncMock()
        monkeypatch.setattr(views, "extract_info", extract)
        select._values = [value]
        await select.callback(inter)
        assert extract.await_count == 0
        assert not player.admissions
        assert inter.response.messages
    asyncio.run(scenario())


def test_search_queue_limit_is_checked_after_extraction(monkeypatch):
    async def scenario():
        player, _, inter, _, select, info = make_search()

        async def extract(query):
            player.queue.extend([player.current] * 100)
            return info

        monkeypatch.setattr(views, "extract_info", extract)
        await select.callback(inter)
        assert len(player.queue) == 100 and not player.admissions
        assert inter.followup.send.await_count == 1
    asyncio.run(scenario())


def test_search_failed_admission_does_not_report_queue_full(monkeypatch):
    async def scenario():
        player, _, inter, view, select, info = make_search()
        player.add_and_play = AsyncMock(return_value=False)
        monkeypatch.setattr(views, "extract_info", AsyncMock(return_value=info))
        await select.callback(inter)
        response = inter.followup.send.await_args.args[0]
        assert response == views.tr({"language": "en"}, "music.cannot_decode", title=info["title"])
        assert not view.is_finished()
        assert not player.queue
    asyncio.run(scenario())


def make_remove():
    player = Player(1, object())
    inter = interaction(player)
    ctx = SimpleNamespace(author=inter.user, guild=player.guild)
    tracks = [{"id": 101, "title": "First", "duration": 60}, {"id": 102, "title": "Second", "duration": 60}]
    view = views.RemoveSongView(ctx, {"name": "Mine"}, tracks, {"language": "en"})
    select = next(c for c in view.children if isinstance(c, views.RemoveSongSelect))
    select._values = ["1"]
    return player, inter, view, select


@pytest.mark.parametrize("component", ["select", "confirm", "cancel"])
def test_remove_view_wide_requester_check_protects_all_components(component):
    async def scenario():
        player, owner, view, select = make_remove()
        outsider = interaction(player)
        outsider.user.id = 999
        view.selected_index = 0
        assert await view.interaction_check(outsider) is False
        assert await view.interaction_check(owner) is True
        control = select if component == "select" else getattr(view, component)
        await control.callback(outsider)
        assert view.selected_index == 0
        assert not view.is_finished()
        assert outsider.response.messages
    asyncio.run(scenario())


@pytest.mark.parametrize("yield_at", ["settings", "defer"])
def test_remove_confirm_captures_track_before_any_await(monkeypatch, yield_at):
    async def scenario():
        player, inter, view, select = make_remove()
        view.selected_index = 0
        deleted = AsyncMock()
        monkeypatch.setattr(database, "async_delete_track_from_playlist", deleted)
        entered, release = asyncio.Event(), asyncio.Event()

        async def wait():
            entered.set()
            await release.wait()

        async def settings(gid):
            if yield_at == "settings":
                await wait()
            return {"language": "en"}

        monkeypatch.setattr(database, "async_get_guild_settings", settings)
        if yield_at == "defer":
            inter.response.hook = wait
        pending = asyncio.create_task(view.confirm.callback(inter))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            await select.callback(interaction(player, user=inter.user))
        finally:
            release.set()
        await pending
        assert deleted.await_args.args == (101,)
        assert view.is_finished()
    asyncio.run(scenario())


def test_remove_double_confirm_deletes_once(monkeypatch):
    async def scenario():
        player, first, view, _ = make_remove()
        view.selected_index = 0
        deleted = AsyncMock()
        monkeypatch.setattr(database, "async_delete_track_from_playlist", deleted)
        entered, release = asyncio.Event(), asyncio.Event()

        async def wait():
            entered.set()
            await release.wait()

        first.response.hook = wait
        pending = asyncio.create_task(view.confirm.callback(first))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            await view.confirm.callback(interaction(player, user=first.user))
        finally:
            release.set()
        await pending
        assert deleted.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["autoplay", "pause", "loop"])
@pytest.mark.parametrize("finished_at", ["initial", "settings", "defer"])
def test_idle_control_uses_localized_no_song_response(monkeypatch, action, finished_at):
    async def scenario():
        player = Player(2, object())
        cog, _ = attach_players(player)
        shell = views.MusicControlView(cog=cog)

        async def finish():
            player.current = None

        async def settings(gid):
            if finished_at == "settings":
                await finish()
            return {"language": "fr"}

        monkeypatch.setattr(views, "async_get_guild_settings", settings)
        if finished_at == "initial":
            await finish()
        inter = interaction(player, finish if finished_at == "defer" else None)
        await getattr(shell, f"btn_{action}").callback(inter)
        # Autoplay can still be enabled on a newly joined/idle player. Pause
        # must not manufacture paused time when there is no current track.
        assert player.autoplay is (action == "autoplay")
        assert player.loop_mode == (1 if action == "loop" else 0)
        assert player.vc.pause_calls == 0 and player.pause_start == 0
        assert inter.message.edit.await_count == 0
        assert inter.followup.send.await_args.args == (
            views.tr({"language": "fr"}, "music.no_song_playing"),
        )
        assert inter.followup.send.await_args.kwargs["ephemeral"] is True
        assert shell.player is None and shell.settings == {}
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["autoplay", "pause", "loop"])
@pytest.mark.parametrize("changed_at", ["settings", "defer"])
@pytest.mark.parametrize("change", ["replaced", "stopping"])
def test_control_edit_rejects_stale_player_after_await(monkeypatch, action, changed_at, change):
    async def scenario():
        player = Player(2, object())
        replacement = Player(2, player.vc.channel)
        cog, registry = attach_players(player)
        shell = views.MusicControlView(cog=cog)

        async def mutate():
            if change == "replaced":
                registry[2] = replacement
            else:
                player._is_stopping = True

        async def settings(gid):
            if changed_at == "settings":
                await mutate()
            return {"language": "fr"}

        monkeypatch.setattr(views, "async_get_guild_settings", settings)
        inter = interaction(player, mutate if changed_at == "defer" else None)
        await getattr(shell, f"btn_{action}").callback(inter)
        for candidate in (player, replacement):
            assert candidate.autoplay is False and candidate.loop_mode == 0
            assert candidate.vc.pause_calls == 0 and candidate.pause_start == 0
        assert inter.message.edit.await_count == 0
        expected = views.tr({"language": "fr"}, "music.not_in_voice")
        if changed_at == "settings":
            assert inter.response.messages[0][0] == (expected,)
        else:
            assert inter.followup.send.await_args.args == (expected,)
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["autoplay", "pause", "loop"])
@pytest.mark.parametrize("source_state", ["copy", "encoded", "retired", "no_active"])
def test_control_embed_preserves_accurate_opus_source_indicator(action, source_state):
    async def scenario():
        player = Player(2, object())
        cog, _ = attach_players(player)
        player.volume = 0.5
        player._using_opus_copy = source_state != "encoded"
        player._active_source = None if source_state == "no_active" else object()
        player.vc.source = object() if source_state == "retired" else player._active_source
        inter = interaction(player)
        await getattr(views.MusicControlView(cog=cog), f"btn_{action}").callback(inter)
        edit = inter.message.edit.await_args.kwargs
        expected = f"ℹ️ {views.tr({'language': 'fr'}, 'music.vol_applies_next')}" if source_state == "copy" else None
        assert edit["embed"].footer.text == expected
        assert edit["view"].settings == {"language": "fr"}
        assert {c.custom_id for c in edit["view"].children} == {
            "music_skip", "music_stop", "music_pause", "music_loop", "music_autoplay",
        }
    asyncio.run(scenario())

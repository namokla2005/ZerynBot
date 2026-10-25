"""P3-B — View persistent resolve đúng guild, cache deep copy, AI cooldown/model,
và các fix cleanup nhỏ (bg path, decompression bomb, :memory:)."""
import asyncio
import io
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cache import cache  # noqa: E402
import ai_manager as aim  # noqa: E402
import card_generator as cards  # noqa: E402
from pathlib import Path  # noqa: E402


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_persistent_view_resolves_player_per_guild(monkeypatch):
    import music.views as views

    class Chan:
        def __init__(self, cid):
            self.id = cid

        def __eq__(self, other):
            return isinstance(other, Chan) and other.id == self.id

        def __hash__(self):
            return hash(self.id)

    class Player:
        def __init__(self, gid, cid):
            self.guild = types.SimpleNamespace(id=gid)
            self.vc = types.SimpleNamespace(channel=Chan(cid))

    players = {1: Player(1, 10), 2: Player(2, 20)}

    class Cog:
        def _get(self, gid):
            return players.get(gid)

    class Response:
        def __init__(self):
            self.sent = []

        async def send_message(self, *a, **k):
            self.sent.append((a, k))

    class Interaction:
        def __init__(self, gid, cid):
            self.guild = types.SimpleNamespace(id=gid)
            self.user = types.SimpleNamespace(voice=types.SimpleNamespace(channel=Chan(cid)))
            self.response = Response()

    async def fake_settings(gid):
        return {}

    monkeypatch.setattr(views, "async_get_guild_settings", fake_settings)
    view = views.MusicControlView(player=None, settings={}, cog=Cog())

    assert asyncio.run(view._check(Interaction(1, 10))) is True
    assert view.player.guild.id == 1
    assert asyncio.run(view._check(Interaction(2, 20))) is True
    assert view.player.guild.id == 2, "view vẫn giữ player của guild bấm đầu tiên"


def test_cache_deepcopy_blocks_nested_poison():
    cache.clear()
    cache.set("nested", {"sub": {"lang": "vi"}})
    got = cache.get("nested")
    got["sub"]["lang"] = "en"
    assert cache.get("nested")["sub"]["lang"] == "vi"


def test_all_keys_cooling_returns_none_and_backoff_grows():
    mgr = aim.AIProviderManager()
    assert mgr.get_next_available_key("groq", ["k1"]) == "k1"
    mgr.mark_cooldown("k1", base_cooldown=60.0)
    assert mgr.get_next_available_key("groq", ["k1"]) is None

    first = mgr._cooldowns["k1"][1]
    mgr.mark_cooldown("k1", base_cooldown=60.0)
    second = mgr._cooldowns["k1"][1]
    assert second > first, "429 lặp phải tăng backoff"


def test_openrouter_model_is_not_sent_to_groq(monkeypatch):
    calls = []

    class R:
        status_code = 500
        text = "err"

    def fake_post(url, headers=None, json=None, **kwargs):
        calls.append(json["model"])
        return R()

    monkeypatch.setattr(aim.requests, "post", fake_post)
    mgr = aim.AIProviderManager()
    mgr._call_groq_sync(
        "k", "p", model="nvidia/nemotron-3.5-lightning:free", request_budget=[1]
    )
    assert calls == [aim.GROQ_MODELS[0]], calls


def test_card_rejects_decompression_bomb():
    from PIL import Image

    img = Image.new("RGB", (9000, 1), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    with pytest.raises(ValueError):
        cards._open_rgba(buf.getvalue())


def test_card_bg_path_points_to_dashboard_static():
    base = Path(cards.__file__).resolve().parent.parent
    assert (base / "dashboard" / "static" / "bg.png").exists()


def test_init_db_accepts_memory_path():
    import database

    old = database.get_db_path()
    try:
        database.set_db_path(":memory:")
        database.init_db()
    finally:
        database.set_db_path(old)


def test_source_guards_for_music_and_tester():
    music = _read("bot/cogs/music.py")
    voice = _read("bot/music/cog_voice.py")
    player = _read("bot/music/player.py")
    tester = _read("bot/tester.py")

    assert "_VOICE_REQUIRED_COMMANDS" in music and "same_voice_err" in music
    assert "_start_inactivity_timer()" in voice
    assert "range(150)" in player and "_extract_semaphore" in player
    assert "get_db_connection()" in tester

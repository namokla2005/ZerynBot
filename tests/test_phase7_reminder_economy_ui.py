"""P4-C — Reminder DM giữ guild_id để dịch đúng ngôn ngữ; delreminder theo owner."""
import asyncio
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_COGS = os.path.join(ROOT, "bot", "cogs")
sys.path.insert(0, _COGS)
try:
    import remind as remind_mod  # noqa: E402
finally:
    sys.path.remove(_COGS)


class FakeCtx:
    def __init__(self):
        self.guild = types.SimpleNamespace(id=123)
        self.channel = types.SimpleNamespace(id=456)
        self.author = types.SimpleNamespace(
            id=789, display_name="User",
            display_avatar=types.SimpleNamespace(url="https://cdn.example/avatar.png"),
        )
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_dm_reminder_keeps_guild_id_and_language_context(temp_db, monkeypatch):
    import database as db

    async def fake_settings(guild_id):
        return {"language": "en"}

    monkeypatch.setattr(remind_mod, "async_get_guild_settings", fake_settings)
    cog = object.__new__(remind_mod.Remind)
    ctx = FakeCtx()

    asyncio.run(remind_mod.Remind.remindme.callback(cog, ctx, "10m", "uống nước", True))

    rows = asyncio.run(db.async_get_user_reminders("789"))
    assert len(rows) == 1
    assert rows[0]["guild_id"] == "123", "DM reminder mất guild_id -> delivery rơi về tiếng Việt"
    assert rows[0]["is_dm"] == 1
    assert rows[0]["channel_id"] == "" or rows[0]["channel_id"] is None


def test_get_reminder_is_owner_scoped(temp_db):
    import database as db
    import time

    rid = asyncio.run(db.async_add_reminder("u1", "g1", "", "x", int(time.time()) + 60, is_dm=1))
    assert asyncio.run(db.async_get_reminder(rid, "u1"))["id"] == rid
    assert asyncio.run(db.async_get_reminder(rid, "u2")) is None


def test_delreminder_uses_owner_lookup_source():
    src = open(os.path.join(ROOT, "bot", "cogs", "remind.py"), encoding="utf-8").read()
    assert "async_get_reminder(reminder_id, str(ctx.author.id))" in src
    assert "async_get_user_reminders(str(ctx.author.id))" not in src.split("async def delreminder", 1)[1][:500]

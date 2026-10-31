"""P0-3 — Anti-raid unlock thật sự mở khoá, không xoá snapshot khi lỗi;
anti-nuke đọc đúng whitelist từ guild settings + immune_roles.
"""
import asyncio
import json
import os
import sys
import types

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COGS_DIR = os.path.join(BASE_DIR, "bot", "cogs")
sys.path.insert(0, _COGS_DIR)
try:
    import automod as am  # noqa: E402
finally:
    sys.path.remove(_COGS_DIR)


class Role:
    def __init__(self, rid):
        self.id = rid
        self.name = f"role-{rid}"


class Channel:
    def __init__(self, cid, fail=False):
        self.id = cid
        self.name = f"ch-{cid}"
        self.fail = fail
        self.calls = []

    async def set_permissions(self, target, overwrite=None, reason=None):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append((target.id, overwrite))


class Guild:
    def __init__(self, cid=10, fail=False):
        self.id = 123
        self.owner_id = 1
        self.name = "Guild"
        self.default_role = Role(999)
        self.channel = Channel(cid, fail=fail)

    def get_channel(self, cid):
        return self.channel if cid == self.channel.id else None


def _run(coro):
    return asyncio.run(coro)


def _patch_update(monkeypatch):
    recorded = {}

    async def fake_update(guild_id, **fields):
        recorded.update(fields)

    monkeypatch.setattr(am, "async_update_automod_settings", fake_update)
    return recorded


SNAPSHOT = [{"channel_id": "10", "overwrite": {"send_messages": False}}]


def test_raidunlock_restores_list_snapshot(monkeypatch, temp_db):
    recorded = _patch_update(monkeypatch)
    guild = Guild()
    self_obj = types.SimpleNamespace(raid_locked_guilds={"123"})

    restored, failed = _run(am.Automod._unlock_guild(
        self_obj, guild, {"raid_snapshot": SNAPSHOT, "raid_locked": 1}))

    assert (restored, failed) == (1, 0)
    assert guild.channel.calls and guild.channel.calls[0][0] == 999
    assert recorded.get("raid_locked") == 0
    assert recorded.get("raid_snapshot") == "[]"
    assert "123" not in self_obj.raid_locked_guilds


def test_raidunlock_keeps_lockdown_when_restore_fails(monkeypatch, temp_db):
    recorded = _patch_update(monkeypatch)
    guild = Guild(fail=True)
    self_obj = types.SimpleNamespace(raid_locked_guilds={"123"})

    restored, failed = _run(am.Automod._unlock_guild(
        self_obj, guild, {"raid_snapshot": SNAPSHOT, "raid_locked": 1}))

    assert (restored, failed) == (0, 1)
    assert recorded.get("raid_locked") == 1, "restore lỗi thì phải giữ lockdown"
    assert json.loads(recorded.get("raid_snapshot")) == SNAPSHOT
    assert "123" in self_obj.raid_locked_guilds


def test_raidunlock_accepts_legacy_json_string(monkeypatch, temp_db):
    _patch_update(monkeypatch)
    guild = Guild()
    self_obj = types.SimpleNamespace(raid_locked_guilds={"123"})

    restored, failed = _run(am.Automod._unlock_guild(
        self_obj, guild,
        {"raid_snapshot": json.dumps(SNAPSHOT), "raid_locked": 1}))

    assert (restored, failed) == (1, 0)


def test_trigger_lockdown_does_not_overwrite_existing_snapshot(monkeypatch, temp_db):
    recorded = _patch_update(monkeypatch)
    called = {"lockdown": 0}

    async def fake_lockdown(guild):
        called["lockdown"] += 1
        return "[]"

    async def fake_lang(guild):
        return {}

    async def fake_log(*args, **kwargs):
        return None

    self_obj = types.SimpleNamespace(
        raid_locked_guilds=set(),
        _lockdown_guild=fake_lockdown,
        _reason_lang=fake_lang,
        _log_automod=fake_log,
    )
    guild = types.SimpleNamespace(id=123)

    _run(am.Automod._trigger_raid_lockdown(
        self_obj, guild, {"raid_locked": 1, "raid_action": "lockdown"}, 10))

    assert called["lockdown"] == 0, "đã lockdown trong DB thì không được snapshot lại"
    assert recorded == {}
    assert "123" in self_obj.raid_locked_guilds


class Member:
    def __init__(self, uid, role_ids, administrator=False):
        self.id = uid
        self.roles = [Role(rid) for rid in role_ids]
        self.guild_permissions = types.SimpleNamespace(administrator=administrator)


class NukeGuild:
    def __init__(self, member):
        self.id = 123
        self.owner_id = 1
        self.member = member

    def get_member(self, uid):
        return self.member if self.member.id == uid else None


def test_anti_nuke_exempt_reads_bot_admin_roles_from_guild_settings(monkeypatch, temp_db):
    member = Member(2, [55])
    guild = NukeGuild(member)

    async def fake_guild_settings(guild_id):
        return {"bot_admin_roles": json.dumps(["55"])}

    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)

    exempt = _run(am.Automod._is_nuke_actor_exempt(
        types.SimpleNamespace(), guild, member, {"immune_roles": []}))

    assert exempt is True


def test_anti_nuke_exempt_reads_immune_roles(monkeypatch, temp_db):
    member = Member(2, [66])
    guild = NukeGuild(member)

    async def fake_guild_settings(guild_id):
        return {"bot_admin_roles": "[]"}

    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)

    exempt = _run(am.Automod._is_nuke_actor_exempt(
        types.SimpleNamespace(), guild, member, {"immune_roles": ["66"]}))

    assert exempt is True


def test_anti_nuke_denies_unlisted_moderator(monkeypatch, temp_db):
    member = Member(2, [77])
    guild = NukeGuild(member)

    async def fake_guild_settings(guild_id):
        return {"bot_admin_roles": "[]"}

    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)

    exempt = _run(am.Automod._is_nuke_actor_exempt(
        types.SimpleNamespace(), guild, member, {"immune_roles": []}))

    assert exempt is False


def test_raidunlock_invalid_channel_id_does_not_crash(monkeypatch, temp_db):
    """Snapshot hỏng (channel_id không phải số) không được làm sập /automods raidunlock."""
    recorded = _patch_update(monkeypatch)
    guild = Guild()
    self_obj = types.SimpleNamespace(raid_locked_guilds={"123"})
    snapshot = [{"channel_id": "not-a-number", "overwrite": {}}, SNAPSHOT[0]]

    restored, failed = _run(am.Automod._unlock_guild(
        self_obj, guild, {"raid_snapshot": snapshot, "raid_locked": 1}))

    assert (restored, failed) == (1, 1)
    assert guild.channel.calls and guild.channel.calls[0][0] == 999
    assert recorded.get("raid_locked") == 1, "còn entry lỗi thì phải giữ lockdown"
    assert json.loads(recorded.get("raid_snapshot")) == snapshot
    assert "123" in self_obj.raid_locked_guilds

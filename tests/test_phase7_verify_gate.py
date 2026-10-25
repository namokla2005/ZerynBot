"""P0-2 — Verify Gate: không fallback @everyone, chặn role vượt hierarchy,
disable không dừng giữa chừng, button không báo thành công khi gán role lỗi.
"""
import asyncio
import json
import os
import sys
import types

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COGS_DIR = os.path.join(BASE_DIR, "bot", "cogs")
# Chỉ thêm tạm để import verify; giữ bot/cogs trên sys.path sẽ shadow package
# `bot.music` bằng module `bot/cogs/music.py` và làm hỏng test load extension.
sys.path.insert(0, _COGS_DIR)
try:
    import verify as vf  # noqa: E402
finally:
    sys.path.remove(_COGS_DIR)


class Role:
    def __init__(self, rid, position, managed=False, default=False):
        self.id = rid
        self.position = position
        self.managed = managed
        self._default = default
        self.name = f"role-{rid}"
        self.mention = f"<@&{rid}>"

    def is_default(self):
        return self._default


class Channel:
    def __init__(self, cid, fail=False):
        self.id = cid
        self.name = f"ch-{cid}"
        self.fail = fail
        self.calls = []

    def overwrites_for(self, role):
        return None

    async def set_permissions(self, target, overwrite=None, reason=None):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append((target.id, overwrite))


class Member:
    def __init__(self, uid, top_position, roles=None):
        self.id = uid
        self.bot = False
        self.top_role = Role(uid * 10, top_position)
        self.roles = list(roles or [])
        self.added = []
        self.removed = []

    async def add_roles(self, *roles, reason=None):
        self.added.extend(roles)

    async def remove_roles(self, *roles, reason=None):
        self.removed.extend(roles)


class Guild:
    def __init__(self, channels, roles=None, members=None):
        self.id = 123
        self.owner_id = 1
        self.name = "Guild"
        self.default_role = Role(999, 0, default=True)
        self.me = types.SimpleNamespace(top_role=Role(888, 100))
        self.channels = list(channels)
        self.members = list(members or [])
        self._roles = {r.id: r for r in (roles or [])}
        self._channels = {c.id: c for c in channels}

    def get_role(self, rid):
        return self._roles.get(rid)

    def get_channel(self, cid):
        return self._channels.get(cid)


class Ctx:
    def __init__(self, guild, author=None):
        self.guild = guild
        self.author = author or Member(2, 10)
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def _run(coro):
    return asyncio.run(coro)


def test_apply_hard_gate_snapshots_target_role(temp_db):
    guild = Guild([Channel(10), Channel(11)])
    ctx = Ctx(guild)
    snapshots, errors = _run(vf.Verify._apply_hard_gate(
        types.SimpleNamespace(), ctx, Role(777, 1), guild.get_channel(10)))

    assert errors == 0
    assert len(snapshots) == 2
    assert all(s["target_id"] == "777" for s in snapshots), snapshots


def test_restore_uses_snapshot_target_not_everyone(monkeypatch, temp_db):
    ch = Channel(10)
    target = Role(777, 1)
    guild = Guild([ch], [target])
    settings = {
        "saved_overrides": json.dumps([{
            "channel_id": "10", "target_id": "777",
            "overwrite": {"view_channel": False},
        }]),
        "pending_role_id": "777",
    }

    async def fake_get(guild_id):
        return settings

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    restored, failed = _run(vf.Verify._restore_gate(types.SimpleNamespace(), Ctx(guild)))

    assert (restored, failed) == (1, 0)
    assert ch.calls and ch.calls[0][0] == 777, ch.calls
    assert all(target_id != 999 for target_id, _ in ch.calls), "không được chạm @everyone"


def test_restore_skips_when_target_role_is_gone(monkeypatch, temp_db):
    ch = Channel(10)
    guild = Guild([ch], [])
    settings = {
        "saved_overrides": json.dumps([{
            "channel_id": "10", "target_id": "777", "overwrite": None,
        }]),
        "pending_role_id": "777",
    }

    async def fake_get(guild_id):
        return settings

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    restored, failed = _run(vf.Verify._restore_gate(types.SimpleNamespace(), Ctx(guild)))

    assert (restored, failed) == (0, 0)
    assert ch.calls == [], "pending role đã mất thì phải bỏ qua, không fallback @everyone"


def test_restore_skips_legacy_snapshot_without_target_id(monkeypatch, temp_db):
    ch = Channel(10)
    guild = Guild([ch], [])
    settings = {
        "saved_overrides": json.dumps([{"channel_id": "10", "overwrite": None}]),
        "pending_role_id": None,
    }

    async def fake_get(guild_id):
        return settings

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    restored, failed = _run(vf.Verify._restore_gate(types.SimpleNamespace(), Ctx(guild)))

    assert (restored, failed) == (0, 0)
    assert ch.calls == []


def test_restore_counts_permission_failures(monkeypatch, temp_db):
    ch = Channel(10, fail=True)
    guild = Guild([ch], [Role(777, 1)])
    settings = {
        "saved_overrides": json.dumps([{
            "channel_id": "10", "target_id": "777", "overwrite": None,
        }]),
        "pending_role_id": "777",
    }

    async def fake_get(guild_id):
        return settings

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    restored, failed = _run(vf.Verify._restore_gate(types.SimpleNamespace(), Ctx(guild)))

    assert (restored, failed) == (0, 1)


def _patch_settings(monkeypatch, settings):
    async def fake_get(guild_id):
        return settings

    async def fake_guild_settings(guild_id):
        return {}

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    monkeypatch.setattr(vf, "async_get_guild_settings", fake_guild_settings)


def _stored_settings(monkeypatch):
    stored = {}

    async def fake_upsert(guild_id, **fields):
        stored.update(fields)

    monkeypatch.setattr(vf, "async_upsert_verify_settings", fake_upsert)
    return stored


def test_verify_role_rejects_role_at_or_above_author_top(monkeypatch, temp_db):
    _patch_settings(monkeypatch, {})
    stored = _stored_settings(monkeypatch)
    high = Role(666, 10)
    guild = Guild([], [high])
    ctx = Ctx(guild, Member(2, 10))

    _run(vf.Verify.verify_role.callback(types.SimpleNamespace(), ctx, high))

    assert "verified_role_id" not in stored
    assert ctx.sent, "phải báo lỗi cho người dùng"


def test_verify_role_rejects_managed_and_everyone(monkeypatch, temp_db):
    _patch_settings(monkeypatch, {})
    stored = _stored_settings(monkeypatch)
    managed = Role(777, 5, managed=True)
    guild = Guild([], [managed])
    ctx = Ctx(guild, Member(2, 10))

    _run(vf.Verify.verify_role.callback(types.SimpleNamespace(), ctx, managed))
    _run(vf.Verify.verify_role.callback(types.SimpleNamespace(), ctx, guild.default_role))

    assert "verified_role_id" not in stored


def test_verify_role_rejects_role_above_bot_top(monkeypatch, temp_db):
    _patch_settings(monkeypatch, {})
    stored = _stored_settings(monkeypatch)
    too_high = Role(555, 100)
    guild = Guild([], [too_high])
    ctx = Ctx(guild, Member(2, 200))

    _run(vf.Verify.verify_role.callback(types.SimpleNamespace(), ctx, too_high))

    assert "verified_role_id" not in stored


def test_verify_role_accepts_role_below_author_top(monkeypatch, temp_db):
    _patch_settings(monkeypatch, {})
    stored = _stored_settings(monkeypatch)
    ok_role = Role(555, 5)
    guild = Guild([], [ok_role])
    ctx = Ctx(guild, Member(2, 10))

    _run(vf.Verify.verify_role.callback(types.SimpleNamespace(), ctx, ok_role))

    assert stored.get("verified_role_id") == "555"


def test_verify_disable_continues_after_one_member_fails(monkeypatch, temp_db):
    pending = Role(777, 1)
    first = Member(1, 5, [pending])
    second = Member(2, 5, [pending])

    async def fail_remove(*roles, reason=None):
        raise RuntimeError("Forbidden-like")

    first.remove_roles = fail_remove
    guild = Guild([], [pending], [first, second])
    _patch_settings(monkeypatch, {"pending_role_id": "777"})
    stored = _stored_settings(monkeypatch)

    async def fake_restore(ctx):
        return (2, 0)

    ctx = Ctx(guild, Member(3, 10))
    self_obj = types.SimpleNamespace(_restore_gate=fake_restore)

    _run(vf.Verify.verify_disable.callback(self_obj, ctx))

    assert pending in second.removed, "member sau không được bị bỏ qua"
    assert stored.get("enabled") == 0


def test_verify_button_does_not_report_success_when_role_add_fails(monkeypatch, temp_db):
    verified = Role(555, 5)
    pending = Role(777, 1)
    member = Member(2, 5, [pending])

    async def fail_add(*roles, reason=None):
        raise RuntimeError("Forbidden-like")

    member.add_roles = fail_add
    guild = Guild([], [verified, pending])

    class Resp:
        def __init__(self):
            self.deferred = False

        async def defer(self, ephemeral=False):
            self.deferred = True

    class Followup:
        def __init__(self):
            self.sent = []

        async def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    class Interaction:
        def __init__(self):
            self.guild = guild
            self.user = member
            self.response = Resp()
            self.followup = Followup()

    async def fake_get(guild_id):
        return {"enabled": 1, "verified_role_id": "555", "pending_role_id": "777"}

    async def fake_guild_settings(guild_id):
        return {}

    monkeypatch.setattr(vf, "async_get_verify_settings", fake_get)
    monkeypatch.setattr(vf, "async_get_guild_settings", fake_guild_settings)

    view = vf.VerifyView(None, {})
    interaction = Interaction()
    _run(view.verify_button.callback(interaction))

    assert member.removed == [], "không được gỡ pending khi chưa gán được verified role"
    assert interaction.followup.sent, "phải báo lỗi thay vì im lặng"
    assert "Không gán được" in str(interaction.followup.sent[-1])

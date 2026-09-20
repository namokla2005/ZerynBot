"""
test_checks_dual_mode.py — Kiểm tra bộ check dùng chung `bot/checks.py`.

Vì sao cần: cùng một predicate được discord.py gọi bằng `commands.Context` (đường
prefix + "baton" của hybrid) và bằng `discord.Interaction` (check đăng ký qua
`@app_commands.check`). Nếu check chỉ đọc `ctx.author` thì đường slash sẽ nổ
AttributeError, còn nếu ném sai loại CheckFailure thì Discord chỉ hiện
"interaction failed" thay vì thông báo từ chối.
"""
import asyncio

import pytest
from discord.ext import commands
from discord import app_commands

import checks


# ─── Fake Context / Interaction (đủ để chạy check, không cần mạng) ────────────

class FakePermissions:
    def __init__(self, **kwargs):
        self._perms = {
            "administrator": False,
            "manage_guild": False,
            "manage_roles": False,
            "manage_messages": False,
        }
        self._perms.update(kwargs)

    def __getattr__(self, item):
        return self._perms.get(item, False)


class FakeRole:
    def __init__(self, role_id):
        self.id = role_id


class FakeGuild:
    def __init__(self, guild_id=123, owner_id=999):
        self.id = guild_id
        self.owner_id = owner_id

    def get_role(self, role_id):
        return None


class FakeMember:
    def __init__(self, user_id=1, perms=None, role_ids=(), guild=None):
        self.id = user_id
        self.guild_permissions = FakePermissions(**(perms or {}))
        self.roles = [FakeRole(r) for r in role_ids]
        self.guild = guild
        self.display_name = f"user{user_id}"


class FakeContext:
    """Đủ giống `commands.Context` cho các check của chúng ta.

    `permissions` là property thật của `commands.Context` (quyền của tác giả
    trong kênh hiện tại) nên fake cũng cung cấp nó.
    """

    def __init__(self, guild, member):
        self.guild = guild
        self.author = member
        self.channel = None
        self.permissions = getattr(member, "guild_permissions", None) if member else None


class FakeInteraction:
    """Đủ giống `discord.Interaction` — chú ý: KHÔNG phải instance thật.

    `permissions` là thuộc tính thật của `discord.Interaction` (quyền của người gọi
    trong kênh), nên fake cũng phải có để phần kiểm quyền chạy đúng.
    """

    def __init__(self, guild, member):
        self.guild = guild
        self.user = member
        self.channel = None
        self.permissions = getattr(member, "guild_permissions", None) if member else None


@pytest.fixture()
def no_whitelist(monkeypatch):
    """Guild settings rỗng: không cấu hình `bot_admin_roles`."""
    async def fake_settings(guild_id):
        return {}

    monkeypatch.setattr(checks.db, "async_get_guild_settings", fake_settings)
    return {}


@pytest.fixture()
def whitelist(monkeypatch):
    """Guild settings có whitelist role 555."""
    async def fake_settings(guild_id):
        return {"bot_admin_roles": "[555]"}

    monkeypatch.setattr(checks.db, "async_get_guild_settings", fake_settings)
    return {"bot_admin_roles": "[555]"}


def _run(coro):
    return asyncio.run(coro)


# Loại exception từ chối phải khớp với loại target: Context → commands.CheckFailure,
# Interaction → app_commands.CheckFailure (nếu sai loại, Discord chỉ hiện
# "interaction failed" thay vì thông báo từ chối).
EXPECTED_DENY = {
    FakeContext: commands.CheckFailure,
    FakeInteraction: app_commands.CheckFailure,
}


# ─── check_bot_admin ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_server_owner_allowed(make_target):
    guild = FakeGuild(owner_id=7)
    target = make_target(guild, FakeMember(user_id=7, guild=guild))
    assert _run(checks.check_bot_admin(target)) is True


@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_administrator_allowed(make_target):
    guild = FakeGuild(owner_id=7)
    member = FakeMember(user_id=8, perms={"administrator": True}, guild=guild)
    assert _run(checks.check_bot_admin(make_target(guild, member))) is True


def test_whitelisted_role_allowed(whitelist):
    guild = FakeGuild(owner_id=7)
    member = FakeMember(user_id=8, role_ids=(555,), guild=guild)
    assert _run(checks.check_bot_admin(FakeContext(guild, member))) is True


def test_missing_whitelisted_role_denied_on_both_paths(whitelist):
    guild = FakeGuild(owner_id=7)
    member = FakeMember(user_id=8, role_ids=(999,), guild=guild)

    # Đường prefix → commands.CheckFailure
    with pytest.raises(commands.CheckFailure):
        _run(checks.check_bot_admin(FakeContext(guild, member)))

    # Đường slash → app_commands.CheckFailure (khác hẳn loại ở trên)
    with pytest.raises(app_commands.CheckFailure):
        _run(checks.check_bot_admin(FakeInteraction(guild, member)))


def test_manage_guild_fallback_when_no_whitelist(no_whitelist):
    guild = FakeGuild(owner_id=7)
    member = FakeMember(user_id=8, perms={"manage_guild": True}, guild=guild)
    assert _run(checks.check_bot_admin(FakeContext(guild, member))) is True


def test_no_permission_denied_when_no_whitelist(no_whitelist):
    guild = FakeGuild(owner_id=7)
    member = FakeMember(user_id=8, guild=guild)
    with pytest.raises(commands.CheckFailure):
        _run(checks.check_bot_admin(FakeContext(guild, member)))


@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_dm_context_denied(make_target):
    member = FakeMember(user_id=8)
    assert _run(checks.check_bot_admin(make_target(None, member))) is False


# ─── admin_only / manage_guild_only / manage_roles_only ───────────────────────

@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_manage_roles_only(make_target):
    guild = FakeGuild()
    ok_member = FakeMember(user_id=1, perms={"manage_roles": True}, guild=guild)
    assert _run(checks.check_manage_roles(make_target(guild, ok_member))) is True

    bad_member = FakeMember(user_id=2, guild=guild)
    with pytest.raises(EXPECTED_DENY[make_target]):
        _run(checks.check_manage_roles(make_target(guild, bad_member)))


@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_admin_only(make_target):
    guild = FakeGuild()
    ok_member = FakeMember(user_id=1, perms={"administrator": True}, guild=guild)
    assert _run(checks.check_administrator(make_target(guild, ok_member))) is True

    bad_member = FakeMember(user_id=2, guild=guild)
    with pytest.raises(EXPECTED_DENY[make_target]):
        _run(checks.check_administrator(make_target(guild, bad_member)))


@pytest.mark.parametrize("make_target", [FakeContext, FakeInteraction])
def test_manage_guild_only(make_target):
    guild = FakeGuild()
    ok_member = FakeMember(user_id=1, perms={"manage_guild": True}, guild=guild)
    assert _run(checks.check_manage_guild(make_target(guild, ok_member))) is True

    bad_member = FakeMember(user_id=2, guild=guild)
    with pytest.raises(EXPECTED_DENY[make_target]):
        _run(checks.check_manage_guild(make_target(guild, bad_member)))


# ─── dual_check: đăng ký check cho cả hai đường ───────────────────────────────

@pytest.mark.parametrize(
    "decorator",
    [checks.is_bot_admin, checks.admin_only, checks.manage_guild_only, checks.manage_roles_only],
)
def test_dual_check_registers_both_paths(decorator):
    async def dummy(ctx):
        return True

    decorated = decorator()(dummy)
    prefix_checks = getattr(decorated, "__commands_checks__", [])
    app_checks = getattr(decorated, "__discord_app_commands_checks__", [])

    assert len(prefix_checks) == 1, f"{decorator.__name__} thiếu check đường prefix"
    assert len(app_checks) == 1, f"{decorator.__name__} thiếu check đường slash"
    assert prefix_checks[0] is app_checks[0], "Hai đường phải dùng cùng một predicate"

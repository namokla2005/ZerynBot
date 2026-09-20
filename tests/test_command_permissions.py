"""
test_command_permissions.py — Chốt chặn phân quyền (P0).

Bối cảnh: `discord/ext/commands/core.py::Command.can_run` CHỈ chạy `self.checks`
của CHÍNH lệnh đó — nó không duyệt check của group cha. Trước đây check được gắn
trên `@commands.hybrid_group(...)` (vd `xp`, `giveaway`, `automods`, `verify`) nên
mọi lệnh con (`/verify disable`, `/xp add`, `/automods raidlock`, ...) mở cho bất
kỳ thành viên nào trên cả hai đường prefix và slash.

Test này khoá lại quy tắc: lệnh con nhạy cảm PHẢI tự mang check, ở CẢ hai danh
sách (`__commands_checks__` cho đường prefix và `__discord_app_commands_checks__`
cho đường slash).
"""
import asyncio
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGS_DIR = os.path.join(BASE_DIR, "bot", "cogs")

# ─── Lệnh con BẮT BUỘC phải có check ──────────────────────────────────────────
# group -> {tên lệnh con}
SENSITIVE_CHILDREN = {
    "xp": {"add", "set", "reset"},
    "giveaway": {"start", "end", "reroll"},
    "automods": {"show", "raidlock", "raidunlock"},
    "autorole": {"show"},
    "verify": {
        "status", "enable", "disable", "channel",
        "role", "pending", "hide", "text", "button", "panel",
    },
}

# Lệnh cấp cao khác phải có check (khoá lại hiện trạng để không bị nới lỏng sau này).
MUST_BE_GATED = {
    "config", "reactionroles", "sync", "ticket",
    "leaderboard", "rank", "lang", "membercount",
    "serverinfo", "userinfo", "roleinfo", "channelinfo",
    "xp", "giveaway", "automods", "autorole", "verify",
}

# Lệnh tự kiểm quyền bên trong callback (không dùng decorator check).
# `backup` tự so `ctx.author.id != config.BOT_OWNER_ID` rồi mới chạy.
SELF_GUARDED = {"backup"}


@pytest.fixture(scope="module")
def loaded_bot():
    """Load toàn bộ cog lên Bot giả (không login, không network)."""
    import discord
    from discord.ext import commands, tasks

    tasks.Loop.start = lambda self, *a, **k: None  # chặn task loop tự chạy

    bot = commands.Bot(
        command_prefix=commands.when_mentioned,
        intents=discord.Intents.none(),
        help_command=None,
    )

    async def load_all():
        for f in sorted(os.listdir(COGS_DIR)):
            if f.endswith(".py") and not f.startswith("_"):
                await bot.load_extension(f"cogs.{f[:-3]}")

    asyncio.run(load_all())
    yield bot
    if not bot.is_closed():
        asyncio.run(bot.close())


def _commands_by_name(bot) -> dict:
    return {c.qualified_name: c for c in bot.walk_commands()}


def test_sensitive_subcommands_have_own_checks(loaded_bot):
    """Lệnh con nhạy cảm phải mang check ở CẢ hai đường (prefix + slash)."""
    commands_by_name = _commands_by_name(loaded_bot)
    missing = []

    for group, children in SENSITIVE_CHILDREN.items():
        for child in sorted(children):
            qualified = f"{group} {child}"
            cmd = commands_by_name.get(qualified)
            if cmd is None:
                missing.append(f"{qualified}: KHÔNG TỒN TẠI")
                continue

            prefix_checks = len(cmd.checks)
            app_cmd = getattr(cmd, "app_command", None)
            app_checks = len(getattr(app_cmd, "checks", []) or [])

            if prefix_checks == 0:
                missing.append(f"{qualified}: thiếu check đường prefix")
            if app_checks == 0:
                missing.append(f"{qualified}: thiếu check đường slash")

    assert not missing, (
        "Lệnh con hybrid đang hở phân quyền (check của group KHÔNG áp cho lệnh con):\n  - "
        + "\n  - ".join(missing)
    )


def test_group_checks_do_not_replace_child_checks(loaded_bot):
    """Ghi lại lý do bug từng tồn tại: group CÓ check nhưng con vẫn phải tự có."""
    commands_by_name = _commands_by_name(loaded_bot)
    for group in SENSITIVE_CHILDREN:
        group_cmd = commands_by_name.get(group)
        assert group_cmd is not None, f"Thiếu group {group}"
        assert len(group_cmd.checks) > 0, f"Group {group} mất check"
        # `when_mentioned` là đường prefix duy nhất; nếu ai đó thêm lại "/" thì
        # `app_commands.default_permissions` (chỉ chặn ở UI Discord) sẽ bị vòng qua.
        for child in group_cmd.commands:
            assert len(child.checks) > 0, (
                f"{child.qualified_name} không có check nào — group check không giúp gì!"
            )


def test_admin_level_commands_stay_gated(loaded_bot):
    """Các lệnh quản trị cấp cao không được rơi mất check khi refactor."""
    commands_by_name = _commands_by_name(loaded_bot)
    ungated = []

    for name in sorted(MUST_BE_GATED):
        cmd = commands_by_name.get(name)
        if cmd is None:
            ungated.append(f"{name}: KHÔNG TỒN TẠI")
            continue
        if len(cmd.checks) == 0 and name not in SELF_GUARDED:
            ungated.append(f"{name}: checks=0")

    assert not ungated, "Lệnh quản trị bị mất check:\n  - " + "\n  - ".join(ungated)


def test_bot_prefix_is_mention_only():
    """Prefix phải là @mention — KHÔNG nhận '/' (tránh gọi lệnh qua tin nhắn thường)."""
    src = open(os.path.join(BASE_DIR, "bot", "bot.py"), encoding="utf-8").read()
    assert "command_prefix=commands.when_mentioned," in src
    assert 'when_mentioned_or("/")' not in src

"""P2-A — Sinh nhật 29/02, temp role bền qua restart, level role không mất role cũ."""
import asyncio
import os
import sys
import time
import types
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_COGS = os.path.join(ROOT, "bot", "cogs")
sys.path.insert(0, _COGS)
try:
    import birthday as bday_mod  # noqa: E402
    import leveling as lvl_mod  # noqa: E402
finally:
    sys.path.remove(_COGS)


def test_next_occurrence_handles_feb_29():
    assert bday_mod._next_occurrence(2, 29, datetime(2026, 1, 1, tzinfo=timezone.utc)).strftime("%Y-%m-%d") == "2026-02-28"
    assert bday_mod._next_occurrence(2, 29, datetime(2028, 1, 1, tzinfo=timezone.utc)).strftime("%Y-%m-%d") == "2028-02-29"
    assert bday_mod._next_occurrence(2, 29, datetime(2026, 3, 1, tzinfo=timezone.utc)).strftime("%Y-%m-%d") == "2027-02-28"


def test_temp_role_crud_and_attempt_cap(temp_db):
    import database as db

    asyncio.run(db.async_add_temp_role("g1", "u1", "r1", time.time() - 10))
    rows = asyncio.run(db.async_get_expired_temp_roles(time.time(), limit=10))
    assert len(rows) == 1
    row_id = rows[0]["id"]

    assert asyncio.run(db.async_fail_temp_role(row_id, 3)) is False
    assert asyncio.run(db.async_fail_temp_role(row_id, 3)) is False
    assert asyncio.run(db.async_fail_temp_role(row_id, 3)) is True
    assert asyncio.run(db.async_get_expired_temp_roles(time.time(), limit=10)) == []


def test_birthday_settings_rejects_unknown_columns(temp_db):
    import database as db

    asyncio.run(db.async_upsert_birthday_settings("g1", gift_coins=123, evil_column="x"))
    row = asyncio.run(db.async_get_birthday_settings("g1"))
    assert row["gift_coins"] == 123
    assert "evil_column" not in row


class Role:
    def __init__(self, rid, position):
        self.id = rid
        self.position = position

    def __lt__(self, other):
        return self.position < other.position

    def __ge__(self, other):
        return self.position >= other.position


class Member:
    def __init__(self, guild):
        self.id = 42
        self.guild = guild
        self.calls = []

    async def add_roles(self, *roles, reason=None):
        self.calls.append(("add", [r.id for r in roles]))

    async def remove_roles(self, *roles, reason=None):
        self.calls.append(("remove", [r.id for r in roles]))


def _guild(top_position=100, manage_roles=True):
    g = types.SimpleNamespace(id=1)
    g.me = types.SimpleNamespace(
        top_role=Role(999, top_position),
        guild_permissions=types.SimpleNamespace(manage_roles=manage_roles),
    )
    return g


def test_level_roles_add_before_remove():
    # apply_level_roles import module-level; dùng asyncio.run
    guild = _guild()
    member = Member(guild)
    old = Role(10, 10)
    new = Role(20, 20)

    asyncio.run(lvl_mod.apply_level_roles(member, [new], [old]))
    assert member.calls == [("add", [20]), ("remove", [10])]


def test_level_roles_keep_old_when_new_role_too_high():
    guild = _guild(top_position=30)
    member = Member(guild)
    old = Role(10, 10)
    too_high = Role(20, 30)

    asyncio.run(lvl_mod.apply_level_roles(member, [too_high], [old]))
    assert member.calls == [], "không gán được role mới thì không được gỡ role cũ"


def test_level_roles_keep_old_when_add_raises():
    guild = _guild()
    member = Member(guild)
    old = Role(10, 10)
    new = Role(20, 20)

    async def fail_add(*roles, reason=None):
        raise RuntimeError("Forbidden-like")

    member.add_roles = fail_add

    asyncio.run(lvl_mod.apply_level_roles(member, [new], [old]))
    assert member.calls == []

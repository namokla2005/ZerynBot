"""P4-D — Đếm sinh nhật theo member guild; các chuỗi user-visible còn hardcode."""
import asyncio
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_birthday_count_filters_by_guild_members(temp_db):
    import database as db

    for uid in ("u1", "u2", "u3"):
        asyncio.run(db.async_set_birthday(uid, 15, 6))
    assert db.get_birthdays_this_month_count("g1", 6) == 3
    assert db.get_birthdays_this_month_count("g1", 6, ["u1", "u3"]) == 2
    assert db.get_birthdays_this_month_count("g1", 6, []) == 0


def test_guild_member_ids_are_cached(monkeypatch):
    from dashboard import auth

    calls = []

    class Resp:
        ok = True

        def json(self):
            return [
                {"user": {"id": "1"}},
                {"user": {"id": "2"}},
            ]

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return Resp()

    monkeypatch.setattr(auth.requests, "get", fake_get)
    auth._member_ids_cache.clear()

    assert auth.get_guild_member_ids("g1") == ["1", "2"]
    assert auth.get_guild_member_ids("g1") == ["1", "2"]
    assert len(calls) == 1, "phải cache, không gọi Discord mỗi page load"


def test_guild_member_ids_failure_returns_none(monkeypatch):
    from dashboard import auth

    class Resp:
        ok = False
        status_code = 403

    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: Resp())
    auth._member_ids_cache.clear()
    assert auth.get_guild_member_ids("g2") is None


def test_verify_label_and_help_strings_use_i18n():
    verify = _read("bot/cogs/verify.py")
    utility = _read("bot/cogs/utility.py")
    giveaway = _read("bot/cogs/giveaway.py")
    assert 'tr(s, "verify.nut_xac_thuc")' in verify
    assert 'tr(settings, "help.required")' in utility
    assert 'tr(settings, "help.optional")' in utility
    assert 't("giveaway.btn_ended")' in giveaway

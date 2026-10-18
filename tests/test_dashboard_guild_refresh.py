# -*- coding: utf-8 -*-
"""O4 — dashboard chi goi Discord MOT lan khi danh sach guild het han, khong phai 4.

Bat bien: 4 endpoint poll cung luc trong mot lan refresh thi Discord chi phai chiu
1 round-trip (rate-limit theo token that, 429 la treo dashboard).
"""
import time

import pytest

from dashboard import api as api_mod
from dashboard import auth as _auth


@pytest.fixture(autouse=True)
def _clean_memo():
    # Khoan tham chieu thang thuoc tinh moi: test hanh vi (do qua HTTP) phai chay duoc
    # ca tren ban code cu de that do bang SO LAN GOI, khong chet vi thieu attribute.
    memo = getattr(api_mod, "_guild_refresh_memo", None)
    if memo is not None:
        memo.clear()
    yield
    if memo is not None:
        memo.clear()


class _Counter:
    def __init__(self, payload):
        self.calls = []
        self.payload = payload

    def __call__(self, token):
        self.calls.append(token)
        return self.payload


def test_two_rapid_refreshes_cost_one_discord_call(monkeypatch):
    fake = _Counter([{"id": "1", "bot_in_guild": True}])
    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)

    a = api_mod._refresh_guilds_once("tok-a", "secret-a")
    b = api_mod._refresh_guilds_once("tok-a", "secret-a")

    assert a == b == [{"id": "1", "bot_in_guild": True}]
    assert len(fake.calls) == 1, f"phai dung memo, thuc te goi {len(fake.calls)} lan"


def test_memo_is_keyed_by_token_not_shared_across_users(monkeypatch):
    fake = _Counter([{"id": "1"}])
    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)

    api_mod._refresh_guilds_once("tok-a", "secret-a")
    api_mod._refresh_guilds_once("tok-b", "secret-b")

    assert len(fake.calls) == 2, "hai phien khong duoc dung lan danh sach guild cua nhau"


def test_expired_memo_refreshes_again(monkeypatch):
    fake = _Counter([{"id": "1"}])
    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)

    api_mod._refresh_guilds_once("tok-c", "secret-c")
    api_mod._guild_refresh_memo["tok-c"] = (time.time() - api_mod._GUILD_REFRESH_MEMO_TTL - 1, [])
    api_mod._refresh_guilds_once("tok-c", "secret-c")

    assert len(fake.calls) == 2


def test_busy_lock_returns_stale_instead_of_waiting(monkeypatch):
    """Thread den sau khong block theo network call — no dung list cu va buoc sau se retry."""
    fake = _Counter([{"id": "new"}])
    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)
    api_mod._guild_refresh_memo["tok-d"] = (time.time() - 999, [{"id": "old"}])
    assert api_mod._guild_refresh_lock.acquire(blocking=False)
    try:
        got = api_mod._refresh_guilds_once("tok-d", "secret-d")
    finally:
        api_mod._guild_refresh_lock.release()

    assert got == [{"id": "old"}], "phai tra ban cu nhat trong memo, khong goi Discord"
    assert fake.calls == []


def test_secret_token_never_enters_the_memo(monkeypatch):
    """Memo key phai la oauth_token_id (con tro vault), khong bao gio la access token."""
    fake = _Counter([{"id": "1"}])
    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)

    api_mod._refresh_guilds_once("pointer-123", "super-secret-token")

    assert "super-secret-token" not in api_mod._guild_refresh_memo
    assert list(api_mod._guild_refresh_memo) == ["pointer-123"]


def test_two_api_calls_in_one_poll_cost_one_discord_refresh(client, temp_db, monkeypatch):
    """Do qua HTTP that: hai request lien tiep khi session 'cu' chi mot lan call Discord.

    Test nay do HANH VI, khong do ten ham moi — nen no that bai tren code cu (2 lan goi)
    chu khong chet vi thieu attribute.
    """
    from conftest import login, MOCK_GUILD_ID

    login(client)
    calls = []

    def fake(_token):
        calls.append(1)
        return [{"id": MOCK_GUILD_ID, "name": "g", "permissions": 8,
                 "bot_in_guild": True, "owner": True}]

    monkeypatch.setattr(_auth, "get_manageable_guilds", fake)

    for _ in range(2):
        with client.session_transaction() as s:
            s["guilds_fetched_at"] = 0        # gia vet request den cung luc thay list 'cu'
        r = client.get(f"/api/guild/{MOCK_GUILD_ID}/channels")
        assert r.status_code == 200, r.data[:200]

    assert len(calls) == 1, f"Discord phai chiu 1 round-trip, thuc te {len(calls)}"

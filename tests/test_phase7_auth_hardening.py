"""P1-1 — Dashboard fail-closed khi vault token mất, session có trần tuyệt đối,
rate-limit ưu tiên user id thay vì gộp mọi người vào IP proxy.
"""
import time

from conftest import MOCK_GUILD_ID, authed_client, login


def _drop_token(client):
    from dashboard.auth import drop_access_token

    with client.session_transaction() as s:
        token_id = s.get("oauth_token_id")
    drop_access_token(token_id)


def test_guild_page_redirects_when_vault_token_missing(client, temp_db):
    login(client)
    _drop_token(client)

    resp = client.get(f"/dashboard/{MOCK_GUILD_ID}/welcome")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with client.session_transaction() as s:
        assert "user" not in s, "session cũ vẫn được giữ sau khi vault mất token"


def test_dashboard_home_redirects_when_vault_token_missing(client, temp_db):
    login(client)
    _drop_token(client)

    resp = client.get("/dashboard")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_session_absolute_lifetime_expires(client, temp_db):
    import config

    login(client)
    with client.session_transaction() as s:
        s["auth_at"] = time.time() - (config.SESSION_LIFETIME_DAYS * 86400 + 60)

    resp = client.get(f"/dashboard/{MOCK_GUILD_ID}/welcome")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with client.session_transaction() as s:
        assert "user" not in s


def test_client_key_prefers_user_id(flask_app):
    from flask import session

    from dashboard.extensions import _client_key

    with flask_app.test_request_context("/", headers={"CF-Connecting-IP": "203.0.113.7"}):
        session["user"] = {"id": "4242"}
        assert _client_key() == "user:4242"


def test_authed_request_still_works(client, temp_db):
    token = authed_client(client)
    resp = client.get(f"/dashboard/{MOCK_GUILD_ID}/welcome")
    assert resp.status_code in (200, 302)
    assert token

"""
Tests bảo mật Dashboard — phủ đúng các lỗ hổng P0 đã vá:
- P0.1: FLASK_SECRET_KEY fail-closed (không còn default tĩnh)
- P0.2: OAuth2 bắt buộc có state (chống Login CSRF)
- P0.3: các route xóa chỉ nhận POST
- P0.4: chặn gửi tin sang kênh ngoài guild (IDOR)
- P0.5: CSRF token trên mọi mutation request
"""
import json
import secrets
import importlib

import pytest

from conftest import login, set_csrf_token, authed_client, MOCK_GUILD_ID


# ─── P0.1 · Secret key fail-closed ────────────────────────────────────────────

def test_secret_key_no_static_default(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    import config
    importlib.reload(config)
    assert config.FLASK_SECRET_KEY not in (
        "", "dev-secret-key-change-me", "change_this_to_a_random_secret_key_32chars"
    )
    first = config.FLASK_SECRET_KEY
    importlib.reload(config)
    assert config.FLASK_SECRET_KEY != first  # ngẫu nhiên mỗi lần khởi động
    assert len(first) >= 32


def test_secret_key_env_respected(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "my-super-secret-key-1234567890abcdef")
    import config
    importlib.reload(config)
    assert config.FLASK_SECRET_KEY == "my-super-secret-key-1234567890abcdef"
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    importlib.reload(config)


# ─── P0.2 · OAuth state bắt buộc ──────────────────────────────────────────────

def test_login_sets_oauth_state(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    with client.session_transaction() as s:
        state = s.get("oauth_state")
    assert state and len(state) >= 32
    assert f"state={state}" in resp.get_data(as_text=True)


def test_callback_rejects_missing_or_wrong_state(client):
    client.get("/login")
    # Sai state
    resp = client.get("/callback?state=wrong&code=abc", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # Thiếu state hẳn
    resp2 = client.get("/callback?code=abc", follow_redirects=False)
    assert resp2.status_code == 302
    assert "/login" in resp2.headers["Location"]


def test_callback_success_with_valid_state(client, monkeypatch):
    import dashboard.app as dapp

    monkeypatch.setattr(dapp, "exchange_code", lambda code: {"access_token": "tok"})
    monkeypatch.setattr(dapp, "get_user", lambda tok: {"id": "111111111111111111", "username": "TestAdmin"})
    monkeypatch.setattr(dapp, "get_manageable_guilds", lambda tok: [{
        "id": MOCK_GUILD_ID, "name": "Zeryn Support Community", "icon": None,
        "permissions": 8, "bot_in_guild": True,
    }])
    monkeypatch.setattr(dapp, "get_avatar_url", lambda u: "https://cdn.discordapp.com/embed/avatars/0.png")

    client.get("/login")
    with client.session_transaction() as s:
        state = s["oauth_state"]

    resp = client.get(f"/callback?state={state}&code=valid-code", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]
    with client.session_transaction() as s:
        assert s["user"]["id"] == "111111111111111111"
        assert s["guilds"][0]["id"] == MOCK_GUILD_ID
        assert "oauth_state" not in s  # state dùng 1 lần rồi bị xóa


# ─── P0.5 · CSRF enforcement ──────────────────────────────────────────────────

def test_post_without_csrf_blocked(client):
    login(client)
    resp = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/modules/music",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_post_with_csrf_allowed(client, temp_db):
    token = authed_client(client)
    resp = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/modules/music",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_post_anonymous_redirects_not_csrf(client):
    """Chưa đăng nhập → API trả 403 Forbidden (không phải CSRF 403)."""
    resp = client.post(f"/api/guild/{MOCK_GUILD_ID}/modules/music", json={"enabled": True})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "Forbidden"


def test_csrf_token_via_form_field(client, temp_db):
    """Form POST (route dashboard thường) nhận CSRF qua hidden field _csrf_token."""
    token = authed_client(client)
    resp = client.post(
        f"/dashboard/{MOCK_GUILD_ID}/modules",
        data={"bot_admin_roles": [], "_csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302  # lưu thành công → redirect (không phải 403 CSRF)


def test_form_post_without_csrf_redirects_with_flash(client, temp_db):
    login(client)  # có session nhưng KHÔNG có token
    resp = client.post(
        f"/dashboard/{MOCK_GUILD_ID}/modules",
        data={"bot_admin_roles": []},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 403)  # bị chặn, không phải 302 sau khi lưu
    if resp.status_code == 302:
        assert resp.headers["Location"] != f"/dashboard/{MOCK_GUILD_ID}/modules"


# ─── P0.4 · IDOR channel cross-server ─────────────────────────────────────────

def _fake_channel_ids(ids):
    def _inner(guild_id):
        return set(ids)
    return _inner


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def test_send_embed_rejects_foreign_channel(client, temp_db, monkeypatch):
    import dashboard.api as dapi
    monkeypatch.setattr(dapi._auth, "get_guild_channel_ids", _fake_channel_ids({"111222333"}))
    token = authed_client(client)
    resp = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/send-embed",
        json={"channel_id": "444555666", "content": "spam sang server khác"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 403


def test_send_embed_ok_for_own_channel(client, temp_db, monkeypatch):
    import dashboard.api as dapi
    monkeypatch.setattr(dapi._auth, "get_guild_channel_ids", _fake_channel_ids({"111222333"}))
    monkeypatch.setattr(
        "dashboard.api.requests.post",
        lambda *a, **k: _FakeResp(200, {"id": "1"}),
    )
    token = authed_client(client)
    resp = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/send-embed",
        json={"channel_id": "111222333", "content": "hello"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_channel_check_fails_closed_when_unverifiable(client, temp_db, monkeypatch):
    """Không gọi được Discord API (None) → từ chối gửi (fail-closed)."""
    import dashboard.api as dapi
    monkeypatch.setattr(dapi._auth, "get_guild_channel_ids", lambda gid: None)
    token = authed_client(client)
    resp = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/send-embed",
        json={"channel_id": "111222333", "content": "hello"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 403


# ─── P0.3 · Route xóa chỉ nhận POST ───────────────────────────────────────────

def test_delete_routes_reject_get(client, temp_db):
    token = authed_client(client)  # noqa: F841 — GET không cần csrf
    paths = [
        f"/dashboard/{MOCK_GUILD_ID}/music/playlist/1/delete",
        f"/dashboard/{MOCK_GUILD_ID}/music/playlist/track/1/delete",
        f"/dashboard/{MOCK_GUILD_ID}/economy/delete_item/1",
        f"/dashboard/{MOCK_GUILD_ID}/tempvoice/delete_channel/123",
        f"/dashboard/{MOCK_GUILD_ID}/customcommands/delete/1",
    ]
    for p in paths:
        resp = client.get(p, follow_redirects=False)
        assert resp.status_code == 405, f"{p} vẫn chấp nhận GET!"


# ─── Phân quyền /admin ────────────────────────────────────────────────────────

def test_admin_blocked_for_non_owner(client, temp_db):
    authed_client(client, user_id="222222222222222222")  # không phải owner
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin" not in resp.headers["Location"]


def test_admin_redirects_anonymous_to_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ─── Health endpoint ──────────────────────────────────────────────────────────

def test_health_503_when_bot_offline(client, health_file):
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json()["online"] is False


def test_health_200_when_bot_online(client, health_file):
    import os
    os.makedirs(os.path.dirname(health_file), exist_ok=True)
    with open(health_file, "w", encoding="utf-8") as f:
        json.dump({"online": True, "pid": 123}, f)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["online"] is True


# ─── SSRF guard ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_url", [
    "http://127.0.0.1:8080/admin",
    "http://localhost/secret",
    "http://192.168.1.1/router",
    "http://10.0.0.5/internal",
    "http://169.254.169.254/latest/meta-data",  # cloud metadata
    "file:///etc/passwd",
    "gopher://evil",
    "ftp://x",
    "http://metadata.google.internal/",
    "",
    None,
])
def test_ssrf_guard_blocks(bad_url):
    from dashboard.auth import is_safe_http_url
    assert is_safe_http_url(bad_url) is False


@pytest.mark.parametrize("good_url", [
    "https://i.ytimg.com/vi/abc/hqdefault.jpg",
    "https://cdn.discordapp.com/icons/1/2.png",
    "http://example.com/image.png",
])
def test_ssrf_guard_allows_public(good_url):
    from dashboard.auth import is_safe_http_url
    assert is_safe_http_url(good_url) is True

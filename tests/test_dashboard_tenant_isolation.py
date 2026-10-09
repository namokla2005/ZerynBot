"""Tests cách ly theo tenant + chặn lạm dụng cho Dashboard (Phase 3).

Ba bất biến:
  1. Admin của guild A KHÔNG được ghi vào dữ liệu của guild B.
  2. Route nguy hiểm phải TẮT khi ADMIN_PASSWORD thiếu/yếu (fail-closed), chứ không
     phải "chạy không cần xác thực".
  3. Rate-limit phải khóa theo IP thật khi chạy sau Cloudflare.
"""
import time

import pytest

pytest.importorskip("flask", reason="Dashboard tests cần flask")
pytest.importorskip("flask_limiter", reason="Dashboard tests cần flask-limiter")

from conftest import authed_client, set_csrf_token, MOCK_USER_ID

GUILD_A = "1110000000000000001"
GUILD_B = "1110000000000000002"
TRACK = {
    "title": "song", "url": "https://youtu.be/x", "duration": 180,
    "webpage_url": "https://youtu.be/x", "thumbnail": "", "uploader": "u",
}


def _login_guilds(client, guild_ids, user_id=MOCK_USER_ID):
    """Session đăng nhập có quyền quản trị trên NHIỀU guild cùng lúc."""
    with client.session_transaction() as s:
        s["user"] = {"id": user_id, "username": "MultiAdmin", "global_name": "MultiAdmin", "avatar": None}
        s["avatar"] = "https://cdn.discordapp.com/embed/avatars/0.png"
        s["access_token"] = "mock-token"
        s["guilds"] = [
            {"id": gid, "name": f"Guild {gid}", "icon": None,
             "permissions": 8, "bot_in_guild": True}
            for gid in guild_ids
        ]
        s["guilds_fetched_at"] = time.time()
        s.permanent = True


# ─── 1. Ghi chéo server qua route playlist ────────────────────────────────────

def test_db_layer_refuses_track_insert_for_foreign_guild(temp_db):
    import database as db

    pl_b = db.create_playlist(GUILD_B, "Chỉ của B", "u9", "Owner")
    assert db.add_track_to_playlist(pl_b, TRACK, GUILD_A) == 0, (
        "tầng DB phải từ chối ghi khi guild_id không khớp"
    )
    assert db.get_playlist_tracks(pl_b) == []
    assert db.add_track_to_playlist(pl_b, TRACK, GUILD_B) > 0
    assert len(db.get_playlist_tracks(pl_b)) == 1


def test_guild_a_admin_cannot_add_track_to_guild_b_playlist(client, temp_db):
    """Lỗi gốc: nhánh 'playlist không thuộc guild' thiếu `return` nên rơi xuống dưới
    và ghi thẳng vào playlist của server khác."""
    import database as db

    pl_b = db.create_playlist(GUILD_B, "Nghiêm cấm ghi", "u9", "Owner")
    _login_guilds(client, [GUILD_A, GUILD_B])
    token = set_csrf_token(client)

    resp = client.post(
        f"/dashboard/{GUILD_A}/music/playlist/{pl_b}/add",
        data={"track_query": "https://youtu.be/evil"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code in (200, 302)
    assert db.get_playlist_tracks(pl_b) == [], (
        "admin guild A đã thêm bài vào playlist của guild B"
    )


def test_guild_a_admin_cannot_delete_guild_b_playlist(client, temp_db):
    import database as db

    pl_b = db.create_playlist(GUILD_B, "Không được xóa", "u9", "Owner")
    db.add_track_to_playlist(pl_b, TRACK, GUILD_B)
    _login_guilds(client, [GUILD_A, GUILD_B])
    token = set_csrf_token(client)

    client.post(
        f"/dashboard/{GUILD_A}/music/playlist/{pl_b}/delete",
        headers={"X-CSRF-Token": token},
    )
    assert db.get_playlist(pl_b) is not None, "xóa chéo server vẫn thành công"


# ─── 2. Step-Up fail-closed ───────────────────────────────────────────────────

@pytest.fixture()
def as_owner(monkeypatch):
    import config

    monkeypatch.setattr(config, "BOT_OWNER_ID", int(MOCK_USER_ID))
    return config


@pytest.mark.parametrize("password", ["", "ngan123", "123456789012345"], ids=[
    "trống", "quá ngắn theo mẫu dễ đoán", "vừa 15 ký tự (dưới trần 16)"])
def test_dangerous_routes_disabled_without_strong_password(client, temp_db, as_owner, monkeypatch, password):
    """Thiếu ADMIN_PASSWORD đủ mạnh => route shell bị VÔ HIỆU HÓA (503).

    Hành vi cũ (đã được một test cũ khóa lại như "đúng"): thiếu mật khẩu là decorator
    bỏ qua kiểm tra, để Web Terminal chạy với mỗi lớp bảo vệ là session owner.
    """
    monkeypatch.setattr(as_owner, "ADMIN_PASSWORD", password)
    token = authed_client(client)

    resp = client.post(
        "/admin/system/terminal",
        json={"command": ""},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 503, f"password={password!r} vẫn cho đi qua: {resp.status_code}"
    assert resp.get_json()["error"] == "stepup_unconfigured"


def test_stepup_endpoint_does_not_grant_access_without_password(client, temp_db, as_owner, monkeypatch):
    """`/admin/system/stepup` là nơi ĐỂ xác thực — nó không được tự cấp quyền."""
    monkeypatch.setattr(as_owner, "ADMIN_PASSWORD", "")
    token = authed_client(client)

    resp = client.post("/admin/system/stepup", json={"password": ""}, headers={"X-CSRF-Token": token})
    assert resp.status_code == 503
    with client.session_transaction() as s:
        assert not s.get("stepup_auth_until"), "stepup đã cấp quyền dù chưa cấu hình mật khẩu"


def test_stepup_still_works_with_strong_password(client, temp_db, as_owner, monkeypatch):
    monkeypatch.setattr(as_owner, "ADMIN_PASSWORD", "a-very-long-admin-passphrase-2026")
    token = authed_client(client)

    bad = client.post("/admin/system/stepup", json={"password": "sai"}, headers={"X-CSRF-Token": token})
    assert bad.status_code == 403

    good = client.post(
        "/admin/system/stepup",
        json={"password": "a-very-long-admin-passphrase-2026"},
        headers={"X-CSRF-Token": token},
    )
    assert good.status_code == 200 and good.get_json()["ok"] is True

    after = client.post(
        "/admin/system/terminal", json={"command": ""}, headers={"X-CSRF-Token": token}
    )
    assert after.status_code == 200, "sau khi step-up đúng thì route phải mở (15 phút)"


# ─── 3. Rate-limit theo IP thật + trần body ───────────────────────────────────

def test_client_key_uses_cf_connecting_ip_only_behind_proxy(monkeypatch):
    import config
    from flask import Flask
    from dashboard.extensions import _client_key

    app = Flask(__name__)
    monkeypatch.setattr(config, "BEHIND_PROXY", True)
    with app.test_request_context("/", headers={"CF-Connecting-IP": "203.0.113.7"}):
        assert _client_key() == "203.0.113.7", "mọi visitor sẽ chung 1 bucket limit"

    monkeypatch.setattr(config, "BEHIND_PROXY", False)
    with app.test_request_context("/", headers={"CF-Connecting-IP": "203.0.113.7"}):
        assert _client_key() != "203.0.113.7", "không có proxy mà vẫn tin header => spoof được"


def test_request_body_size_is_capped(flask_app):
    """Không đặt MAX_CONTENT_LENGTH thì một request khổng lồ đủ làm nghẽn tiến trình
    đang chạy chung máy 6GB với bot."""
    assert flask_app.config.get("MAX_CONTENT_LENGTH"), "MAX_CONTENT_LENGTH chưa được đặt"


def test_support_send_route_hits_its_rate_limit(client, temp_db, monkeypatch):
    """`/api/support/send` gọi AI trả phí cho TỪNG tin nhắn và từng không có trần nào.

    Test không đăng nhập: limiter chạy TRƯỚC view, nên 429 phải thắng 401 khi vượt trần.
    Fixture `flask_app` tắt limiter cho các test khác nên phải bật lại ở đây.
    """
    from dashboard.extensions import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    codes = [
        client.post("/api/support/send", json={"content": "x"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes, f"không giới hạn lượt gọi AI, toàn bộ response: {set(codes)}"

"""
test_dashboard_cache.py — Khoá các tối ưu cache của Web Dashboard (GĐ2).

Bối cảnh: dashboard chạy sau waitress với `threads=4` trên Termux. Mỗi request
REST chậm 5s (Discord roles, YouTube) giữ 1/4 năng lực dashboard, nên các cache
này phải tồn tại lâu dài — test ở đây phát hiện nếu ai đó vô tình bỏ cache.

Lưu ý: các test cần `flask` sẽ tự skip trên máy dev chưa cài flask (giống
tests/test_dashboard_security.py) nhưng LUÔN chạy trong CI.
"""
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE_DIR, os.path.join(BASE_DIR, "bot"), os.path.join(BASE_DIR, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── Cache role của guild (dashboard/auth.py) ─────────────────────────────────

class _FakeRolesResponse:
    ok = True
    status_code = 200

    def json(self):
        return [
            {"id": "1", "name": "@everyone", "color": 0, "position": 0},
            {"id": "2", "name": "Admin", "color": 15844367, "position": 5},
        ]


def test_guild_roles_uses_cache(temp_db, monkeypatch):
    """2 lần lấy role liên tiếp chỉ được gọi REST 1 lần."""
    import dashboard.auth as auth

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _FakeRolesResponse()

    monkeypatch.setattr(auth.config, "TOKEN", "test-token")
    monkeypatch.setattr(auth.requests, "get", fake_get)
    auth.invalidate_guild_roles_cache("999")

    first = auth.get_guild_roles("999")
    second = auth.get_guild_roles("999")

    assert calls["n"] == 1, "lần gọi thứ hai phải lấy từ cache, không gọi REST"
    assert [r["name"] for r in first] == ["Admin"], "@everyone phải bị lọc bỏ"
    assert second == first


def test_guild_roles_falls_back_to_db_normalized(temp_db, monkeypatch):
    """REST lỗi → dùng bảng guild_roles nhưng đã chuẩn hoá về dạng payload Discord."""
    import dashboard.auth as auth
    import database

    with database._connect_sync() as conn:
        conn.execute(
            "INSERT INTO guild_roles (guild_id, role_id, role_name, color_hex, position)"
            " VALUES (?, ?, ?, ?, ?)",
            ("777", "42", "Moderator", "#ff0000", 3),
        )
        conn.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(auth.config, "TOKEN", "test-token")
    monkeypatch.setattr(auth.requests, "get", boom)
    auth.invalidate_guild_roles_cache("777")

    roles = auth.get_guild_roles("777")
    assert roles == [{"id": "42", "name": "Moderator", "color": "#ff0000", "position": 3}]


def test_roles_cache_invalidator(temp_db, monkeypatch):
    """invalidate_guild_roles_cache phải buộc lần sau gọi lại REST."""
    import dashboard.auth as auth

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _FakeRolesResponse()

    monkeypatch.setattr(auth.config, "TOKEN", "test-token")
    monkeypatch.setattr(auth.requests, "get", fake_get)
    auth.invalidate_guild_roles_cache("555")

    auth.get_guild_roles("555")
    auth.invalidate_guild_roles_cache("555")
    auth.get_guild_roles("555")

    assert calls["n"] == 2


# ─── Cache metadata bài hát + helper HTTP Discord (dashboard/app.py) ──────────

def test_track_info_cache_avoids_duplicate_http(temp_db, monkeypatch):
    """Cùng một bài thêm 2 lần chỉ tốn 2 request (search + oembed) cho lần đầu."""
    pytest.importorskip("flask")
    import dashboard.app as dapp

    calls = {"search": 0, "oembed": 0}

    class _Resp:
        status_code = 200

        def __init__(self, payload, text=""):
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "results?search_query=" in url:
            calls["search"] += 1
            return _Resp({}, text='...{"videoId":"abcdefghijk"}...')
        calls["oembed"] += 1
        return _Resp({
            "title": "Bài hát thử nghiệm",
            "thumbnail_url": "https://img/x.jpg",
            "author_name": "Ca sĩ",
        })

    dapp._track_info_cache.clear()
    monkeypatch.setattr(dapp.requests, "get", fake_get)

    first = dapp.fetch_track_info_simple("Bài hát thử nghiệm")
    after_first = dict(calls)
    second = dapp.fetch_track_info_simple("bài hát thử nghiệm  ")  # khác hoa/thường + khoảng trắng

    assert first["title"] == "Bài hát thử nghiệm"
    assert second == first
    assert calls == after_first, f"lần gọi thứ hai phải lấy từ cache, không thêm HTTP: {calls}"


def test_discord_api_helper_never_raises(monkeypatch):
    """_discord_api phải trả None khi lỗi mạng (route xử lý None thay vì 500)."""
    pytest.importorskip("flask")
    import dashboard.app as dapp

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(dapp.requests, "request", boom)

    assert dapp._discord_api("GET", "/users/@me/guilds") is None
    assert dapp._discord_api("DELETE", "/users/@me/guilds/123") is None

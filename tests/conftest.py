"""
conftest.py — Fixtures dùng chung cho toàn bộ test suite.

Mô phỏng môi trường nội bộ theo đúng hướng dẫn `E2E_TESTING.md`:
- SQLite DB: file tạm per-test (tmp_path) thay cho data/bot.db thật.
- Flask session: mock user + guild như mô tả trong E2E_TESTING.md mục 2.
- Rate limiter: tắt trong test để không ảnh hưởng kết quả.
"""
import os
import sys
import time
import secrets

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (BASE_DIR, os.path.join(BASE_DIR, "bot"), os.path.join(BASE_DIR, "dashboard")):
    if p not in sys.path:
        sys.path.insert(0, p)


# ─── DB tạm (per-test) ─────────────────────────────────────────────────────────

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Trỏ database.DB_PATH sang file tạm rồi init schema."""
    import database

    db_file = tmp_path / "bot.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return str(db_file)


# ─── Flask app + session mock (theo E2E_TESTING.md) ───────────────────────────

MOCK_USER_ID = "111111111111111111"
MOCK_GUILD_ID = "999999999999999999"


@pytest.fixture()
def flask_app(temp_db):
    import dashboard.app as dapp

    dapp.app.config.update(TESTING=True)
    try:
        dapp.limiter.enabled = False  # flask-limiter
    except Exception:
        pass
    yield dapp.app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


def login(client, user_id: str = MOCK_USER_ID, guild_id: str = MOCK_GUILD_ID):
    """Gắn session đăng nhập nháy giống kịch bản E2E_TESTING.md."""
    with client.session_transaction() as s:
        s["user"] = {
            "id": user_id,
            "username": "TestAdmin",
            "global_name": "TestAdmin",
            "avatar": None,
        }
        s["avatar"] = "https://cdn.discordapp.com/embed/avatars/0.png"
        s["access_token"] = "mock-token"
        s["guilds"] = [
            {
                "id": guild_id,
                "name": "Zeryn Support Community",
                "icon": None,
                "permissions": 8,  # Administrator
                "bot_in_guild": True,
            }
        ]
        s["guilds_fetched_at"] = time.time()
        s.permanent = True
    return guild_id


def set_csrf_token(client) -> str:
    """Cài sẵn CSRF token vào session rồi trả về token để gắn vào header."""
    with client.session_transaction() as s:
        token = s.get("_csrf_token") or secrets.token_urlsafe(32)
        s["_csrf_token"] = token
    return token


def authed_client(client, user_id: str = MOCK_USER_ID):
    """Đăng nhập nháy + trả về CSRF token sẵn sàng cho POST."""
    login(client, user_id=user_id)
    return set_csrf_token(client)


@pytest.fixture()
def health_file():
    """Dọn file data/health.json sau mỗi test (file nằm trong gitignore)."""
    path = os.path.join(BASE_DIR, "data", "health.json")
    yield path
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

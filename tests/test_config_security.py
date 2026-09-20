"""
test_config_security.py — Kiểm tra cấu hình bảo mật trong `config.py`.

Tách khỏi `test_dashboard_security.py` (module đó cần flask) để các test này LUÔN
chạy được, kể cả trên máy dev chưa cài flask.

Phủ:
- P0.1: FLASK_SECRET_KEY fail-closed (không còn default tĩnh, ngẫu nhiên mỗi lần khởi động)
- P0.4: ADMIN_PASSWORD tồn tại trong config và đọc từ biến môi trường
"""
import importlib

import pytest


@pytest.fixture()
def isolated_env(monkeypatch):
    """Chặn đọc file .env thật để test đúng kịch bản "thiếu biến".

    Trước đây test fail oan trên máy có .env: `config.py` gọi `load_dotenv()` nên
    `FLASK_SECRET_KEY` luôn được nạp lại từ file → 2 lần reload cho cùng 1 giá trị.
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    yield
    monkeypatch.undo()
    import config
    importlib.reload(config)  # khôi phục config theo .env thật sau test


INSECURE_DEFAULTS = (
    "",
    "dev-secret-key-change-me",
    "change_this_to_a_random_secret_key_32chars",
)


def test_secret_key_no_static_default(monkeypatch, isolated_env):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    import config

    importlib.reload(config)
    assert config.FLASK_SECRET_KEY not in INSECURE_DEFAULTS

    first = config.FLASK_SECRET_KEY
    importlib.reload(config)
    assert config.FLASK_SECRET_KEY != first  # ngẫu nhiên mỗi lần khởi động
    assert len(first) >= 32


def test_secret_key_env_respected(monkeypatch, isolated_env):
    monkeypatch.setenv("FLASK_SECRET_KEY", "my-super-secret-key-1234567890abcdef")
    import config

    importlib.reload(config)
    assert config.FLASK_SECRET_KEY == "my-super-secret-key-1234567890abcdef"

    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    importlib.reload(config)


def test_admin_password_read_from_env(monkeypatch, isolated_env):
    """P0.4: `ADMIN_PASSWORD` phải tồn tại và lấy giá trị từ môi trường."""
    monkeypatch.setenv("ADMIN_PASSWORD", "  stepup-pass-abc  ")
    import config

    importlib.reload(config)
    assert config.ADMIN_PASSWORD == "stepup-pass-abc"  # đã strip khoảng trắng

    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    importlib.reload(config)
    assert config.ADMIN_PASSWORD == ""  # rỗng = tắt step-up (có cảnh báo khi import)

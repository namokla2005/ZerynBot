"""Tests cho phần hardening còn lại của Dashboard (Phase 3).

Bốn bất biến:
  1. Không kiểm chứng được id với Discord => KHÔNG lưu gì cả, config cũ còn nguyên.
  2. Role id cũng phải được kiểm tra như channel id (trước đây không có gì).
  3. Trang /admin không được chứa API key thật.
  4. Ô key để trống = giữ nguyên pool (không phải xóa sạch).
"""
import time

import pytest

pytest.importorskip("flask", reason="Dashboard tests cần flask")
pytest.importorskip("flask_limiter", reason="Dashboard tests cần flask-limiter")

from conftest import authed_client, login, set_csrf_token, MOCK_GUILD_ID, MOCK_USER_ID

REAL_GROQ_KEY = "gsk_" + "S" * 50 + "abcd"


# ─── 1 & 2. Kiểm chứng id ─────────────────────────────────────────────────────

def test_safe_channel_raises_instead_of_trusting_unverifiable_id(monkeypatch):
    from dashboard import auth as _auth
    from dashboard.web_helpers import VerificationUnavailable, _safe_channel

    monkeypatch.setattr(_auth, "get_guild_channel_ids", lambda gid: None)
    with pytest.raises(VerificationUnavailable):
        _safe_channel("g1", "999888777")   # id lạ, không kiểm chứng được


def test_welcome_save_keeps_old_channel_when_discord_unreachable(client, temp_db, monkeypatch):
    """Bất biến người dùng thấy: Discord lỗi lúc bấm Lưu => kênh cũ còn nguyên.

    Hành vi cũ là fail-open: id gửi lên được lưu thẳng khi không kiểm chứng được.
    """
    import database as db
    from dashboard import auth as _auth

    db.upsert_guild(MOCK_GUILD_ID, welcome_channel_id="1110000000000000000")
    monkeypatch.setattr(_auth, "get_guild_channel_ids", lambda gid: None)
    token = authed_client(client)

    resp = client.post(
        f"/dashboard/{MOCK_GUILD_ID}/welcome",
        data={"welcome_channel_id": "6660000000000000000", "welcome_message": "hi"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code in (200, 302)
    saved = db.get_guild_settings(MOCK_GUILD_ID)
    assert saved["welcome_channel_id"] == "1110000000000000000", (
        "id không kiểm chứng được đã bị lưu, hoặc config cũ bị xóa"
    )


def test_safe_channel_still_rejects_foreign_channel(monkeypatch):
    from dashboard import auth as _auth
    from dashboard.web_helpers import _safe_channel

    monkeypatch.setattr(_auth, "get_guild_channel_ids", lambda gid: {"123", "456"})
    assert _safe_channel("g1", "123") == "123"
    assert _safe_channel("g1", "999") is None


def test_safe_role_validates_against_guild_roles(monkeypatch):
    from dashboard import auth as _auth
    from dashboard.web_helpers import VerificationUnavailable, _safe_role

    monkeypatch.setattr(
        _auth, "get_guild_roles",
        lambda gid, include_everyone=False: [{"id": "777"}, {"id": "888"}],
    )
    assert _safe_role("g1", "777") == "777"
    assert _safe_role("g1", "777000") is None, "role của server khác phải bị từ chối"

    monkeypatch.setattr(_auth, "get_guild_roles", lambda gid, include_everyone=False: [])
    with pytest.raises(VerificationUnavailable):
        _safe_role("g1", "777")


def test_verify_page_rejects_foreign_role(client, temp_db, monkeypatch):
    import database as db
    from dashboard import auth as _auth

    monkeypatch.setattr(_auth, "get_guild_channel_ids", lambda gid: {"555"})
    monkeypatch.setattr(
        _auth, "get_guild_roles",
        lambda gid, include_everyone=False: [{"id": "777"}],
    )
    token = authed_client(client)

    client.post(
        f"/dashboard/{MOCK_GUILD_ID}/verify",
        data={"verified_role_id": "4440000000000000000", "channel_id": "555"},
        headers={"X-CSRF-Token": token},
    )
    saved = db.get_verify_settings(MOCK_GUILD_ID) if hasattr(db, "get_verify_settings") else {}
    assert str(saved.get("verified_role_id") or "") != "4440000000000000000", (
        "role id lạ vẫn được lưu"
    )


# ─── 3. _to_int không làm sập trang ───────────────────────────────────────────

def test_to_int_survives_junk_and_clamps():
    from dashboard.web_helpers import _to_int

    assert _to_int("", 15) == 15
    assert _to_int(None, 15) == 15
    assert _to_int("abc", 25) == 25
    assert _to_int("30", 10, lo=1, hi=20) == 20
    assert _to_int("-5", 10, lo=0) == 0
    assert _to_int("42", 0) == 42


def test_leveling_form_with_empty_number_field_does_not_500(client, temp_db, monkeypatch):
    """`int(form.get('message_xp_min', 15))` từng ValueError khi ô bị xóa trắng,
    và app không có errorhandler nào -> trang 500 thô của waitress."""
    from dashboard import auth as _auth

    monkeypatch.setattr(_auth, "get_guild_channel_ids", lambda gid: {"555"})
    token = authed_client(client)

    resp = client.post(
        f"/dashboard/{MOCK_GUILD_ID}/leveling",
        data={"message_xp_min": "", "message_xp_max": "not-a-number",
              "voice_xp": "7", "announce_channel_id": "555", "announce_message": "x"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code != 500, "form số học rỗng vẫn làm sập trang"


# ─── 4. Key AI không lộ trong HTML, rỗng = giữ nguyên ─────────────────────────

@pytest.fixture()
def owner_client(client, temp_db, as_owner):
    login(client)
    return client


@pytest.fixture()
def as_owner(monkeypatch):
    import config

    monkeypatch.setattr(config, "BOT_OWNER_ID", int(MOCK_USER_ID))
    return config


def test_admin_page_html_contains_no_real_api_key(owner_client, temp_db, monkeypatch):
    import database as db

    db.set_global_setting("groq_api_keys", REAL_GROQ_KEY)
    resp = owner_client.get("/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert REAL_GROQ_KEY not in html, "key thật bị render vào nguồn trang /admin"
    assert "gsk_****abcd" in html or "gsk_" in html, "UI phải còn cho biết đang có key nào"


def test_empty_key_field_preserves_stored_pool(owner_client, temp_db):
    """Textarea giờ trống khi mở trang => 'rỗng' không được phép nghĩa là 'xóa'."""
    import database as db

    db.set_global_setting("groq_api_keys", REAL_GROQ_KEY)
    token = set_csrf_token(owner_client)

    resp = owner_client.post(
        "/admin/ai_key",
        data={"gemini_api_keys": "", "groq_api_keys": "",
              "openrouter_api_keys": "", "global_ai_provider": "auto",
              "global_ai_model": "openai/gpt-oss-20b"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code in (200, 302)
    assert db.get_global_setting("groq_api_keys", "") == REAL_GROQ_KEY, (
        "bấm Lưu mà không đụng ô key đã xóa sạch pool"
    )


def test_clear_sentinel_empties_pool(owner_client, temp_db):
    import database as db
    from dashboard.blueprints.admin import KEY_CLEAR_SENTINEL

    db.set_global_setting("groq_api_keys", REAL_GROQ_KEY)
    token = set_csrf_token(owner_client)
    owner_client.post(
        "/admin/ai_key",
        data={"groq_api_keys": KEY_CLEAR_SENTINEL, "global_ai_provider": "auto"},
        headers={"X-CSRF-Token": token},
    )
    assert db.get_global_setting("groq_api_keys", "") == ""


def test_new_key_submission_replaces_pool(owner_client, temp_db):
    import database as db

    db.set_global_setting("groq_api_keys", REAL_GROQ_KEY)
    token = set_csrf_token(owner_client)
    fresh = "gsk_" + "N" * 50 + "wxyz"
    owner_client.post(
        "/admin/ai_key",
        data={"groq_api_keys": fresh, "global_ai_provider": "auto"},
        headers={"X-CSRF-Token": token},
    )
    assert db.get_global_setting("groq_api_keys", "") == fresh


def test_mask_key_exposes_only_last_four():
    from ai_manager import mask_key

    masked = mask_key(REAL_GROQ_KEY)
    assert masked == "gsk_****abcd", f"mask không như mong đợi: {masked}"
    # Phần nhân key (50 ký tự giữa) không được xuất hiện ở bất kỳ dạng nào.
    assert "SSSS" not in masked, "mask để lộ thân key"
    # Tổng ký tự thật tối đa = 4 prefix nhà cung cấp + 4 cuối (bản cũ lộ 7 + 4).
    exposed = sum(1 for ch in set(masked) if ch in REAL_GROQ_KEY[:-4])
    assert exposed <= 4, f"mask lộ nhiều hơn 4 ký tự nhận diện: {masked}"
    assert mask_key("short") == "****"


def test_error_handlers_registered(owner_client):
    app = owner_client.application
    handlers = set(app.error_handler_spec.get(None, {}).keys())
    assert 500 in handlers and 413 in handlers, f"thiếu errorhandler: {handlers}"


def test_logout_revokes_token_calling_discord(client, temp_db, monkeypatch):
    """/logout phải báo Discord thu hồi token, không chỉ xóa phía mình."""
    import dashboard.auth as _auth

    calls = {}

    def fake_post(url, **kw):
        calls["url"] = url
        calls["data"] = kw.get("data")

        class _R:
            status_code = 200
        return _R()

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    monkeypatch.setattr(_auth.config, "CLIENT_SECRET", "test-secret")

    login(client)
    with client.session_transaction() as s:
        token_id = s["oauth_token_id"]
    client.get("/logout", follow_redirects=True)

    assert calls.get("url", "").endswith("/oauth2/token/revoke"), "không gọi revoke lên Discord"
    assert token_id not in _auth._token_vault

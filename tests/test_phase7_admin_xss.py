"""P0-4 — Stored XSS: activity log phải được escape trước khi vào HTML.

admin.html dựng bảng bằng innerHTML; API là boundary cuối cùng trước sink.
Các message lỗi provider (fetch JSON) được escape tại client.
"""
import asyncio
import os

from conftest import MOCK_USER_ID, authed_client

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_activity_api_escapes_html_payload(monkeypatch, client, temp_db):
    import config
    import database as db

    monkeypatch.setattr(config, "BOT_OWNER_ID", int(MOCK_USER_ID))
    authed_client(client)

    asyncio.run(db.async_log_activity(
        action="/audit",
        event_type="command",
        guild_id="1",
        guild_name="<svg onload=alert(1)>",
        user_id="2",
        user_name='<img src=x onerror="alert(1)">',
        channel_name="general",
        details="<b>details</b>",
    ))
    asyncio.run(db.async_log_activity(
        action="/plain",
        guild_name="Tom & Jerry",
        user_name="A < B",
    ))

    resp = client.get("/api/admin/activity_logs")
    assert resp.status_code == 200
    logs = resp.get_json()["logs"]

    row = next(x for x in logs if x["action"] == "/audit")
    assert "&lt;img" in row["user_name"], row
    assert "<img" not in row["user_name"], "API vẫn trả HTML thô"
    assert "&lt;svg" in row["guild_name"]
    assert "&lt;b&gt;details&lt;/b&gt;" == row["details"]

    plain = next(x for x in logs if x["action"] == "/plain")
    assert plain["guild_name"] == "Tom &amp; Jerry"
    assert plain["user_name"] == "A &lt; B"


def test_admin_template_escapes_provider_error_text():
    html = open(
        os.path.join(BASE_DIR, "dashboard", "templates", "admin.html"),
        encoding="utf-8",
    ).read()
    assert "escapeHtml(r.provider" in html
    assert "escapeHtml(r.key_masked" in html
    assert "escapeHtml(r.message" in html
    assert "escapeHtml(data.message)" in html
    assert "escapeHtml(err.message)" in html

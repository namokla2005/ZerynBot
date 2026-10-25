"""P3-A — Dashboard chỉ nhận role/channel của chính guild, chặn open redirect,
và mọi key template phải có đủ 6 locale; tên hunt/work được dịch lúc render.
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_COGS = os.path.join(ROOT, "bot", "cogs")
sys.path.insert(0, _COGS)
try:
    import economy as eco  # noqa: E402
finally:
    sys.path.remove(_COGS)


def test_safe_role_accepts_only_roles_of_the_guild(monkeypatch):
    from dashboard import auth
    from dashboard.web_helpers import _safe_role

    monkeypatch.setattr(auth, "get_guild_roles", lambda gid, include_everyone=True: [
        {"id": "111", "name": "Member"},
        {"id": "222", "name": "Mod"},
    ])
    assert _safe_role("g1", "111") == "111"
    assert _safe_role("g1", "999") is None


def test_guild_handlers_use_safe_role():
    src = io.open(os.path.join(ROOT, "dashboard", "blueprints", "guild.py"), encoding="utf-8").read()
    assert "_safe_role(guild_id, rid)" in src
    assert "_safe_role(guild_id, value)" in src
    assert '_safe_role(guild_id, request.form.get("role_id"' in src
    assert "_safe_channel(guild_id, cid)" in src


def test_language_switch_blocks_open_redirect(client):
    bad = client.get("/ui/language/en", headers={"Referer": "https://evil.example/steal"})
    assert bad.status_code == 302
    assert "evil.example" not in bad.headers["Location"]

    ok = client.get("/ui/language/en", headers={"Referer": "http://localhost/dashboard"})
    assert ok.status_code == 302
    assert "localhost/dashboard" in ok.headers["Location"]


def test_all_template_keys_exist_in_six_locales():
    locales = {}
    for lang in ("vi", "en", "zh", "es", "pt", "fr"):
        locales[lang] = set(json.load(io.open(os.path.join(ROOT, "locales", f"{lang}.json"), encoding="utf-8")))
    used = set()
    for path in glob.glob(os.path.join(ROOT, "dashboard", "templates", "*.html")):
        text = io.open(path, encoding="utf-8").read()
        used |= set(re.findall(r"\bt\(\s*['\"]([a-zA-Z0-9_.\-]+)['\"]", text))
    for lang, keys in locales.items():
        missing = sorted(used - keys)
        assert not missing, f"{lang} thiếu key template: {missing}"


def test_hunt_and_job_names_translate_at_render():
    en = {"language": "en"}
    assert eco.cat_name(en, "🐇 Thỏ Rừng Nhanh Nhẹn") == "🐇 Swift Wild Rabbit"
    assert eco.cat_name(en, "Lập trình viên Fullstack 💻") == "Fullstack developer 💻"
    # Không có key thì trả nguyên chuỗi đã lưu, không lộ key.
    assert eco.cat_name(en, "món tự tạo") == "món tự tạo"


def test_dashboard_api_limits_expensive_panel_routes():
    src = io.open(os.path.join(ROOT, "dashboard", "api.py"), encoding="utf-8").read()
    assert src.count('@limiter.limit("10/minute")') >= 4

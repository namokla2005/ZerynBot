"""
test_dashboard_routes.py — Lưới an toàn cho `dashboard/app.py` trước/sau khi tách
thành blueprint (Giai đoạn 3.2).

Bắt đúng 3 loại lỗi nguy hiểm nhất khi tách route ra blueprint:
1. Mất/đổi URL của route (app.url_map phải khớp baseline).
2. Route render template bị 500 — đặc biệt lỗi `BuildError` do `url_for()` còn
   trỏ tên endpoint CŨ sau khi endpoint được đổi sang namespace mới.
3. Tên endpoint trong template/*.py không tồn tại → trang chết chỉ khi user mở.

Không gọi mạng: toàn bộ `requests.*` bị chặn, DB là file tạm qua fixture temp_db.
"""
import os
import re

import pytest

pytest.importorskip("flask", reason="Dashboard tests cần flask — bỏ qua khi chưa cài")
pytest.importorskip("flask_limiter", reason="Dashboard tests cần flask-limiter")

from conftest import MOCK_GUILD_ID, MOCK_USER_ID, login  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── Baseline URL: chụp TRƯỚC khi tách blueprint ────────────────────────────────
# Refactor chỉ được DI CHUYỂN code — URL + method phải y hệt.
BASELINE_ROUTES = [
    "DELETE /api/guild/<guild_id>/embeds/<int:embed_id>",
    "DELETE /api/guild/<guild_id>/reactionroles/<int:panel_id>",
    "DELETE /api/guild/<guild_id>/tickets/<int:panel_id>",
    "GET /",
    "GET /admin",
    "GET /admin/support",
    "GET /admin/support/",
    "GET /api/admin/activity_logs",
    "GET /api/admin/ai/activity-feed",
    "GET /api/admin/support/thread/<thread_id>/messages",
    "GET /api/admin/telemetry",
    "GET /api/guild/<guild_id>/channels",
    "GET /api/guild/<guild_id>/embeds",
    "GET /api/guild/<guild_id>/modules",
    "GET /api/guild/<guild_id>/recent_events",
    "GET /api/support/messages",
    "GET /callback",
    "GET /commands",
    "GET /dashboard",
    "GET /dashboard/<guild_id>",
    "GET /dashboard/<guild_id>/commands",
    "GET /dashboard/<guild_id>/customcommands",
    "GET /dashboard/<guild_id>/embeds",
    "GET /dashboard/<guild_id>/music",
    "GET /dashboard/<guild_id>/reactionroles",
    "GET /dashboard/<guild_id>/tickets",
    "GET /docs",
    "GET /health",
    "GET /invite",
    "GET /login",
    "GET /logout",
    "GET /privacy",
    "GET /support",
    "GET /tos",
    "GET /ui/language/<lang_code>",
    "GET,POST /dashboard/<guild_id>/ai",
    "GET,POST /dashboard/<guild_id>/automod",
    "GET,POST /dashboard/<guild_id>/autoroles",
    "GET,POST /dashboard/<guild_id>/birthday",
    "GET,POST /dashboard/<guild_id>/economy",
    "GET,POST /dashboard/<guild_id>/leveling",
    "GET,POST /dashboard/<guild_id>/logger",
    "GET,POST /dashboard/<guild_id>/moderation",
    "GET,POST /dashboard/<guild_id>/modules",
    "GET,POST /dashboard/<guild_id>/tempvoice",
    "GET,POST /dashboard/<guild_id>/verify",
    "GET,POST /dashboard/<guild_id>/welcome",
    "POST /admin/ai_key",
    "POST /admin/broadcast",
    "POST /admin/invite/<guild_id>",
    "POST /admin/kick/<guild_id>",
    "POST /admin/system/git-pull",
    "POST /admin/system/restart",
    "POST /admin/system/stepup",
    "POST /admin/system/terminal",
    "POST /admin/unblacklist/<guild_id>",
    "POST /api/admin/support/thread/<thread_id>/reply",
    "POST /api/admin/support/thread/<thread_id>/status",
    "POST /api/admin/test_ai_key",
    "POST /api/guild/<guild_id>/embeds",
    "POST /api/guild/<guild_id>/language",
    "POST /api/guild/<guild_id>/modules/<module_name>",
    "POST /api/guild/<guild_id>/reactionroles",
    "POST /api/guild/<guild_id>/reactionroles/<int:panel_id>/send",
    "POST /api/guild/<guild_id>/send-embed",
    "POST /api/guild/<guild_id>/send-test-card",
    "POST /api/guild/<guild_id>/tickets",
    "POST /api/guild/<guild_id>/tickets/<int:panel_id>/send",
    "POST /api/guild/<guild_id>/welcome",
    "POST /api/support/escalate",
    "POST /api/support/send",
    "POST /dashboard/<guild_id>/customcommands/add",
    "POST /dashboard/<guild_id>/customcommands/delete/<int:cmd_id>",
    "POST /dashboard/<guild_id>/economy/add_item",
    "POST /dashboard/<guild_id>/economy/delete_item/<int:item_id>",
    "POST /dashboard/<guild_id>/music/playlist/<int:playlist_id>/add",
    "POST /dashboard/<guild_id>/music/playlist/<int:playlist_id>/delete",
    "POST /dashboard/<guild_id>/music/playlist/create",
    "POST /dashboard/<guild_id>/music/playlist/track/<int:track_id>/delete",
    "POST /dashboard/<guild_id>/tempvoice/delete_channel/<channel_id>",
]

MIN_ENDPOINTS = 79          # số endpoint trước khi tách (gồm 'static')
MIN_URL_FOR_REFS = 100      # số lượt url_for('...') quét được (bắt regex hỏng)

# Route được phép trả 503 khi bot chưa chạy (health check chủ động báo down)
ALLOWED_5XX = {"/health": {503}}


# ─── 1. URL/method không được đổi ──────────────────────────────────────────────

def _signature(rule) -> str:
    methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
    return f"{methods} {rule.rule}"


def test_route_inventory_unchanged(flask_app):
    current = sorted(
        _signature(r) for r in flask_app.url_map.iter_rules() if r.endpoint != "static"
    )
    baseline = sorted(BASELINE_ROUTES)
    missing = [r for r in baseline if r not in current]
    added = [r for r in current if r not in baseline]
    assert not missing, f"Mất route sau refactor: {missing}"
    assert not added, f"Có route mới (nếu cố ý, cập nhật baseline): {added}"


def test_endpoint_count_not_reduced(flask_app):
    assert len(flask_app.view_functions) >= MIN_ENDPOINTS, (
        f"Chỉ còn {len(flask_app.view_functions)} endpoint — có blueprint quên register?"
    )


# ─── 2. Mọi route GET phải chạy được, không 500 ────────────────────────────────

def _block_network(monkeypatch):
    """Chặn mọi HTTP ra ngoài, bất kể module nào gọi (kể cả sau khi tách file)."""
    import requests

    def _boom(*args, **kwargs):
        raise RuntimeError("network blocked in test")

    monkeypatch.setattr(requests, "request", _boom)
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)
    monkeypatch.setattr(requests, "delete", _boom)


DUMMY_ARGS = {
    "guild_id": "999999999999999999",
    "channel_id": "111111111111111111",
    "user_id": "1",
    "thread_id": "1",
    "panel_id": "1",
    "playlist_id": "1",
    "track_id": "1",
    "item_id": "1",
    "cmd_id": "1",
    "embed_id": "1",
    "module_name": "music",
    "lang_code": "vi",
}


def _fill_url(rule) -> str | None:
    url = rule.rule
    for arg in rule.arguments:
        value = DUMMY_ARGS.get(arg)
        if value is None:
            return None
        url = re.sub(rf"<[^:<>]+:{arg}>", value, url)
        url = url.replace(f"<{arg}>", value)
    return url


def test_all_get_routes_do_not_500(client, flask_app, temp_db, monkeypatch):
    _block_network(monkeypatch)
    failures = []
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == "static" or "GET" not in rule.methods:
            continue
        url = _fill_url(rule)
        if url is None:
            continue
        try:
            resp = client.get(url)
        except Exception as exc:  # noqa: BLE001 — muốn thấy đúng route gây lỗi
            failures.append((rule.endpoint, url, repr(exc)[:200]))
            continue
        allowed = ALLOWED_5XX.get(rule.rule, set())
        if resp.status_code >= 500 and resp.status_code not in allowed:
            failures.append((rule.endpoint, url, resp.status_code))
    assert not failures, f"Route GET lỗi: {failures}"


# ─── 3. Mọi lời gọi url_for trong template/code phải trỏ endpoint còn tồn tại ───

URL_FOR_PATTERN = re.compile(r"""url_for\(\s*['"]([A-Za-z_][\w\.]*)['"]""")
SCAN_SKIP_DIRS = {".git", ".agents", "node_modules", "__pycache__", "data", ".venv", "venv"}


def _iter_scannable_files():
    for root, dirs, files in os.walk(BASE_DIR):
        # Bỏ qua mọi thư mục ẩn/tạm (.git, .tmp_*, .venv, ...) để không quét script nháp
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith((".py", ".html", ".js")):
                yield os.path.join(root, name)


def test_all_url_for_targets_exist(flask_app):
    known = set(flask_app.view_functions)
    missing = {}
    total = 0
    for path in _iter_scannable_files():
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for match in URL_FOR_PATTERN.finditer(text):
            name = match.group(1)
            total += 1
            if name not in known:
                missing.setdefault(name, set()).add(os.path.relpath(path, BASE_DIR))
    assert total >= MIN_URL_FOR_REFS, (
        f"Chỉ quét được {total} lượt url_for — regex/hướng quét có vấn đề?"
    )
    assert not missing, (
        "Các endpoint KHÔNG tồn tại nhưng vẫn được url_for gọi (sẽ lỗi BuildError 500): "
        + repr({k: sorted(v) for k, v in missing.items()})
    )


# ─── 4. Nhánh redirect bên trong decorator (mìn url_for("public.login"/"guild.home")) ───

def test_protected_page_redirects_to_login(client, temp_db):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    resp2 = client.get(f"/dashboard/{MOCK_GUILD_ID}")
    assert resp2.status_code == 302
    assert "/login" in resp2.headers["Location"]


def test_guild_access_denied_redirects_home(client, temp_db):
    """Session hợp lệ nhưng guild không có trong danh sách → phải về home, không 500."""
    login(client, user_id=MOCK_USER_ID)
    resp = client.get("/dashboard/123456789012345678")
    assert resp.status_code == 302
    assert resp.headers["Location"].rstrip("/").endswith("/dashboard")


def test_stale_session_without_network_does_not_500(client, temp_db, monkeypatch):
    """`_refresh_guilds_if_stale` gọi mạng khi session cũ — phải fail mềm, không 500."""
    _block_network(monkeypatch)
    login(client, user_id=MOCK_USER_ID)
    with client.session_transaction() as s:
        s["guilds_fetched_at"] = 0  # ép refresh
    resp = client.get(f"/dashboard/{MOCK_GUILD_ID}")
    assert resp.status_code in (200, 302)
    assert resp.status_code < 500


def test_public_pages_render(client, temp_db):
    for path in ("/", "/tos", "/privacy", "/docs", "/login"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} → {resp.status_code}"
    # /support yêu cầu đăng nhập → phải redirect chứ không được 500
    support = client.get("/support")
    assert support.status_code in (200, 302)
    assert support.status_code < 500


# ─── 5. URL tuyệt đối hardcode trong bot phải còn sống trên dashboard ───────────

ABSOLUTE_URL_PATTERN = re.compile(r"https://zerynbot\.id\.vn(/[A-Za-z0-9_\-/?&=%#]*)?")


def test_hardcoded_public_urls_still_route(flask_app):
    """`/botinfo` + 2 nút `/help` trỏ `https://zerynbot.id.vn/commands` từ hồi viết lệnh,
    nhưng trang lệnh thật nằm ở `/docs` → người dùng bấm là gặp 404.

    Regex/URL map là machine thật của loại lỗi này: một trang bị đổi tên hoặc
    xóa đi sẽ không làm sập test nào khác, chỉ làm hỏng liên kết mà user đã bấm.
    Quét cả bot/ lẫn dashboard/ vì cả hai đều nhúng URL tuyệt đối.
    """
    from werkzeug.exceptions import MethodNotAllowed, NotFound

    import pathlib

    adapter = flask_app.url_map.bind("zerynbot.id.vn")
    offenders = []
    checked = set()
    root = pathlib.Path(BASE_DIR)
    for folder in ("bot", "dashboard"):
        for py in sorted((root / folder).rglob("*.py")):
            rel = str(py.relative_to(root)).replace("\\", "/")
            for n, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for m in ABSOLUTE_URL_PATTERN.finditer(line):
                    path = m.group(1) or "/"
                    checked.add(path)
                    try:
                        adapter.match(path)
                    except NotFound:
                        offenders.append(f"{rel}:{n} → {path} (404)")
                    except MethodNotAllowed:
                        offenders.append(f"{rel}:{n} → {path} (khong nhan GET)")
    # /commands 404 tung lap lại loi nay; neu quyet duoc qua it URL thi regex hong
    assert "/commands" in checked, f"Quét phải gồm /commands, mới nhận: {sorted(checked)}"
    assert not offenders, f"URL hardcode dieu tren dashboard: {offenders}"


def test_commands_url_lands_on_command_center(client, temp_db):
    """User bấm "Danh Sách Lệnh" trong Discord → phải tới trang lệnh, không 404."""
    root = client.get("/commands")
    assert root.status_code in (301, 302, 307, 308), f"/commands → {root.status_code}"
    from urllib.parse import urlparse

    assert urlparse(root.headers["Location"]).path == "/docs"

    landed = client.get("/commands", follow_redirects=True)
    assert landed.status_code == 200
    assert b"cmd-search" in landed.data, "Ve /docs nhung thieu o tim lenh — khong phai trang lenh"


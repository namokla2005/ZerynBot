"""Phase 4 — task fire-and-forget sống sót qua GC + input hygiene ở các cổng vào.

M2/M3/L1/L2 trong docs/BAO CAO_AUDIT_LOI_AN_2026-10-18.md.
"""
import asyncio
import gc
import re
import warnings
from pathlib import Path

import pytest

from conftest import authed_client, login, MOCK_GUILD_ID  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ─── M2: strong reference cho task nền ────────────────────────────────────────

async def test_spawned_task_survives_gc_and_finishes():
    """Bug gốc: loop chỉ giữ WEAK ref -> task có thể bị GC giữa chừng, không log, không lỗi."""
    import taskbag

    done = {"v": False}

    async def work():
        await asyncio.sleep(0.05)
        done["v"] = True

    task = taskbag.spawn(work())
    assert taskbag.pending_count() >= 1, "spawn phải giữ reference vào bag"
    gc.collect()                       # đúng cái đã giết task trước khi có taskbag
    await asyncio.sleep(0.2)

    assert done["v"] is True, "task bị GC mất giữa chừng"
    assert taskbag.pending_count() == 0, "task xong rồi phải được nhả khỏi bag"


def test_spawn_without_running_loop_does_not_raise():
    """cog_unload có thể chạy lúc event loop đã đóng — phải im lặng, không nổ, không warning."""
    import taskbag

    async def work():
        pass

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert taskbag.spawn(work(), name="no-loop") is None
        gc.collect()
    assert not [w for w in caught if "never awaited" in str(w.message)], [str(w.message) for w in caught]


def test_no_bare_fire_and_forget_create_task_left_in_bot():
    """Guard nguồn: mọi `create_task` nền phải đi qua taskbag hoặc được gán vào biến."""
    offenders = []
    for path in sorted((ROOT / "bot").rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            if "asyncio.create_task(" not in code:
                continue
            if re.search(r"\w+\s*=[^=].*asyncio\.create_task\(", code):
                continue   # có gán (kể cả trong biểu thức ternary) -> caller tự giữ reference
            if "add_signal_handler" in code:
                continue                       # callback shutdown, không phải nền
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {code.strip()}")
    assert not offenders, "task nền không ai giữ reference:\n" + "\n".join(offenders)


# ─── M3: cột SQL không bind được -> phải whitelist ────────────────────────────

def test_upsert_guild_rejects_unknown_column(temp_db):
    import database

    database.init_db()
    with pytest.raises(ValueError):
        database.upsert_guild("g_wl", **{"language = 'vi'; DROP TABLE guilds; --": "x"})

    # Bảng vẫn dùng được bình thường -> câu SQL độc không hề được ghép vào.
    assert database.get_guild_settings("g_wl")["language"] == "vi"


def test_upsert_guild_still_writes_real_columns(temp_db):
    import database

    database.init_db()
    database.upsert_guild("g_wl_ok", language="en", welcome_use_embed=0)

    got = database.get_guild_settings("g_wl_ok")
    assert got["language"] == "en"
    assert int(got["welcome_use_embed"]) == 0


# ─── L2: module_name từ URL ───────────────────────────────────────────────────

def test_set_module_rejects_unknown_name(temp_db):
    import database

    database.init_db()
    assert database.set_module("g_mod", "nhac_cua_tui", True) is False
    assert database.set_module("g_mod", "music", True) is True

    rows = database.get_guild_modules("g_mod")
    assert "nhac_cua_tui" not in rows


def test_api_toggle_module_returns_400_for_unknown(client, temp_db):
    token = authed_client(client)
    hdr = {"X-CSRF-Token": token}
    ok = client.post(f"/api/guild/{MOCK_GUILD_ID}/modules/music", json={"enabled": True}, headers=hdr)
    bad = client.post(f"/api/guild/{MOCK_GUILD_ID}/modules/rac", json={"enabled": True}, headers=hdr)

    assert ok.status_code == 200, ok.data[:200]
    assert bad.status_code == 400
    assert bad.get_json()["error"] == "unknown_module"


# ─── L1: after_id từ query string ─────────────────────────────────────────────

def test_support_messages_rejects_non_numeric_after_id(client, temp_db):
    login(client)
    r = client.get("/api/support/messages?thread_id=t1&after_id=abc")

    assert r.status_code == 400, f"phải là 400 rõ ràng, không 500 kèm traceback: {r.status_code}"
    assert r.get_json()["error"] == "bad_after_id"

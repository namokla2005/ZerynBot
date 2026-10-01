"""
test_termux_optimizations.py — Khoá các tối ưu chạy 24/7 trên Termux (Tecno Pova 2).

Bảo vệ những thứ rất dễ bị vô hiệu hoá khi refactor:
- PRAGMA per-connection (cache_size / temp_store / mmap / busy_timeout) phải được
  áp cho mọi kết nối qua helper `_connect_sync` / `_connect_async` — nếu ai đó mở
  lại `sqlite3.connect(...)` trực tiếp thì tối ưu RAM/IO sẽ biến mất.
- `DB_PATH` vẫn phải đọc tại thời điểm gọi (giữ nguyên khả năng monkeypatch của
  conftest; nếu helper cache biến này thì test sẽ ghi vào DB thật).
- Cog AI phải dùng chung một `aiohttp.ClientSession` thay vì tạo mới mỗi request.
- 3 hàm provider "key riêng của guild" phải đi qua `ai_manager` (một nguồn logic).
- `call_ai_sync` phải có ngân sách thời gian để không giữ worker thread của chat
  support 24/7.
- Chu kỳ task ngầm đã giãn lên 60s để giảm số lần đánh thức CPU.
"""
import asyncio
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE_DIR, os.path.join(BASE_DIR, "bot"), os.path.join(BASE_DIR, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── PRAGMA per-connection (GĐ1.7) ────────────────────────────────────────────

def test_sync_connection_applies_tuned_pragmas(temp_db):
    import database

    with database._connect_sync() as conn:
        assert conn.execute("PRAGMA cache_size;").fetchone()[0] == database.DB_CACHE_SIZE_KB
        assert conn.execute("PRAGMA temp_store;").fetchone()[0] == 2      # 2 = MEMORY
        assert conn.execute("PRAGMA synchronous;").fetchone()[0] == 1     # 1 = NORMAL
        assert conn.execute("PRAGMA busy_timeout;").fetchone()[0] == database.DB_BUSY_TIMEOUT_MS
        mmap = conn.execute("PRAGMA mmap_size;").fetchone()[0]
        # 0 = bản SQLite không hỗ trợ mmap (một số platform) → vẫn hợp lệ
        assert mmap in (0, database.DB_MMAP_BYTES)


async def test_async_connection_applies_tuned_pragmas(temp_db):
    import database

    async with database._connect_async() as db:
        async with db.execute("PRAGMA cache_size;") as cur:
            assert (await cur.fetchone())[0] == database.DB_CACHE_SIZE_KB
        async with db.execute("PRAGMA temp_store;") as cur:
            assert (await cur.fetchone())[0] == 2


def test_connect_helpers_read_db_path_at_call_time(temp_db, tmp_path):
    """Đổi DB bằng set_db_path() phải có hiệu lực ngay cho kết nối mở sau đó.

    Giai đoạn 3.3: `database` là package nên `DB_PATH` chỉ tồn tại thật ở
    `database/conn.py`; API chính thức để đổi DB là `set_db_path()` (đồng bộ cả
    `database.DB_PATH` lẫn conn). Test này khoá đúng hành vi "đọc tại thời điểm
    gọi, không cache" — nếu ai đó cache đường dẫn trong helper, test sẽ đỏ.
    """
    import database

    other = tmp_path / "other.db"
    database.set_db_path(str(other))

    with database._connect_sync() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS pragma_probe (x INTEGER)")
        conn.commit()

    assert other.exists(), "helper phải dùng DB_PATH tại thời điểm gọi, không cache"
    assert database.DB_PATH == str(other), "database.DB_PATH phải phản ánh giá trị mới"
    asyncio.run(_async_probe_uses_new_db(str(other)))


async def _async_probe_uses_new_db(path: str):
    """Đường async cũng phải theo DB mới (không dùng bản sao DB_PATH cũ)."""
    import database

    assert database.get_db_path() == path
    async with database._connect_async() as db:
        async with db.execute("SELECT COUNT(*) FROM pragma_probe;") as cur:
            assert (await cur.fetchone())[0] == 0


async def test_vacuum_stays_safe_and_forcible(temp_db):
    """VACUUM tự quyết định (có thể bỏ qua) và force=True đều không được lỗi."""
    import database

    with database._connect_sync() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS vacuum_probe (x INTEGER)")
        conn.executemany("INSERT INTO vacuum_probe (x) VALUES (?)", [(i,) for i in range(200)])
        conn.commit()
        conn.execute("DELETE FROM vacuum_probe")
        conn.commit()

    await database.async_vacuum_db()             # dưới ngưỡng rác → bỏ qua VACUUM
    await database.async_vacuum_db(force=True)   # đường chạy tay → luôn VACUUM

    with database._connect_sync() as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacuum_probe;").fetchone()[0] == 0


# ─── Session AI dùng chung (GĐ1.4) ────────────────────────────────────────────

async def test_ai_session_is_shared_and_recreatable():
    import cogs.ai as ai

    s1 = await ai._get_ai_session()
    s2 = await ai._get_ai_session()
    assert s1 is s2, "phải tái sử dụng cùng một ClientSession cho mọi request"

    await ai.close_ai_session()
    assert s1.closed, "close_ai_session phải đóng session"

    s3 = await ai._get_ai_session()
    assert s3 is not s1, "session đã đóng phải được tạo lại"
    await ai.close_ai_session()


# ─── Hợp nhất stack AI (GĐ1.5) ────────────────────────────────────────────────

async def test_legacy_providers_delegate_to_ai_manager(monkeypatch):
    import cogs.ai as ai
    import ai_manager as aim

    seen = []

    async def fake_call_provider_async(**kwargs):
        seen.append(kwargs)
        return True, "PHẢN HỒI"

    monkeypatch.setattr(aim.ai_manager, "call_provider_async", fake_call_provider_async)

    assert await ai._call_groq_api("hi", None, "gsk_test", None, None) == "PHẢN HỒI"
    assert await ai._call_openrouter_api("hi", None, "sk-or-v1-test") == "PHẢN HỒI"
    assert await ai._call_gemini_direct("hi", None, "AIza-test") == "PHẢN HỒI"

    assert [c["provider"] for c in seen] == ["groq", "openrouter", "gemini"]


async def test_legacy_providers_report_failure(monkeypatch):
    """Lỗi từ manager phải được dịch thành chuỗi '❌ ...' như hành vi cũ."""
    import cogs.ai as ai
    import ai_manager as aim

    async def fake_rate_limited(**kwargs):
        return False, "RATE_LIMIT_429"

    monkeypatch.setattr(aim.ai_manager, "call_provider_async", fake_rate_limited)

    assert (await ai._call_groq_api("hi", None, "gsk_test")).startswith("❌")
    assert (await ai._call_openrouter_api("hi", None, "sk-or-v1-test")).startswith("❌")
    assert (await ai._call_gemini_direct("hi", None, "AIza-test")).startswith("❌")


async def test_gemini_direct_blocks_internal_image_url():
    """SSRF guard cho URL ảnh phải chặn trước khi gọi network."""
    import cogs.ai as ai

    res = await ai._call_gemini_direct("mô tả", None, "AIza-test", image_url="http://127.0.0.1/a.png")
    assert "SSRF" in res


# ─── ai_manager: SSRF ảnh + ngân sách thời gian (GĐ1.5, GĐ1.6) ────────────────

def test_is_safe_image_url_blocks_internal_hosts():
    import ai_manager as aim

    for bad in (
        "http://127.0.0.1/a.png",
        "http://localhost/a.png",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10/a.png",
        "",
    ):
        assert aim.is_safe_image_url(bad) is False, bad

    assert aim.is_safe_image_url("https://example.com/a.png") is True


async def test_call_provider_async_rejects_empty_and_cooled_key(monkeypatch):
    import ai_manager as aim

    ok, res = await aim.ai_manager.call_provider_async("groq", "   ", "hi")
    assert (ok, res) == (False, "EMPTY_KEY")

    monkeypatch.setattr(aim.ai_manager, "is_in_cooldown", lambda key: True)
    ok, res = await aim.ai_manager.call_provider_async("groq", "gsk_x", "hi")
    assert (ok, res) == (False, "RATE_LIMIT_429")


async def test_sync_budget_prevents_runaway(monkeypatch):
    """Provider chậm: call_ai_sync phải dừng theo ngân sách, không thử hết."""
    import ai_manager as aim

    mgr = aim.ai_manager
    monkeypatch.setattr(aim, "ai_logger", None)
    monkeypatch.setattr(aim, "SYNC_TOTAL_BUDGET", 0.25)
    monkeypatch.setattr(
        mgr,
        "load_pools",
        lambda: {
            "routing_mode": "auto",
            "model": "qwen/qwen3.8-27b",
            "gemini_keys": ["k1"],
            "groq_keys": ["k2"],
            "openrouter_keys": ["k3"],
        },
    )
    monkeypatch.setattr(
        mgr, "_get_provider_chain", lambda routing, model: ["groq", "openrouter", "gemini"]
    )

    attempts = {"n": 0}

    def slow_fail(key, prompt, system_instruction="", model="", **kwargs):
        attempts["n"] += 1
        time.sleep(0.15)
        return False, "HTTP 500"

    monkeypatch.setattr(mgr, "_call_groq_sync", slow_fail)
    monkeypatch.setattr(mgr, "_call_openrouter_sync", slow_fail)
    monkeypatch.setattr(mgr, "_call_gemini_sync", slow_fail)

    t0 = time.monotonic()
    ok, _res = mgr.call_ai_sync("hi")
    elapsed = time.monotonic() - t0

    assert ok is False
    assert elapsed < 1.0, f"call_ai_sync phải dừng sớm, đã chạy {elapsed:.2f}s"
    assert attempts["n"] < 3, f"không được thử hết 3 provider khi hết ngân sách ({attempts['n']})"


# ─── Nhịp task ngầm (GĐ1.8) ───────────────────────────────────────────────────

def test_background_loops_use_slower_cadence():
    import cogs.giveaway as gw
    import cogs.remind as rd

    assert float(gw.Giveaway.giveaway_loop.seconds) == 60.0
    assert float(rd.Remind.reminder_task.seconds) == 60.0

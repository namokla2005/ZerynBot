"""Tests cho guardrails tầng AI (Phase 2).

Ba bất biến cần khoá:
  1. `load_pools()` (sqlite3 ĐỒNG BỘ) không được chạy trên event loop — nó từng có
     thể treo cả bot tới `busy_timeout` 15s.
  2. Mọi cửa gọi AI (chat kênh, /ask, /summarize) phải chung một ngân sách.
  3. Ảnh người dùng đính kèm không được nạp vô hạn vào RAM, và model vision đã bị
     vô hiệu hóa không được gọi nữa.
"""
import asyncio
import threading
import time

import pytest


@pytest.fixture()
def mgr(temp_db):
    import ai_manager

    return ai_manager.AIProviderManager()


# ─── 1. Không block event loop ─────────────────────────────────────────────────

async def test_load_pools_runs_off_the_event_loop(mgr, monkeypatch):
    seen = {}
    real_pools = mgr.load_pools

    def slow_pools():
        seen["thread"] = threading.current_thread().name
        time.sleep(0.3)                      # mô phỏng cache miss + write-lock
        return real_pools()

    monkeypatch.setattr(mgr, "load_pools", slow_pools)

    ticks = 0
    stop = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.02)

    task = asyncio.create_task(ticker())
    try:
        await mgr.call_ai_async("ping")      # pool rỗng -> failover rồi trả về
    finally:
        stop.set()
        await task

    assert seen.get("thread"), "call_ai_async phải đọc pool qua load_pools()"
    assert seen["thread"] != threading.main_thread().name, (
        f"load_pools chạy trên '{seen['thread']}' — phải qua asyncio.to_thread, "
        "nếu không mọi cog và voice đều đứng hình trong lúc chờ SQLite"
    )
    assert ticks >= 5, f"event loop bị chặn: chỉ {ticks} tick trong lúc gọi AI"


async def test_call_provider_async_does_not_block_loop(mgr, monkeypatch):
    seen = {}
    real_pools = mgr.load_pools

    def spy_pools():
        seen["thread"] = threading.current_thread().name
        return real_pools()

    monkeypatch.setattr(mgr, "load_pools", spy_pools)
    ok, res = await mgr.call_provider_async("groq", "gsk_invalid_key_for_test", "hi")
    assert ok is False
    assert seen.get("thread") != threading.main_thread().name, (
        "call_provider_async cũng phải đọc model default ngoài event loop"
    )


# ─── 2. Ngân sách AI chung mọi cửa ────────────────────────────────────────────

async def test_ai_budget_enforced_and_shared_across_surfaces(temp_db):
    from cogs.ai import AI

    guild, user = "g_budget_1", "u_budget_1"
    ai_s = {"rate_limit": 3}

    results = [await AI._consume_ai_budget(None, guild, user, ai_s) for _ in range(5)]
    assert results == [True, True, True, False, False], (
        f"phải cho đúng 3 lượt/60s rồi chặn, thực tế: {results}"
    )
    # Cửa khác (listener #ai-chat, /summarize) dùng cùng key → cùng ngân sách.
    assert await AI._consume_ai_budget(None, guild, user, {"rate_limit": 3}) is False
    # User khác trong cùng guild không bị ảnh hưởng.
    assert await AI._consume_ai_budget(None, guild, "u_other_1", ai_s) is True


async def test_ai_budget_invalid_limit_falls_back(temp_db):
    from cogs.ai import AI

    # rate_limit rác (string/None) không được khiến lệnh AI nổ.
    assert await AI._consume_ai_budget(None, "g_budget_2", "u1", {"rate_limit": "abc"}) is True
    # 0 hoặc âm = chủ guild tắt giới hạn → không chặn.
    assert await AI._consume_ai_budget(None, "g_budget_2", "u2", {"rate_limit": 0}) is True


# ─── 3. Ảnh: chặn kích thước, không gọi model đã chết ─────────────────────────

class _FakeContent:
    def __init__(self, payload: bytes):
        self._payload = payload

    async def read(self, n: int) -> bytes:
        return self._payload[:n]


class _FakeResponse:
    def __init__(self, status, headers, payload):
        self.status = status
        self.headers = headers
        self.content = _FakeContent(payload)
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return {}

    async def text(self):
        return ""


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.requested = None

    def get(self, url, **kwargs):
        self.requested = url
        return self._response


async def test_gemini_rejects_oversized_image(mgr, monkeypatch):
    import ai_manager

    monkeypatch.setattr(ai_manager, "is_safe_image_url", lambda url: True)
    payload = b"x" * (ai_manager.AI_IMAGE_MAX_BYTES + 4096)
    session = _FakeSession(_FakeResponse(
        200, {"Content-Type": "image/png", "Content-Length": str(len(payload))}, payload
    ))

    ok, res = await mgr._call_gemini_async(
        session, "fake-key", "mô tả ảnh", image_url="https://cdn.discordapp.com/a.png"
    )
    assert ok is False and res == "IMAGE_TOO_LARGE", res
    assert session.requested is None or ok is False


async def test_gemini_catches_lying_content_length(mgr, monkeypatch):
    """Server nói Content-Length nhỏ nhưng thực tế tải về khổng lồ."""
    import ai_manager

    monkeypatch.setattr(ai_manager, "is_safe_image_url", lambda url: True)
    payload = b"x" * (ai_manager.AI_IMAGE_MAX_BYTES + 4096)
    session = _FakeSession(_FakeResponse(
        200, {"Content-Type": "image/png", "Content-Length": "1024"}, payload
    ))
    ok, res = await mgr._call_gemini_async(session, "k", "hi", image_url="https://x/y.png")
    assert ok is False and res == "IMAGE_TOO_LARGE", res


async def test_gemini_rejects_non_image_content_type(mgr, monkeypatch):
    import ai_manager

    monkeypatch.setattr(ai_manager, "is_safe_image_url", lambda url: True)
    session = _FakeSession(_FakeResponse(
        200, {"Content-Type": "application/x-executable"}, b"MZ" + b"\x00" * 100
    ))
    ok, res = await mgr._call_gemini_async(session, "k", "hi", image_url="https://x/y.bin")
    assert ok is False and res == "IMAGE_BAD_TYPE", res


async def test_gemini_reports_download_failure_instead_of_answering_text_only(
    mgr, monkeypatch
):
    """Lỗi tải ảnh phải trả thất bại — im lặng bỏ ảnh sẽ trả lời sai nội dung."""
    import ai_manager

    monkeypatch.setattr(ai_manager, "is_safe_image_url", lambda url: True)
    session = _FakeSession(_FakeResponse(404, {}, b""))
    ok, res = await mgr._call_gemini_async(session, "k", "hi", image_url="https://x/y.png")
    assert ok is False and res == "IMAGE_DOWNLOAD_HTTP_404", res


async def test_disabled_vision_models_are_no_longer_called(mgr, monkeypatch):
    """llama-3.2-vision đã bị Groq gỡ (references/groq_active_models.md) — gọi nữa
    chỉ nhận 404 rồi vẫn đốt thêm provider kế tiếp."""
    import ai_manager

    monkeypatch.setattr(ai_manager, "is_safe_image_url", lambda url: True)
    monkeypatch.setattr(ai_manager, "GROQ_VISION_MODEL", "", raising=False)
    monkeypatch.setattr(ai_manager, "OPENROUTER_VISION_MODEL", "", raising=False)

    ok, res = await mgr._call_groq_async(
        None, "gsk_fake", "describe", image_url="https://cdn.discordapp.com/a.png"
    )
    assert ok is False and res == "GROQ_VISION_UNAVAILABLE", res

    ok2, res2 = await mgr._call_openrouter_async(
        None, "sk-or-fake", "describe", image_url="https://cdn.discordapp.com/a.png"
    )
    assert ok2 is False and res2 == "OPENROUTER_VISION_UNAVAILABLE", res2

    # Text thường vẫn đi đường bình thường (không bị chặn oan): tới được bước gọi HTTP.
    reached_http = {"v": False}

    class _ProbeSession:
        def post(self, url, **kwargs):
            reached_http["v"] = True
            return _FakeResponse(401, {}, b"{}")

    await mgr._call_groq_async(_ProbeSession(), "gsk_fake", "hello")
    assert reached_http["v"], "prompt chữ phải còn được gửi tới Groq"


async def test_gemini_body_caps_output_tokens(mgr, monkeypatch):
    """Gemini là provider duy nhất từng không đặt trần output."""
    import ai_manager

    captured = {}

    class _RecordingSession:
        def post(self, url, **kwargs):
            captured["body"] = kwargs.get("json")
            return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")

    await mgr._call_gemini_async(_RecordingSession(), "k", "hello")
    body = captured.get("body") or {}
    gen_cfg = body.get("generationConfig") or {}
    assert gen_cfg.get("maxOutputTokens"), (
        f"body Gemini không có generationConfig.maxOutputTokens: {body}"
    )


def test_every_ai_entry_point_consumes_budget():
    """Guard chỉ có nghĩa khi MỌI cửa gọi provider đi qua nó.

    Bug gốc: `rate_limit` có sẵn trong ai_settings và listener #ai-chat thì áp dụng,
    còn /ask và /summarize gọi thẳng provider — owner tưởng đã giới hạn nhưng chưa.
    """
    import inspect
    from cogs.ai import AI

    for name in ("ask", "summarize", "on_message"):
        func = getattr(AI, name)
        func = getattr(func, "callback", func)      # hybrid_command bọc hàm gốc trong .callback
        src = inspect.getsource(func)
        assert "_consume_ai_budget" in src, (
            f"AI.{name} gọi provider mà không trích ngân sách trước"
        )

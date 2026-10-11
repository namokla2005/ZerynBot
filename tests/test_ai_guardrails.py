"""Tests cho guardrails tầng AI (Phase 2).

Ba bất biến cần khoá:
  1. `load_pools()` (sqlite3 ĐỒNG BỘ) không được chạy trên event loop — nó từng có
     thể treo cả bot tới `busy_timeout` 15s.
  2. Mọi cửa gọi AI (chat kênh, /ask, /summarize) phải chung một ngân sách.
  3. Ảnh người dùng đính kèm không được nạp vô hạn vào RAM, và model vision đã bị
     vô hiệu hóa không được gọi nữa.
"""
import asyncio
import re
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


# ─── 4. Câu trả lời dài: chia tin nhắn, không cắt mất nội dung ────────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_split_keeps_short_text_untouched():
    from cogs.ai import _split_for_discord

    text = "Câu trả lời ngắn gọn."
    assert _split_for_discord(text) == [text]


def test_split_never_exceeds_discord_limit_and_loses_nothing():
    from cogs.ai import DISCORD_MESSAGE_LIMIT, _split_for_discord

    text = "\n\n".join(f"- Mục {i}: " + "nội dung dài dòng " * 20 for i in range(40))
    chunks = _split_for_discord(text)
    assert len(chunks) > 1, "text 6k ký tự mà vẫn ra 1 tin => chưa chia"
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks), [len(c) for c in chunks]
    assert _norm("".join(chunks)) == _norm(text), "có nội dung bị rơi khi chia tin"


def test_split_does_not_leave_a_code_fence_open():
    from cogs.ai import DISCORD_MESSAGE_LIMIT, _fence_state, _split_for_discord

    text = "mở đầu\n\n```python\n" + "\n".join(f"print({i})" for i in range(900)) + "\n```\n\nkết thúc"
    chunks = _split_for_discord(text)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= DISCORD_MESSAGE_LIMIT
        assert _fence_state(c)[0] is False, "một tin còn fence mở => tin đó render lỗi"
    assert "kết thúc" in chunks[-1], "phần sau code block bị cắt mất"


def test_split_hard_cuts_one_giant_line():
    from cogs.ai import DISCORD_MESSAGE_LIMIT, _split_for_discord

    text = "x" * 7000
    chunks = _split_for_discord(text)
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks)
    assert "".join(chunks) == text


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeChannel:
    id = 42424242

    def __init__(self):
        self.sent = []

    def typing(self):
        return _Typing()

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))


class _FakeUser:
    def __init__(self, uid: int):
        self.id = uid
        self.bot = False
        self.display_name = "Nam"


class _FakeGuild:
    id = 1010


class _FakeMessage:
    def __init__(self, content: str, channel):
        self.content = content
        self.author = _FakeUser(7)
        self.channel = channel
        self.guild = _FakeGuild()
        self.attachments = []
        self.replies = []

    async def reply(self, content, **kwargs):
        self.replies.append((content, kwargs))


async def _run_chat_listener(monkeypatch, answer: str):
    import cogs.ai as ai_mod

    async def fake_api(*a, **kw):
        return answer

    async def fake_enabled(*a, **kw):
        return True

    async def fake_ai_settings(*a, **kw):
        return {"enabled": 1, "ai_channel_id": str(_FakeChannel.id), "rate_limit": 0}

    async def fake_guild_settings(*a, **kw):
        return {"language": "vi"}

    async def fake_global(*a, **kw):
        return "test/model"

    monkeypatch.setattr(ai_mod, "call_ai_api", fake_api)
    monkeypatch.setattr(ai_mod, "async_is_module_enabled", fake_enabled)
    monkeypatch.setattr(ai_mod, "async_get_ai_settings", fake_ai_settings)
    monkeypatch.setattr(ai_mod, "async_get_guild_settings", fake_guild_settings)
    monkeypatch.setattr(ai_mod, "async_get_global_setting", fake_global)

    channel = _FakeChannel()
    message = _FakeMessage("các lệnh mà bot biết là gì", channel)
    await ai_mod.AI(bot=None).on_message(message)
    return [c for c, _ in message.replies] + [c for c, _ in channel.sent], channel


async def test_chat_reply_over_2000_chars_is_delivered_in_full(temp_db, monkeypatch):
    from cogs.ai import DISCORD_MESSAGE_LIMIT

    answer = "\n\n".join(f"**{i}. Tính năng** — " + "mô tả chi tiết " * 15 for i in range(25))
    assert 3000 < len(answer) < 9000, f"ca này cần nằm trong trần 5 tin, độ dài={len(answer)}"

    delivered, _ = await _run_chat_listener(monkeypatch, answer)

    assert len(delivered) > 1, "trả lời >2000 ký tự mà bot chỉ gửi 1 tin => vẫn bị cắt"
    assert all(len(m) <= DISCORD_MESSAGE_LIMIT for m in delivered)
    assert _norm("".join(delivered)) == _norm(answer), "nội dung user nhận được không đủ"


async def test_chat_reply_is_capped_and_says_so(temp_db, monkeypatch):
    from cogs.ai import AI_MAX_CHAT_MESSAGES, DISCORD_MESSAGE_LIMIT

    delivered, channel = await _run_chat_listener(monkeypatch, ("đoạn văn rất dài " * 600))

    assert len(delivered) == AI_MAX_CHAT_MESSAGES, "phải chặn ở trần tin, không spam vô hạn"
    assert all(len(m) <= DISCORD_MESSAGE_LIMIT for m in delivered)
    assert "rút gọn" in delivered[-1], "cắt bớt mà không báo cho user biết"
    # Tin nối tiếp không được ping lại (@everyone trong nội dung AI = spam cả server)
    for _, kwargs in channel.sent:
        allowed = kwargs.get("allowed_mentions")
        assert allowed is not None and allowed.everyone is False


async def test_chat_cap_does_not_leave_a_dangling_fence(temp_db, monkeypatch):
    from cogs.ai import AI_MAX_CHAT_MESSAGES, DISCORD_MESSAGE_LIMIT, _fence_state

    answer = "```python\n" + "\n".join(f"print({i})" for i in range(2000)) + "\n```\n\nphần đuôi"
    delivered, _ = await _run_chat_listener(monkeypatch, answer)

    assert len(delivered) == AI_MAX_CHAT_MESSAGES
    for m in delivered:
        assert len(m) <= DISCORD_MESSAGE_LIMIT, len(m)
        assert _fence_state(m)[0] is False, "tin còn ``` mở => markdown bị vỡ"

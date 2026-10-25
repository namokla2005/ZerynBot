"""P1-3 — AI không vượt ngân sách thời gian/số request, có trần ngày,
main.py không crash khi pgrep không khớp.
"""
import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COGS_DIR = os.path.join(ROOT, "bot", "cogs")
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, _COGS_DIR)
try:
    import ai as ai_cog  # noqa: E402
finally:
    sys.path.remove(_COGS_DIR)

import ai_manager as aim  # noqa: E402


class Fake500:
    status_code = 500
    text = "err"


def test_sync_call_stops_before_request_when_deadline_passed(monkeypatch):
    called = []

    def fake_post(*args, **kwargs):
        called.append(args)
        return Fake500()

    monkeypatch.setattr(aim.requests, "post", fake_post)
    mgr = aim.AIProviderManager()

    ok, err = mgr._call_groq_sync(
        "k", "p", deadline=time.monotonic() - 1, request_budget=[6]
    )
    assert ok is False and err == "BUDGET_EXHAUSTED"
    assert called == []


def test_sync_call_stops_at_request_budget(monkeypatch):
    called = []

    def fake_post(*args, **kwargs):
        called.append(args)
        return Fake500()

    monkeypatch.setattr(aim.requests, "post", fake_post)
    mgr = aim.AIProviderManager()

    ok, err = mgr._call_groq_sync("k", "p", request_budget=[2])
    assert ok is False
    assert len(called) == 2, f"vượt trần request: {len(called)}"
    assert err == "REQUEST_BUDGET_EXHAUSTED"


def test_call_ai_sync_passes_budget_and_deadline_down(monkeypatch):
    seen = {}

    def fake_call(key, prompt, system_instruction="", model="", timeout=12,
                  deadline=None, request_budget=None):
        seen["deadline"] = deadline
        seen["budget"] = request_budget
        seen["timeout"] = timeout
        return False, "HTTP 500"

    mgr = aim.AIProviderManager()
    monkeypatch.setattr(mgr, "load_pools", lambda: {
        "routing_mode": "groq", "model": "qwen/qwen3.8-27b",
        "gemini_keys": [], "groq_keys": ["k1"], "openrouter_keys": [],
    })
    monkeypatch.setattr(mgr, "_get_provider_chain", lambda routing, model: ["groq"])
    monkeypatch.setattr(mgr, "get_next_available_key", lambda provider, keys: keys[0])
    monkeypatch.setattr(mgr, "_call_groq_sync", fake_call)

    ok, _ = mgr.call_ai_sync("hi")
    assert ok is False
    assert isinstance(seen["deadline"], float)
    assert isinstance(seen["budget"], list) and seen["budget"][0] == aim.SYNC_MAX_REQUESTS
    assert seen["timeout"] >= 1


def test_daily_ai_budget_separates_user_and_guild(monkeypatch):
    monkeypatch.setattr(ai_cog, "AI_DAILY_USER_LIMIT", 2)
    monkeypatch.setattr(ai_cog, "AI_DAILY_GUILD_LIMIT", 3)
    ai_cog._ai_daily_user.clear()
    ai_cog._ai_daily_guild.clear()

    assert ai_cog._consume_daily_ai("g1", "u1") is True
    assert ai_cog._consume_daily_ai("g1", "u1") is True
    assert ai_cog._consume_daily_ai("g1", "u1") is False, "vượt trần user"
    assert ai_cog._consume_daily_ai("g1", "u2") is True
    assert ai_cog._consume_daily_ai("g1", "u3") is False, "vượt trần guild"
    assert ai_cog._consume_daily_ai("g2", "u1") is True, "guild khác phải độc lập"


def test_pgrep_pid_handles_no_match(monkeypatch):
    import main

    monkeypatch.setattr(main.os, "name", "posix")

    class R:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: R())
    assert main._pgrep_pid("khong-co-tien-trinh") is None


def test_pgrep_pid_returns_first_pid(monkeypatch):
    import main

    monkeypatch.setattr(main.os, "name", "posix")

    class R:
        returncode = 0
        stdout = "12345\n67890\n"

    monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: R())
    assert main._pgrep_pid("main.py --bot") == 12345


def test_support_daily_cap(monkeypatch):
    import dashboard.support_service as ss

    monkeypatch.setattr(ss, "SUPPORT_AI_DAILY_LIMIT", 2)
    ss._support_daily_counts.clear()

    assert ss._consume_support_budget("u1") is True
    assert ss._consume_support_budget("u1") is True
    assert ss._consume_support_budget("u1") is False
    assert ss._consume_support_budget("u2") is True


def test_chat_first_reply_disables_mentions_source():
    path = os.path.join(ROOT, "bot", "cogs", "ai.py")
    src = open(path, encoding="utf-8").read()
    assert "message.reply(chunks[0], allowed_mentions=no_ping)" in src

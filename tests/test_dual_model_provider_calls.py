# -*- coding: utf-8 -*-
"""O5 — ba provider go nhau qua DUNG mot ham POST/parse, khong con ba ban copy.

Truoc day moi ham co try/requests/parse rieng nen doi timeout hay cach bao loi la phai
nho du ba — va that su da co cho trong do (Gemini thieu tran token output trong khi
Groq/OpenRouter co tu lau).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dm():
    sys.path.insert(0, str(ROOT / "scripts"))
    import dual_model_mcp as m
    return m


class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = text or json.dumps(self._body)

    def json(self):
        return self._body


class _Boom(Exception):
    pass


def test_only_one_http_post_call_site_remains(dm):
    src = (ROOT / "scripts" / "dual_model_mcp.py").read_text(encoding="utf-8")
    assert src.count("requests.post(") == 1, (
        "moi lan them provider ma copy khoi post/parse la them mot cho phai doi timeout"
    )


def test_openai_chat_parses_content(dm, monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"], seen["payload"], seen["timeout"] = url, json, timeout
        return _Resp(200, {"choices": [{"message": {"content": "  xin chao  "}}]})

    monkeypatch.setattr(dm.requests, "post", fake_post)
    ok, out = dm._openai_chat("Groq", "https://x/y", {"h": "1"}, "model-a", "prompt", "sys", 1800)

    assert ok is True and out == "xin chao"
    assert seen["timeout"] == 30, "timeout phai nam o mot cho"
    assert seen["payload"]["max_tokens"] == 1800
    assert seen["payload"]["messages"][0]["role"] == "system"


def test_openai_chat_reports_empty_and_rate_limit(dm, monkeypatch):
    monkeypatch.setattr(dm.requests, "post",
                        lambda *a, **k: _Resp(200, {"choices": [{"message": {"content": "   "}}]}))
    ok, out = dm._openai_chat("Groq", "u", {}, "m", "p", "", 100)
    assert ok is False and "content" in out, out

    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: _Resp(429, {}, "slow down"))
    ok, out = dm._openai_chat("OpenRouter", "u", {}, "m", "p", "", 100)
    assert ok is False and "429" in out and "OpenRouter" in out


def test_openai_chat_survives_a_network_exception(dm, monkeypatch):
    def boom(*a, **k):
        raise _Boom("connection reset")

    monkeypatch.setattr(dm.requests, "post", boom)
    ok, out = dm._openai_chat("Groq", "u", {}, "m", "p", "", 100)

    assert ok is False and "Groq" in out and "connection reset" in out


def test_groq_and_openrouter_use_the_shared_call_with_their_own_limits(dm, monkeypatch):
    captured = []
    monkeypatch.setattr(
        dm.requests, "post",
        lambda url, headers=None, json=None, timeout=None: (
            captured.append((url, json.get("max_tokens"))) or _Resp(200, {"choices": [{"message": {"content": "ok"}}]})
        ),
    )

    dm._call_groq_single("k", "m", "p")
    dm._call_openrouter("k", "m", "p")

    assert captured[0][0].startswith("https://api.groq.com") and captured[0][1] == 1800
    assert captured[1][0].startswith("https://openrouter.ai") and captured[1][1] == 1500


def test_gemini_keeps_its_own_parser_and_output_cap(dm, monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "noi dung"}]}}]})

    monkeypatch.setattr(dm.requests, "post", fake_post)
    ok, out = dm._call_gemini_single("k", "gemini-x", "p", "sys")

    assert ok is True and out == "noi dung"
    assert seen["payload"]["generationConfig"]["maxOutputTokens"], (
        "Gemini phai giu tran output — cai ma ban copy-first da bo sot"
    )


def test_gemini_reports_empty_candidates(dm, monkeypatch):
    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: _Resp(200, {"candidates": []}))
    ok, out = dm._call_gemini_single("k", "m", "p")
    assert ok is False and "candidate" in out

    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: _Resp(404, {}, "not found"))
    ok, out = dm._call_gemini_single("k", "m", "p")
    assert ok is False and "404" in out

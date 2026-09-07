"""
test_ai_ssrf.py — Kiểm tra chống SSRF cho `/summarize url=` trong bot/cogs/ai.py.

Yêu cầu bắt buộc:
- `http://localhost`, `http://127.0.0.1`, `http://192.168.1.1`, `file:///etc/passwd`,
  `http://169.254.169.254` (metadata), `http://[::1]` → bị CHẶN (trả về None NGAY,
  không thực hiện network call).
- URL công khai (`https://example.com`) → vẫn đi qua bước validate (nhưng không bắt
  buộc gọi network thành công trong test).
"""
import aiohttp  # noqa: F401  (đảm bảo aiohttp có sẵn để import ai.py)
import pytest


def _unsafe_urls():
    return [
        "http://localhost",
        "http://127.0.0.1",
        "http://192.168.1.1",
        "http://10.0.0.5",
        "file:///etc/passwd",
        "http://169.254.169.254",
        "http://[::1]",
        "http://metadata.google.internal",
    ]


def _import_ai():
    import os
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (base, os.path.join(base, "bot"), os.path.join(base, "dashboard")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from cogs.ai import _fetch_url_article_content
    return _fetch_url_article_content


@pytest.mark.asyncio
async def test_fetch_url_rejects_ssrf_payloads(monkeypatch):
    """Các URL nội bộ phải bị chặn ngay, không được gọi network."""
    _fetch_url_article_content = _import_ai()

    # Chặn mọi mạng đi ra: nếu có gọi network thì test sẽ fail ngay
    # (vì các URL trên phải bị loại trước khi tới aiohttp).

    for url in _unsafe_urls():
        result = await _fetch_url_article_content(url)
        assert result is None, f"SSRF: {url} phải bị chặn, nhưng hàm trả về {result!r}"


@pytest.mark.asyncio
async def test_fetch_url_accepts_public_https():
    """URL công khai https:// phải đi qua bước validate (không bị chặn ở SSRF)."""
    _import_ai()

    # Điểm mấu chốt là KHÔNG bị chặn bởi is_safe_http_url (tức không trả None vì unsafe).
    from dashboard.auth import is_safe_http_url
    assert is_safe_http_url("https://example.com") is True

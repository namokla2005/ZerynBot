#!/usr/bin/env python3
"""music_source_check.py — Kiểm tra nguồn audio mà bot sẽ dùng (không phát nhạc).

Chạy trên Termux sau khi đặt YTDLP_COOKIEFILE:
    python scripts/music_source_check.py
    python scripts/music_source_check.py --url "https://youtu.be/..."

Exit code:
  0 = primary + Opus audio-only (đường copy, CPU thấp)
  1 = compat/android hoặc audio-only không phải Opus (vẫn phát, CPU cao hơn)
  2 = không lấy được nguồn
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from music.config import (  # noqa: E402
    _COOKIE_FILE,
    get_source_mode,
    primary_ready,
    source_cache_tag,
)
from music.extractor import (  # noqa: E402
    _extract_sync,
    _extract_with_fallback,
    _selected_format,
    _selected_is_audio_only,
    _selected_is_opus,
    _should_try_primary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        help="URL YouTube hoặc từ khóa tìm kiếm",
    )
    args = parser.parse_args()
    query = args.url.strip()
    mode = get_source_mode()

    if _should_try_primary(mode):
        info, used = _extract_with_fallback(query, mode)
    else:
        info, used = _extract_sync(query, "compat"), "compat"

    fmt = _selected_format(info) or {}
    result = {
        "query": query,
        "source_mode": mode,
        "source_tag": source_cache_tag(),
        "cookie_file": _COOKIE_FILE or None,
        "cookie_ready": primary_ready(),
        "used": used,
        "title": (info or {}).get("title"),
        "format_id": fmt.get("format_id"),
        "acodec": fmt.get("acodec"),
        "vcodec": fmt.get("vcodec"),
        "abr": fmt.get("abr"),
        "asr": fmt.get("asr"),
        "protocol": fmt.get("protocol"),
        "audio_only": _selected_is_audio_only(info),
        "is_opus": _selected_is_opus(info),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not info:
        return 2
    if used == "primary" and result["is_opus"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

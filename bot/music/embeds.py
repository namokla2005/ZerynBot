"""
embeds.py — Thanh tiến trình + embed "Now Playing" của trình phát nhạc.

Tách từ `bot/cogs/music.py` (Giai đoạn 3.1). Không import `player` lúc runtime
(chỉ dùng cho type-hint) để tránh vòng import embeds ↔ player.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from i18n import tr

try:
    from emojis import e, embed_title, partial
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, partial

if TYPE_CHECKING:  # chỉ để type-hint — KHÔNG import thật (tránh vòng import)
    from .player import Track


def _make_progress_bar(elapsed_sec: int, total_sec: int | None, bar_length: int = 45) -> str:
    """Tạo thanh tiến trình phát nhạc nét đậm nổi bật theo phong cách Markdown Bold (45 ký tự)."""
    if total_sec is None or not isinstance(total_sec, (int, float)) or total_sec <= 0:
        return f"[**{'━' * bar_length}**](https://zerynbot.id.vn)"

    elapsed_sec = max(0, min(int(elapsed_sec or 0), int(total_sec)))
    ratio = elapsed_sec / total_sec if total_sec > 0 else 0.0
    played_len = max(1, min(bar_length, int(ratio * bar_length)))
    remaining_len = bar_length - played_len

    played_bar = "━" * played_len
    remaining_bar = "━" * remaining_len

    if remaining_len > 0:
        return f"[**{played_bar}**](https://zerynbot.id.vn)**{remaining_bar}**"
    else:
        return f"[**{played_bar}**](https://zerynbot.id.vn)"

def _format_queue_duration(queue: list, current_track: Track = None) -> str:
    total_sec = 0
    has_live = False
    if current_track:
        if current_track.duration is not None and isinstance(current_track.duration, (int, float)) and current_track.duration > 0:
            total_sec += int(current_track.duration)
        else:
            has_live = True
    for t in queue:
        if t.duration is not None and isinstance(t.duration, (int, float)) and t.duration > 0:
            total_sec += int(t.duration)
        else:
            has_live = True
    if total_sec <= 0:
        return "LIVE" if has_live else "0s"
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}h {m}m"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def _make_np_embed(track: Track, queue: list, loop_mode: int, volume: float = 1.0, elapsed_sec: int = 0, settings: dict = None, is_opus_copy: bool = False) -> discord.Embed:
    """Tạo Embed Now Playing chuẩn phong cách Wave Music (Compact card, right thumbnail, bold bar)."""
    s = settings or {}
    if track is None:
        # Người bấm nút điều khiển đúng lúc bài cuối kết thúc thì `player.current` đã
        # là None. Bản cũ chạm `track.duration` -> AttributeError -> Discord chỉ báo
        # "This interaction failed" mà không có manh mối nào cho người dùng.
        return discord.Embed(
            color=0x5865F2,
            description=f"⏹️ {tr(s, 'music.no_song_playing')}",
        )
    vol_percent = int(volume * 100)
    queue_len = len(queue)
    total_dur_str = _format_queue_duration(queue, track)
    np_title = tr(s, "music.now_playing_title") if tr(s, "music.now_playing_title") != "music.now_playing_title" else "Now Playing"
    vol_label = tr(s, "music.np_volume")
    queue_label = tr(s, "music.np_queue")
    dur_label = tr(s, "music.total_duration")
    songs_unit = tr(s, "music.songs_unit")

    dur_badge = track.duration_str if track.duration and track.duration > 0 else "LIVE"
    progress_bar = _make_progress_bar(elapsed_sec, track.duration, bar_length=45)

    embed = discord.Embed(
        color=0x5865F2,  # Discord Blurple (#5865F2) matching Wave Music
        description=(
            f"**{e('zb_play')} {np_title}**\n"
            f"### [{track.title}]({track.url})\n"
            f"**{track.uploader}** — `{dur_badge}` — {track.requester_mention}\n"
            f"─────────────────────────────────────────────\n"
            f"**{vol_label}:** `{vol_percent}%` — **{queue_label}:** `{queue_len} {songs_unit}` — **{dur_label}:** `{total_dur_str}`\n\n"
            f"{progress_bar}"
        )
    )

    # Đặt thumbnail ở góc phải trên cùng thay vì ảnh to choáng màn hình
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

    if is_opus_copy and volume != 1.0:
        embed.set_footer(text=f"ℹ️ {tr(s, 'music.vol_applies_next')}")

    return embed

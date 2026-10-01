"""
music — Package nhạc của ZerynBot V2 (tách từ `bot/cogs/music.py`, Giai đoạn 3.1).

Cấu trúc:
  config.py     hằng số FFmpeg/yt-dlp + YoutubeDL thread-local
  extractor.py  trích xuất metadata & URL stream (yt-dlp, cache 2 tầng)
  embeds.py     thanh tiến trình + embed "Now Playing"
  views.py      nút điều khiển / hàng đợi / tìm kiếm / phân trang lyrics
  player.py     Track + MusicPlayer (vòng đời phát nhạc 1 guild)

Cog thật vẫn nằm ở `bot/cogs/music.py` (loader chỉ quét `bot/cogs/*.py`) và
re-export toàn bộ tên dưới đây để tương thích ngược 100%.
"""

from .config import (
    FFMPEG_BEFORE,
    FFMPEG_OPTS_COPY,
    FFMPEG_OPTS_ENCODE,
    MAX_BG_LOAD,
    MAX_PLAYERS,
    MAX_QUEUE_SIZE,
    YDL_OPTS,
    YDL_OPTS_FLAT,
    _COOKIE_FILE,
    _extract_semaphore,
    _get_ydl,
    _get_ydl_flat,
    _lower_process_priority,
    _thread_local,
)
from .embeds import _format_queue_duration, _make_np_embed, _make_progress_bar
from .extractor import (
    _clean_song_title,
    _compact_song_info,
    _extract_metadata_sync,
    _extract_stream_expire,
    _extract_sync,
    _find_related_track_sync,
    _fmt_duration,
    _get_best_thumbnail,
    _get_spotify_session,
    _get_stream_acodec,
    _get_stream_url,
    _is_duplicate_song,
    _resolve_external_url,
    clean_youtube_query,
    extract_info,
    extract_metadata,
)
from .views import (
    LyricsPaginatorView,
    MusicControlView,
    RemoveSongSelect,
    RemoveSongView,
    SearchSelect,
    SearchSelectView,
    _chunk_lyrics,
    _clean_track_title,
    _fetch_lyrics_from_lrclib,
    _parse_time_str,
)
from .player import MusicPlayer, Track

__all__ = [
    "FFMPEG_BEFORE", "FFMPEG_OPTS_COPY", "FFMPEG_OPTS_ENCODE",
    "MAX_BG_LOAD", "MAX_PLAYERS", "MAX_QUEUE_SIZE",
    "YDL_OPTS", "YDL_OPTS_FLAT", "_COOKIE_FILE", "_extract_semaphore",
    "_get_ydl", "_get_ydl_flat", "_lower_process_priority", "_thread_local",
    "_format_queue_duration", "_make_np_embed", "_make_progress_bar",
    "_clean_song_title", "_compact_song_info", "_extract_metadata_sync",
    "_extract_stream_expire", "_extract_sync", "_find_related_track_sync",
    "_fmt_duration", "_get_best_thumbnail", "_get_spotify_session",
    "_get_stream_acodec", "_get_stream_url", "_is_duplicate_song",
    "_resolve_external_url", "clean_youtube_query", "extract_info", "extract_metadata",
    "LyricsPaginatorView", "MusicControlView", "RemoveSongSelect", "RemoveSongView",
    "SearchSelect", "SearchSelectView", "_chunk_lyrics", "_clean_track_title",
    "_fetch_lyrics_from_lrclib", "_parse_time_str", "MusicPlayer", "Track",
]

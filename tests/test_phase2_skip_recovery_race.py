"""Phase 2 — Cờ `_skipped` không được treo khi user bấm skip lúc player đang bận.

Bất biến phía người dùng: sau khi bấm /skip, hàng đợi BAO GIỜ tiến sang bài kế —
kể cả đúng lúc bot đang backoff khôi phục stream hay đang reconnect voice (là hai
thời điểm user hay bấm skip nhất vì nhạc đang kẹt).

Tái dựng lại lỗi: `_skipped=True` bị các nhánh `return` sớm bỏ lại, còn `_play()`
chặn ở đầu hàm khi thấy cờ -> không bài nào phát được nữa, cho tới khi user bấm
skip LẦN HAI (lúc chẳng còn gì đang phát) hoặc restart bot.
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot"), os.path.join(ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_phase5c_music_watchdog as hw  # noqa: E402


async def _recording_player(**kw):
    P = hw._harness()
    player, vc = await hw._player(**kw)
    player.current = hw._track(P, title="dang-phat")
    player.queue = [hw._track(P, title="bai-ke-tiep")]
    played = []

    async def fake_play(track, seek_offset=0):
        played.append(track.title)

    player._play = fake_play
    return P, player, vc, played


async def test_honour_pending_skip_clears_flag_and_advances():
    _P, player, _vc, played = await _recording_player(playing=False)
    player._skipped = True

    assert await player._honour_pending_skip() is True
    assert player._skipped is False, "cờ phải bị tiêu khi đã chuyển bài"
    assert played == ["bai-ke-tiep"], played


async def test_pending_skip_is_not_consumed_without_voice():
    """Không có voice thì GIỮ cờ + giữ hàng đợi, để luồng reconnect tiêu sau."""
    _P, player, vc, played = await _recording_player(playing=False)
    vc._c = False
    queued = list(player.queue)
    player._skipped = True

    assert await player._honour_pending_skip() is False
    assert player._skipped is True
    assert player.queue == queued
    assert played == []


async def test_skip_during_recovery_backoff_advances_the_queue():
    """Ca H3 gốc: skip rơi vào đúng 2s backoff của nhánh khôi phục bài hát."""
    _P, player, _vc, played = await _recording_player(playing=False)
    cur = player.current

    async def press_skip():
        await asyncio.sleep(0.1)          # luc nay player dang `await asyncio.sleep(2)`
        player._skipped = True

    task = asyncio.create_task(press_skip())
    await player._handle_after_play_async(error=True, elapsed=5, track=cur)
    await task

    assert player._skipped is False, "_skipped treo sau khi recovery return"
    assert played == ["bai-ke-tiep"], (
        f"hàng đợi không tiến (phát lại bài cũ hoặc chết đứng): {played}"
    )


async def test_skip_blocked_by_after_play_guard_is_drained():
    """`vc.play()` đã chạy nhưng `_recovering` còn bật -> after-callback bị chặn ở cửa.

    Đây là khe hẹp mà cờ skip bị bỏ rơi KHÔNG còn nhánh nào khác tiêu hộ.
    """
    _P, player, _vc, played = await _recording_player(playing=True)
    player._recovering = True
    player._skipped = True

    player._after_play()                  # audio thread goi vo, bi chan o cua

    assert played == [], "lẽ ra chưa được phát gì khi recovery còn đang giữ"
    player._recovering = False            # recovery ket thuc
    await asyncio.sleep(0.6)              # drain poll 0.2s lan

    assert player._skipped is False
    assert played == ["bai-ke-tiep"], played


async def test_drain_never_resurrects_a_stopped_player():
    """Task drain không được tự ý phát tiếp sau khi user /stop."""
    _P, player, _vc, played = await _recording_player(playing=True)
    player._recovering = True
    player._skipped = True

    player._after_play()
    player._manual_stopped = True         # /stop xen vao giu chừng
    player._recovering = False
    await asyncio.sleep(0.6)

    assert played == [], f"stop() rồi mà drain vẫn phát: {played}"


async def test_resume_after_reconnect_honours_a_pending_skip():
    """`resume_after_reconnect` từng return sớm khi còn cờ, bỏ `_is_reconnecting=True` mãi."""
    _P, player, vc, played = await _recording_player(playing=False)
    player._is_reconnecting = True
    player._skipped = True

    await player.resume_after_reconnect()

    assert player._skipped is False
    assert played == ["bai-ke-tiep"], played
    assert player._is_reconnecting is False, "luồng reconnect phải đóng cờ ở finally"

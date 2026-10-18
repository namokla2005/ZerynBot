# -*- coding: utf-8 -*-
"""taskbag — giữ strong reference cho tác vụ fire-and-forget.

Event loop CHỈ giữ tham chiếu yếu tới task do `create_task()` trả về (theo tài liệu
Python): không giữ lại thì task có thể bị garbage-collect giữa chừng và coroutine
chưa từng chạy tới dòng cuối — không exception, không log, chỉ có dữ liệu biến mất.
Đã thấy dạng này với `async_log_activity` và `async_increment_stat` trên Termux.
"""
from __future__ import annotations

import asyncio

_BAG: set[asyncio.Task] = set()


def spawn(coro, *, name: str = "") -> asyncio.Task | None:
    """Chạy `coro` nền và giữ nó sống tới khi xong. Trả về None khi không có loop."""
    try:
        task = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    except RuntimeError:
        # Không có event loop đang chạy: đóng coroutine để không để lại
        # "coroutine was never awaited" và để caller đi tiếp đường đồng bộ.
        coro.close()
        return None
    _BAG.add(task)
    task.add_done_callback(_BAG.discard)
    return task


def pending_count() -> int:
    """Số task đang chờ — phục vụ test và self-check."""
    return len(_BAG)

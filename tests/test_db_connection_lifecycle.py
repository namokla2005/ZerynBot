# -*- coding: utf-8 -*-
"""O1 — mọi kết nối SQLite phải được ĐÓNG, không phó mặc fd cho GC.

Bat bien: sau khi dung `with _connect_sync() as db:` thi ket noi o trang thai
`closed` that, van commit du lieu binh an, va so fd mo khong tang theo so lan goi.
"""
import os
import sqlite3

import pytest

import database
from database.conn import _connect_sync


def _closed(conn) -> bool:
    """sqlite3 khong lo `closed` ra ngoai — thu dung thao mao, no phai cheu."""
    try:
        conn.execute("SELECT 1").fetchone()
    except sqlite3.ProgrammingError:
        return True
    return False


@pytest.fixture(autouse=True)
def _fresh_db(temp_db):
    database.init_db()
    yield


def test_with_block_closes_the_connection():
    with _connect_sync() as conn:
        conn.execute("SELECT 1").fetchone()
        assert not _closed(conn), "bên trong `with` vẫn phải dùng được bình thường"
    assert _closed(conn), (
        "sqlite3.Connection.__exit__ chi commit/rollback — neu khong tu close thi "
        "fd song toi luc GC thuong"
    )


def test_data_written_inside_with_is_committed_and_readable():
    with _connect_sync() as conn:
        conn.execute(
            "INSERT INTO guilds (guild_id) VALUES (?)", ("g_o1_commit",)
        )

    with _connect_sync() as check:
        row = check.execute(
            "SELECT guild_id FROM guilds WHERE guild_id = ?", ("g_o1_commit",)
        ).fetchone()
    assert row is not None, "dong boi vi close som hon commit"


def test_exception_inside_with_rolls_back_and_still_closes():
    with pytest.raises(RuntimeError):
        with _connect_sync() as conn:
            conn.execute("INSERT INTO guilds (guild_id) VALUES (?)", ("g_o1_rollback",))
            raise RuntimeError("buoc roi giua chung")
    assert _closed(conn)

    with _connect_sync() as check:
        row = check.execute(
            "SELECT guild_id FROM guilds WHERE guild_id = ?", ("g_o1_rollback",)
        ).fetchone()
    assert row is None, "rollback phai giu nguyen nhu truoc khi ghi"


def test_get_db_connection_still_closes_once_only():
    from database.conn import get_db_connection

    with get_db_connection() as conn:
        conn.execute("SELECT 1").fetchone()
    assert _closed(conn)


@pytest.mark.skipif(os.name != "posix", reason="dem fd can /proc (Linux/Termux/CI)")
def test_file_descriptors_do_not_grow_with_connection_count():
    """Dung 300 ket noi ma fd tang lien tuc la dung cai loi O1 mo ta."""
    def open_fds():
        return len(os.listdir(f"/proc/{os.getpid()}/fd"))

    base = open_fds()
    for _ in range(300):
        with _connect_sync() as conn:
            conn.execute("SELECT 1").fetchone()
    after = open_fds()

    assert after <= base + 5, f"fd tang {after - base} sau 300 lan mo/dong ket noi"


def test_raw_caller_still_gets_a_usable_connection():
    """bot/tester.py goi tho (khong `with`) thi van phai dung duoc."""
    probe = _connect_sync(timeout=5.0)
    try:
        assert probe.execute("PRAGMA foreign_keys").fetchone() is not None
    finally:
        probe.close()
    assert _closed(probe)

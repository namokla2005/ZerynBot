"""Tests cho database.py — CRUD cơ bản trên DB SQLite tạm (không đụng data thật)."""


def test_init_db_creates_tables(temp_db):
    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for required in ("guilds", "guild_modules", "economy_users", "user_levels"):
        assert required in tables, f"thiếu bảng {required}"


def test_wal_mode_enabled(temp_db):
    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"


def test_upsert_and_get_guild_settings(temp_db):
    import database as db
    db.upsert_guild("123", welcome_message="Xin chào!", language="en")
    settings = db.get_guild_settings("123")
    assert settings["welcome_message"] == "Xin chào!"
    assert settings["language"] == "en"


def test_module_toggle_roundtrip(temp_db):
    import database as db
    db.set_module("123", "music", True)
    db.set_module("123", "economy", False)
    modules = db.get_guild_modules("123")
    assert modules["music"] is True
    assert modules["economy"] is False
    # Toggle lại
    db.set_module("123", "economy", True)
    assert db.get_guild_modules("123")["economy"] is True


def test_economy_balance_sync(temp_db):
    import database as db
    db.update_user_balance("123", "user1", 1000, 500)
    db.update_user_balance("123", "user1", 1200, 500)  # update chồng
    rows = db.get_top_economy_users("123", limit=5)
    assert rows[0]["wallet"] == 1200
    assert rows[0]["bank"] == 500


async def test_economy_claim_daily_async(temp_db):
    import database as db
    result = await db.async_claim_daily("123", "user1", 100, 1)
    assert result["wallet"] >= 100
    assert result["daily_streak"] >= 1


def test_track_playlist_lookup(temp_db):
    import database as db
    # Tạo playlist + track rồi tra ngược playlist từ track (dùng cho kiểm quyền)
    playlist_id = db.create_playlist("123", "Test PL", "user1", "Tester")
    track_id = db.add_track_to_playlist(playlist_id, {
        "title": "song", "url": "https://youtu.be/x", "duration": 180,
        "webpage_url": "https://youtu.be/x", "thumbnail": "", "uploader": "u",
    })
    found = db.get_playlist_of_track(track_id)
    assert found is not None
    assert str(found["guild_id"]) == "123"
    assert db.get_playlist_of_track(999999) is None


# ─── Regression: job prune từng xóa SẠCH reminder chưa tới hạn ─────────────────
# `reminders.remind_at` là INTEGER epoch giây, nhưng câu prune so nó với
# `datetime('now','-30 days')` (TEXT). SQLite xếp mọi INTEGER nhỏ hơn mọi TEXT nên
# vị từ luôn đúng → người dùng mất alarm trong 24h mà không có lỗi nào được log.

async def test_prune_keeps_future_reminders(temp_db):
    import time
    import sqlite3
    import database as db

    future = int(time.time()) + 7 * 86400          # reminder 7 ngày nữa
    expired = int(time.time()) - 365 * 86400       # reminder quá hạn 1 năm
    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, reason, remind_at)"
            " VALUES ('u1','123','456','uống thuốc',?)", (future,),
        )
        conn.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, reason, remind_at)"
            " VALUES ('u2','123','456','hết hạn rồi',?)", (expired,),
        )
        conn.commit()

    await db.async_prune_old_data(reminders_days=30)

    with sqlite3.connect(temp_db) as conn:
        rows = conn.execute("SELECT user_id, remind_at FROM reminders").fetchall()
    assert [r[0] for r in rows] == ["u1"], (
        f"prune phải GIỮ reminder chưa tới hạn và chỉ xóa cái quá hạn, thực tế: {rows}"
    )
    assert rows[0][1] == future


def test_every_connection_enforces_foreign_keys(temp_db):
    """FK khai báo trong schema chỉ có tác dụng khi per-connection PRAGMA được bật."""
    import sqlite3
    import database as db

    conn = db._connect_sync() if hasattr(db, "_connect_sync") else None
    if conn is None:
        from database.conn import _connect_sync
        conn = _connect_sync()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_delete_playlist_removes_child_tracks(temp_db):
    """Bật FK rồi thì xóa playlist phải dọn cả hàng đợi con (không để orphan)."""
    import sqlite3
    import database as db

    playlist_id = db.create_playlist("123", "Cascade PL", "u1", "Tester")
    db.add_track_to_playlist(playlist_id, {
        "title": "s", "url": "https://youtu.be/s", "duration": 100,
        "webpage_url": "https://youtu.be/s", "thumbnail": "", "uploader": "u",
    })
    db.delete_playlist(playlist_id, "123")

    with sqlite3.connect(temp_db) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM music_playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
    assert orphans == 0, "xóa playlist để lại track mồ côi"


def test_insert_track_into_missing_playlist_is_rejected(temp_db):
    """Chứng minh FK thật sự enforce: chèn track không có playlist phải raise."""
    import sqlite3
    import pytest

    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO music_playlist_tracks (playlist_id, title, url, duration, position)"
                " VALUES (999999, 'x', 'https://youtu.be/x', 1, 1)",
            )
    finally:
        conn.close()


# ─── Regression: backup bằng copy file nóng mất dữ liệu đang nằm trong WAL ──────
# `zipfile.write('data/bot.db')` bỏ sót `bot.db-wal`, mà các trang đã commit vẫn
# nằm trong WAL cho tới khi checkpoint → bản backup torn, restore mất giao dịch.

def test_snapshot_database_captures_uncheckpointed_wal(temp_db):
    import os
    import sqlite3
    import database as db

    # Ghi 1 giao dịch rồi GIỮ WAL (không checkpoint) — mô phỏng DB đang chạy 24/7.
    writer = sqlite3.connect(temp_db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO guilds (guild_id, language) VALUES ('777', 'vi')")
    writer.commit()

    dest = temp_db + ".snapshot"
    snap = None
    try:
        size = db.snapshot_database(dest)
        assert size > 0
        snap = sqlite3.connect(dest)
        # 1. Giao dịch mới nhất (chỉ trong WAL) PHẢI có mặt trong snapshot.
        assert snap.execute(
            "SELECT language FROM guilds WHERE guild_id='777'"
        ).fetchone()[0] == "vi"
        # 2. Snapshot phải là DB nhất quán, không torn.
        assert snap.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        if snap is not None:
            snap.close()
        writer.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(dest + suffix):
                os.remove(dest + suffix)


def test_snapshot_database_is_not_a_raw_file_copy(temp_db):
    """Snapshot phải đọc được cả dữ liệu trong WAL, khác với copy file thô."""
    import os
    import shutil
    import sqlite3
    import database as db

    conn = sqlite3.connect(temp_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO guilds (guild_id, language) VALUES ('888', 'en')")
    conn.commit()

    raw = temp_db + ".rawcopy"
    snap = temp_db + ".snap"
    c_raw = c_snap = None
    try:
        shutil.copyfile(temp_db, raw)          # cách cũ: copy mỗi file .db
        db.snapshot_database(snap)
        c_raw = sqlite3.connect(raw)
        c_snap = sqlite3.connect(snap)
        in_snap = c_snap.execute("SELECT COUNT(*) FROM guilds WHERE guild_id='888'").fetchone()[0]
        try:
            in_raw = c_raw.execute("SELECT COUNT(*) FROM guilds WHERE guild_id='888'").fetchone()[0]
        except sqlite3.OperationalError:
            # Bản copy thô không có cả schema (toàn bộ trang mới nằm trong WAL).
            in_raw = None
        assert in_snap == 1, "snapshot phải chứa dữ liệu đang nằm trong WAL"
        assert in_raw in (0, None), (
            "copy file thô không đọc được dữ liệu WAL (ở đây in_raw=%r) — đây chính "
            "là lý do phải bỏ zf.write(db_path) trong backup" % in_raw
        )
    finally:
        for c in (c_raw, c_snap):
            if c is not None:
                c.close()
        conn.close()
        for p in (raw, snap, snap + "-wal", snap + "-shm"):
            if os.path.exists(p):
                os.remove(p)

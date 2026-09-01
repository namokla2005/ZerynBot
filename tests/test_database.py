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

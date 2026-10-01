"""
test_database_api_surface.py — Chốt "hợp đồng công khai" của database.py (Giai đoạn 3).

Hai mục đích:
1. Khi tách `database.py` (4262 dòng) thành package `database/`, danh sách hàm
   công khai PHẢI giữ nguyên — 30+ file đang `from database import (...)`.
   Test này đỏ ngay nếu một hàm bị bỏ sót khi di chuyển.
2. `get_db_path()` / `set_db_path()` là API duy nhất được phép trỏ DB, và mọi
   kết nối phải đi theo đường đó — nếu không, test có thể ghi vào
   `data/bot.db` thật (rủi ro lớn nhất của GĐ3).
"""
import asyncio
import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE_DIR, os.path.join(BASE_DIR, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── Hợp đồng công khai (chụp TRƯỚC khi tách package) ───────────────────────────
# Nguồn: dir(database) lọc theo hàm/hằng số do chính module database định nghĩa.
DATABASE_PUBLIC_API = [
    "BASE_DIR", "DB_PATH",
    "add_custom_command", "add_economy_shop_item", "add_support_message",
    "add_to_blacklist", "add_track_to_playlist",
    "async_add_active_temp_channel", "async_add_automod_warning", "async_add_custom_command",
    "async_add_inventory_item", "async_add_love_points", "async_add_mod_warning",
    "async_add_reminder", "async_add_to_blacklist", "async_add_track_to_playlist",
    "async_buy_shop_item", "async_cache_channels", "async_cache_guild", "async_cache_roles",
    "async_claim_daily", "async_claim_economy_cooldown", "async_clear_automod_warnings",
    "async_count_guild_custom_commands", "async_count_mod_warnings", "async_count_user_custom_commands",
    "async_create_giveaway", "async_create_marriage", "async_create_playlist",
    "async_delete_custom_command", "async_delete_marriage", "async_delete_mod_warning",
    "async_delete_playlist", "async_delete_reminder", "async_delete_song_cache",
    "async_delete_track_from_playlist", "async_deposit_money", "async_find_custom_command",
    "async_get_active_giveaways", "async_get_active_temp_channel", "async_get_ai_settings",
    "async_get_all_ticket_panels", "async_get_automod_settings", "async_get_birthday",
    "async_get_birthday_settings", "async_get_birthdays_today", "async_get_custom_commands",
    "async_get_due_reminders", "async_get_economy_cooldown", "async_get_economy_settings",
    "async_get_economy_shop", "async_get_economy_user", "async_get_fun_interaction_count",
    "async_get_giveaway", "async_get_global_setting", "async_get_guild_modules",
    "async_get_guild_settings", "async_get_inventory", "async_get_inventory_item",
    "async_get_level_roles", "async_get_leveling_settings", "async_get_logger_settings",
    "async_get_maintenance_job", "async_get_marriage", "async_get_mod_warnings",
    "async_get_playlist_by_name", "async_get_playlist_tracks", "async_get_playlists",
    "async_get_reaction_role_item", "async_get_recent_guild_events", "async_get_saved_embed_by_name",
    "async_get_saved_embeds", "async_get_song_cache", "async_get_system_activity_logs",
    "async_get_tempvoice_settings", "async_get_ticket_button", "async_get_top_economy",
    "async_get_top_played_songs", "async_get_top_users", "async_get_upcoming_birthdays",
    "async_get_user_level", "async_get_user_rank", "async_get_user_reminders",
    "async_get_user_transactions", "async_get_user_xp", "async_get_verify_settings",
    "async_increment_custom_command_usage", "async_increment_fun_interaction", "async_increment_stat",
    "async_is_blacklisted", "async_is_module_enabled", "async_log_activity",
    "async_log_ai_activity", "async_log_transaction", "async_modify_wallet",
    "async_place_bet", "async_prune_old_data", "async_refund_shop_purchase",
    "async_remove_active_temp_channel", "async_remove_birthday", "async_remove_guild",
    "async_reset_user_xp", "async_sell_all_inventory", "async_sell_inventory_item",
    "async_set_birthday", "async_set_economy_cooldown", "async_set_guild_language",
    "async_set_maintenance_job", "async_set_song_cache", "async_transfer_money",
    "async_update_automod_settings", "async_update_giveaway", "async_update_temp_channel_lock",
    "async_update_user_xp", "async_upsert_birthday_settings", "async_upsert_verify_settings",
    "async_vacuum_db", "async_wal_checkpoint", "async_withdraw_money",
    "atomic_escalate_support_thread", "create_playlist", "delete_custom_command",
    "delete_economy_shop_item", "delete_embed", "delete_playlist",
    "delete_reaction_roles_panel", "delete_ticket_panel", "delete_track_from_playlist",
    "get_active_temp_channels", "get_ai_activity_snapshot", "get_ai_settings",
    "get_all_support_threads", "get_automod_settings", "get_birthday_settings_sync",
    "get_birthdays_this_month_count", "get_blacklist", "get_bot_guild_ids",
    "get_custom_command", "get_custom_commands", "get_db_connection",
    "get_db_path", "get_economy_settings", "get_economy_shop", "get_global_setting",
    "get_guild_categories", "get_guild_channels", "get_guild_meta", "get_guild_modules",
    "get_guild_roles", "get_guild_settings", "get_guild_stats", "get_guild_voice_channels",
    "get_level_roles", "get_leveling_settings", "get_logger_settings", "get_marriages_count_sync",
    "get_mod_warnings_count_sync", "get_or_create_support_thread", "get_playlist",
    "get_playlist_by_name", "get_playlist_of_track", "get_playlist_tracks",
    "get_playlists", "get_reaction_roles_panel", "get_reaction_roles_panels",
    "get_recent_guild_events", "get_saved_embeds", "get_support_messages",
    "get_support_thread", "get_system_activity_logs", "get_tempvoice_settings",
    "get_ticket_panel", "get_ticket_panels", "get_top_economy_users",
    "get_top_played_songs", "get_top_users", "get_verify_settings",
    "init_db", "invalidate_custom_commands_cache", "is_blacklisted",
    "log_activity", "log_ai_activities_batch", "log_ai_activity",
    "mark_support_thread_read", "remove_from_blacklist", "save_embed",
    "save_reaction_roles_panel", "save_ticket_panel", "set_db_path",
    "set_global_setting", "set_guild_language", "set_level_roles",
    "set_leveling_settings", "set_logger_settings", "set_module",
    "set_module_enabled", "update_ai_settings", "update_custom_command",
    "update_economy_settings", "update_panel_message_id", "update_reaction_roles_message_id",
    "update_support_thread_status", "update_tempvoice_settings", "update_user_balance",
    "upsert_automod_settings", "upsert_birthday_settings_sync", "upsert_guild",
    "upsert_verify_settings", "wal_checkpoint",
]


def _is_db_api(name: str) -> bool:
    """True nếu tên thuộc về chính module database (không phải import kèm)."""
    import database

    obj = getattr(database, name)
    if callable(obj):
        mod = (getattr(obj, "__module__", "") or "").split(".")[0]
        return mod == "database"
    return name in ("BASE_DIR", "DB_PATH")


def test_public_api_not_shrunk():
    """Không được mất bất kỳ hàm công khai nào khi tách package."""
    import database

    missing = [n for n in DATABASE_PUBLIC_API if not hasattr(database, n)]
    assert not missing, f"database thiếu {len(missing)} tên công khai: {missing[:20]}"


def test_public_api_still_owned_by_database_module():
    """Các hàm phải thuộc package `database` (kể cả submodule sau khi tách)."""
    import database

    wrong = []
    for name in DATABASE_PUBLIC_API:
        obj = getattr(database, name, None)
        if obj is None:
            continue
        if callable(obj) and not _is_db_api(name):
            wrong.append((name, getattr(obj, "__module__", "?")))
    assert not wrong, f"Tên bị 'rơi' sang module khác: {wrong[:10]}"


def test_public_api_count_not_reduced():
    """Đếm theo cách linh hoạt hơn danh sách cứng: số hàm công khai không giảm."""
    import database

    names = {n for n in dir(database) if not n.startswith("_") and _is_db_api(n)}
    assert len(names) >= len(DATABASE_PUBLIC_API), (
        f"API surface co lại: {len(names)} < {len(DATABASE_PUBLIC_API)}"
    )


# ─── Đường dẫn DB: một nguồn duy nhất ──────────────────────────────────────────

def test_set_db_path_is_the_single_source_of_truth(tmp_path):
    import database

    old = database.get_db_path()
    target = tmp_path / "custom.db"
    try:
        database.set_db_path(str(target))
        assert database.get_db_path() == str(target)
        assert database.DB_PATH == str(target)

        database.init_db()
        assert target.exists(), "init_db() phải tạo schema ở file DB mới"
    finally:
        database.set_db_path(old)
    assert database.get_db_path() == old


def test_sync_writes_go_to_current_db_path(tmp_path):
    """Ghi qua _connect_sync/get_db_connection rơi đúng file DB đang được trỏ."""
    import database

    old = database.get_db_path()
    target = tmp_path / "sync.db"
    real_db = os.path.join(BASE_DIR, "data", "bot.db")
    real_mtime_before = os.path.getmtime(real_db) if os.path.exists(real_db) else None

    try:
        database.set_db_path(str(target))
        database.init_db()

        # 1. Qua helper riêng tư của module
        conn = database._connect_sync()
        conn.execute("INSERT OR REPLACE INTO guilds (guild_id) VALUES ('test-sync')")
        conn.commit()
        conn.close()

        # 2. Qua context manager công khai
        with database.get_db_connection() as c:
            row = c.execute("SELECT guild_id FROM guilds WHERE guild_id='test-sync'").fetchone()
        assert row is not None and row[0] == "test-sync"

        # 3. Kiểm chứng dữ liệu thật sự nằm trong file tạm
        with sqlite3.connect(str(target)) as raw:
            assert raw.execute("SELECT COUNT(*) FROM guilds").fetchone()[0] >= 1
    finally:
        database.set_db_path(old)

    # DB thật (nếu tồn tại) không được bị ghi bởi test này
    if real_mtime_before is not None and os.path.exists(real_db):
        assert os.path.getmtime(real_db) == real_mtime_before


def test_async_writes_go_to_current_db_path(tmp_path):
    """Đường async (aiosqlite) cũng phải theo get_db_path()."""
    import database

    old = database.get_db_path()
    target = tmp_path / "async.db"

    async def _scenario():
        await database.async_upsert_verify_settings(
            "123", enabled=1, channel_id="456", verified_role_id="789"
        )
        settings = await database.async_get_verify_settings("123")
        assert settings is not None and settings["enabled"] == 1
        return settings

    try:
        database.set_db_path(str(target))
        database.init_db()
        assert asyncio.run(_scenario()) is not None
    finally:
        database.set_db_path(old)

    with sqlite3.connect(str(target)) as raw:
        assert raw.execute("SELECT COUNT(*) FROM verify_settings").fetchone()[0] == 1


def test_init_db_creates_parent_directory(tmp_path):
    """init_db() phải tạo thư mục cha nếu chưa có (Termux cài mới)."""
    import database

    old = database.get_db_path()
    target = tmp_path / "nested" / "deep" / "bot.db"
    try:
        database.set_db_path(str(target))
        database.init_db()
        assert target.exists()
    finally:
        database.set_db_path(old)


def test_privacy_of_real_db_in_whole_test_suite(temp_db):
    """Fixture temp_db phải cô lập DB: test không bao giờ ghi vào data/bot.db thật."""
    import database

    real_db = os.path.join(BASE_DIR, "data", "bot.db")
    assert database.get_db_path() == temp_db
    assert database.get_db_path() != real_db

    # Ghi qua đúng đường production (get_db_connection) → file thật không bị tạo/đổi
    mtime_before = os.path.getmtime(real_db) if os.path.exists(real_db) else None
    with database.get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO guilds (guild_id) VALUES ('privacy-check')")
        conn.commit()
    if mtime_before is not None:
        assert os.path.getmtime(real_db) == mtime_before
    else:
        assert not os.path.exists(real_db)

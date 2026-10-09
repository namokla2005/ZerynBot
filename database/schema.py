"""
schema.py — Khởi tạo schema SQLite (bảng, index, migration nhẹ).

Tách từ `database.py` (Giai đoạn 3.3). Đây là nguồn duy nhất tạo bảng cho cả bot
và dashboard; mọi test dùng DB tạm đều gọi `init_db()`.
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional
import os

import aiosqlite

from cache import cache

from .conn import _connect_async, _connect_sync, _row_to_dict, get_db_connection, get_db_path

logger = logging.getLogger("ZerynBot.Database")

def init_db():
    """Create all tables if they don't exist (sync, called at startup)."""
    os.makedirs(os.path.dirname(get_db_path()), exist_ok=True)
    with _connect_sync() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id              TEXT PRIMARY KEY,
                welcome_channel_id    TEXT,
                welcome_message       TEXT DEFAULT 'Xin chào {user}, chào mừng đến với **{server}**! 🎉',
                welcome_use_embed     INTEGER DEFAULT 1,
                welcome_embed_color   TEXT DEFAULT '#57F287',
                welcome_embed_title   TEXT DEFAULT '🎉 Chào mừng thành viên mới!',
                welcome_bg_url        TEXT,
                goodbye_channel_id    TEXT,
                goodbye_message       TEXT DEFAULT 'Tạm biệt **{user_name}**, chúc bạn nhiều may mắn! 👋',
                goodbye_use_embed     INTEGER DEFAULT 1,
                goodbye_embed_color   TEXT DEFAULT '#ED4245',
                goodbye_embed_title   TEXT DEFAULT '👋 Tạm biệt!',
                goodbye_bg_url        TEXT,
                language              TEXT DEFAULT 'vi',
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS guild_modules (
                guild_id    TEXT,
                module_name TEXT,
                enabled     INTEGER DEFAULT 1,
                PRIMARY KEY (guild_id, module_name)
            );

            CREATE TABLE IF NOT EXISTS guild_channels (
                guild_id        TEXT,
                channel_id      TEXT,
                channel_name    TEXT,
                channel_type    INTEGER,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS guild_roles (
                guild_id        TEXT,
                role_id         TEXT,
                role_name       TEXT,
                color_hex       TEXT,
                position        INTEGER,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS guild_meta (
                guild_id        TEXT PRIMARY KEY,
                guild_name      TEXT,
                guild_icon      TEXT,
                member_count    INTEGER,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS saved_embeds (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                name        TEXT NOT NULL,
                embed_json  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ticket_panels (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id       TEXT NOT NULL,
                channel_id     TEXT NOT NULL,
                name           TEXT NOT NULL,
                title          TEXT,
                description    TEXT,
                color          TEXT DEFAULT '#5865F2',
                image_url      TEXT,
                thumbnail_url  TEXT,
                footer_text    TEXT,
                support_role_id TEXT,
                message_id     TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reaction_roles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                message_id  TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                emoji       TEXT NOT NULL,
                role_id     TEXT NOT NULL,
                FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ticket_buttons (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id       INTEGER NOT NULL,
                label          TEXT NOT NULL,
                style          TEXT DEFAULT 'primary',
                category_id    TEXT NOT NULL,
                FOREIGN KEY (panel_id) REFERENCES ticket_panels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS music_playlists (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id       TEXT NOT NULL,
                name           TEXT NOT NULL,
                creator_id     TEXT,
                creator_name   TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS music_song_cache (
                cache_key   TEXT PRIMARY KEY,
                payload     TEXT NOT NULL,
                created_at  REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS music_playlist_tracks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id    INTEGER NOT NULL,
                title          TEXT NOT NULL,
                url            TEXT NOT NULL,
                duration       INTEGER,
                webpage_url    TEXT,
                thumbnail      TEXT,
                uploader       TEXT,
                position       INTEGER,
                FOREIGN KEY (playlist_id) REFERENCES music_playlists(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reaction_roles_panels (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id       TEXT NOT NULL,
                channel_id     TEXT NOT NULL,
                name           TEXT NOT NULL,
                title          TEXT,
                description    TEXT,
                color          TEXT DEFAULT '#5865F2',
                image_url      TEXT,
                thumbnail_url  TEXT,
                footer_text    TEXT,
                message_id     TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reaction_roles_items (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id       INTEGER NOT NULL,
                emoji          TEXT NOT NULL,
                role_id        TEXT NOT NULL,
                FOREIGN KEY (panel_id) REFERENCES reaction_roles_panels(id) ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS automod_settings (
                guild_id        TEXT PRIMARY KEY,
                bad_words       TEXT DEFAULT '[]',
                blacklist_links TEXT DEFAULT '[]',
                whitelist_links TEXT DEFAULT '[]',
                spam_enabled    INTEGER DEFAULT 0,
                bad_words_enabled INTEGER DEFAULT 0,
                links_enabled   INTEGER DEFAULT 0,
                notify_role_id  TEXT,
                log_channel_id  TEXT,
                anti_raid_enabled       INTEGER DEFAULT 0,
                raid_join_per_window    INTEGER DEFAULT 5,
                raid_action             TEXT DEFAULT 'lockdown',
                anti_nuke_enabled       INTEGER DEFAULT 0,
                nuke_actions            TEXT DEFAULT '["channel_delete","role_delete","guild_update"]'
            );

            CREATE TABLE IF NOT EXISTS automod_warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT,
                user_id     TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS maintenance_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_key     TEXT UNIQUE NOT NULL,
                last_run_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS leveling_settings (
                guild_id            TEXT PRIMARY KEY,
                message_xp_min      INTEGER DEFAULT 15,
                message_xp_max      INTEGER DEFAULT 25,
                voice_xp            INTEGER DEFAULT 10,
                announce_channel_id TEXT,
                announce_message    TEXT DEFAULT '🎉 Chúc mừng {user} đã đạt cấp **{level}**!',
                stack_rewards       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id            TEXT,
                user_id             TEXT,
                xp                  INTEGER DEFAULT 0,
                level               INTEGER DEFAULT 0,
                last_message_at     TIMESTAMP DEFAULT 0,
                last_voice_xp_at    TIMESTAMP DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS level_roles (
                guild_id    TEXT,
                level       INTEGER,
                role_id     TEXT,
                PRIMARY KEY (guild_id, level, role_id)
            );

            CREATE TABLE IF NOT EXISTS logger_settings (
                guild_id                TEXT PRIMARY KEY,
                log_channel_id          TEXT,
                log_message_edit        INTEGER DEFAULT 1,
                log_message_delete      INTEGER DEFAULT 1,
                log_member_join_leave   INTEGER DEFAULT 1,
                log_member_kick_ban     INTEGER DEFAULT 1,
                log_member_role_change  INTEGER DEFAULT 1,
                log_channel_change      INTEGER DEFAULT 1,
                log_role_change         INTEGER DEFAULT 1,
                log_automod             INTEGER DEFAULT 1,
                log_ticket              INTEGER DEFAULT 1
            );
            
            CREATE TABLE IF NOT EXISTS guild_stats (
                guild_id    TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                event_label TEXT NOT NULL,
                date_hour   TEXT NOT NULL,
                count       INTEGER DEFAULT 1,
                PRIMARY KEY (guild_id, event_type, event_label, date_hour)
            );
            
            CREATE TABLE IF NOT EXISTS giveaways (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id             TEXT,
                channel_id           TEXT,
                message_id           TEXT,
                host_id              TEXT,
                prize                TEXT,
                winners_count        INTEGER DEFAULT 1,
                end_at               TIMESTAMP,
                ended                INTEGER DEFAULT 0,
                req_role_id          TEXT,
                req_account_age_days INTEGER DEFAULT 0,
                participants_json    TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS guild_blacklist (
                guild_id   TEXT PRIMARY KEY,
                guild_name TEXT,
                reason     TEXT,
                kicked_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS economy_settings (
                guild_id            TEXT PRIMARY KEY,
                daily_amount        INTEGER DEFAULT 100,
                streak_bonus        INTEGER DEFAULT 20,
                starting_balance    INTEGER DEFAULT 50,
                currency_symbol     TEXT DEFAULT '🪙',
                currency_name       TEXT DEFAULT 'Coins'
            );

            CREATE TABLE IF NOT EXISTS economy_users (
                guild_id        TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                wallet          INTEGER DEFAULT 50,
                bank            INTEGER DEFAULT 0,
                daily_streak    INTEGER DEFAULT 0,
                last_daily_at   REAL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS economy_shop (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                role_id     TEXT NOT NULL,
                name        TEXT NOT NULL,
                price       INTEGER NOT NULL DEFAULT 100,
                stock       INTEGER DEFAULT -1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_inventory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                item_id     TEXT NOT NULL,
                item_name   TEXT NOT NULL,
                item_type   TEXT NOT NULL,
                rarity      TEXT DEFAULT 'common',
                quantity    INTEGER DEFAULT 1,
                sell_price  INTEGER DEFAULT 50,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS economy_cooldowns (
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                action_type TEXT NOT NULL,
                last_used   REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, action_type)
            );

            CREATE INDEX IF NOT EXISTS idx_inventory_lookup ON user_inventory (guild_id, user_id);

            CREATE TABLE IF NOT EXISTS economy_transactions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                kind            TEXT NOT NULL,
                amount          INTEGER NOT NULL,
                counterparty    TEXT,
                note            TEXT,
                created_at      REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_econ_tx ON economy_transactions (guild_id, user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS tempvoice_settings (
                guild_id            TEXT PRIMARY KEY,
                enabled             INTEGER DEFAULT 0,
                hub_channel_id      TEXT,
                category_id         TEXT,
                name_template       TEXT DEFAULT '🔊 Phòng của {user}',
                default_limit       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tempvoice_active (
                channel_id      TEXT PRIMARY KEY,
                guild_id        TEXT NOT NULL,
                owner_id        TEXT NOT NULL,
                is_locked       INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS custom_commands (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT NOT NULL,
                trigger         TEXT NOT NULL,
                match_type      TEXT DEFAULT 'exact',
                response_text   TEXT,
                embed_json      TEXT,
                is_enabled      INTEGER DEFAULT 1,
                uses_count      INTEGER DEFAULT 0,
                creator_id      TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ai_settings (
                guild_id            TEXT PRIMARY KEY,
                enabled             INTEGER DEFAULT 0,
                ai_channel_id       TEXT,
                personality_preset  TEXT DEFAULT 'friendly',
                custom_prompt       TEXT DEFAULT '',
                allow_ask           INTEGER DEFAULT 1,
                allow_summarize     INTEGER DEFAULT 1,
                rate_limit          INTEGER DEFAULT 5,
                api_key             TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS bot_global_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                guild_id    TEXT,
                channel_id  TEXT,
                reason      TEXT NOT NULL,
                remind_at   INTEGER NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS mod_warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                mod_id      TEXT NOT NULL,
                reason      TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_marriages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                user1_id    TEXT NOT NULL,
                user2_id    TEXT NOT NULL,
                married_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                love_points INTEGER DEFAULT 0,
                UNIQUE(guild_id, user1_id),
                UNIQUE(guild_id, user2_id)
            );

            CREATE TABLE IF NOT EXISTS user_birthdays (
                user_id     TEXT PRIMARY KEY,
                day         INTEGER NOT NULL,
                month       INTEGER NOT NULL,
                year        INTEGER,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS birthday_settings (
                guild_id            TEXT PRIMARY KEY,
                enabled             INTEGER DEFAULT 1,
                channel_id          TEXT,
                role_id             TEXT,
                message_template    TEXT,
                gift_coins          INTEGER DEFAULT 500,
                gift_xp             INTEGER DEFAULT 200
            );

            CREATE TABLE IF NOT EXISTS fun_interactions (
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                action      TEXT NOT NULL,
                count       INTEGER DEFAULT 0,
                -- Thời điểm tương tác gần nhất: bảng này chỉ có ý nghĩa "đếm gần đây",
                -- trước đây không có cột thời gian nên không thể dọn dữ liệu cũ.
                last_used   REAL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, target_id, action)
            );

            CREATE TABLE IF NOT EXISTS verify_settings (
                guild_id            TEXT PRIMARY KEY,
                enabled             INTEGER DEFAULT 0,
                channel_id          TEXT,
                verified_role_id    TEXT,
                pending_role_id     TEXT,
                verify_text         TEXT DEFAULT 'Chào mừng đến với **{server}**! Bấm nút bên dưới để xác thực.',
                button_label        TEXT DEFAULT 'Tôi đã đọc nội quy & Xác thực',
                log_channel_id      TEXT,
                hide_channels       INTEGER DEFAULT 1,
                saved_overrides     TEXT DEFAULT '[]',
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT,
                guild_name   TEXT,
                user_id      TEXT,
                user_name    TEXT,
                avatar_url   TEXT,
                channel_name TEXT,
                event_type   TEXT NOT NULL,
                action       TEXT NOT NULL,
                details      TEXT,
                created_at   REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_activity_logs_guild ON activity_logs (guild_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_activity_logs_created ON activity_logs (created_at DESC);

            CREATE TABLE IF NOT EXISTS support_threads (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id           TEXT UNIQUE NOT NULL,
                user_id             TEXT NOT NULL,
                user_name           TEXT NOT NULL,
                user_avatar         TEXT,
                status              TEXT DEFAULT 'open',
                last_message        TEXT,
                last_sender         TEXT,
                last_escalated_at   TIMESTAMP,
                unread_admin        INTEGER DEFAULT 0,
                unread_user         INTEGER DEFAULT 0,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS support_messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id      TEXT NOT NULL,
                sender_type    TEXT NOT NULL,
                sender_id      TEXT NOT NULL,
                sender_name    TEXT NOT NULL,
                content        TEXT NOT NULL,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_support_threads_user ON support_threads (user_id);
            CREATE INDEX IF NOT EXISTS idx_support_messages_thread ON support_messages (thread_id, id);

            CREATE TABLE IF NOT EXISTS ai_activity_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source       TEXT NOT NULL,
                model        TEXT NOT NULL,
                provider     TEXT NOT NULL,
                latency_ms   INTEGER NOT NULL DEFAULT 0,
                status       TEXT NOT NULL,
                message      TEXT NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_ai_activity_logs_id ON ai_activity_logs (id DESC);
            CREATE INDEX IF NOT EXISTS idx_ai_activity_logs_source ON ai_activity_logs (source, id DESC);

            /* ─── Index đường nóng (Phase 5) ──────────────────────────────────────
               Đo bằng EXPLAIN QUERY PLAN trên data/bot.db: tất cả đều là "SCAN <table>"
               (quét toàn bảng). Máy chạy 24/7 trên Helio G85 và đang ở load average
               ~26/8 core, nên mỗi lệnh/dashboard poll quét thêm một bảng là trả giá
               thật. Không index cho economy_users / economy_settings / ai_settings /
               leveling_settings / fun_interactions vì guild_id đã là prefix của
               PRIMARY KEY -> index riêng chỉ tốn thêm thời gian ghi.
               CREATE INDEX IF NOT EXISTS: idempotent, chạy lại mỗi lần init_db mà
               không cần bảng version. */
            CREATE INDEX IF NOT EXISTS idx_custom_commands_guild ON custom_commands (guild_id, is_enabled);
            CREATE INDEX IF NOT EXISTS idx_economy_shop_guild_price ON economy_shop (guild_id, price);
            CREATE INDEX IF NOT EXISTS idx_giveaways_message ON giveaways (message_id);
            CREATE INDEX IF NOT EXISTS idx_giveaways_ended ON giveaways (ended, end_at);
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (remind_at);
            CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders (user_id, remind_at);
            CREATE INDEX IF NOT EXISTS idx_mod_warnings_target ON mod_warnings (guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_automod_warnings_target ON automod_warnings (guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON music_playlist_tracks (playlist_id, position);
            CREATE INDEX IF NOT EXISTS idx_playlists_guild ON music_playlists (guild_id);
            CREATE INDEX IF NOT EXISTS idx_ticket_buttons_panel ON ticket_buttons (panel_id);
            CREATE INDEX IF NOT EXISTS idx_rr_items_panel ON reaction_roles_items (panel_id);
            CREATE INDEX IF NOT EXISTS idx_tempvoice_guild ON tempvoice_active (guild_id);
            CREATE INDEX IF NOT EXISTS idx_saved_embeds_guild ON saved_embeds (guild_id);
            CREATE INDEX IF NOT EXISTS idx_birthdays_month_day ON user_birthdays (month, day);
            CREATE INDEX IF NOT EXISTS idx_support_threads_status ON support_threads (status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_ticket_panels_guild ON ticket_panels (guild_id);
            CREATE INDEX IF NOT EXISTS idx_rr_panels_guild ON reaction_roles_panels (guild_id);
        """)
        # Schema migration checks
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(guilds)")
        cols = [row[1] for row in cursor.fetchall()]
        if "autoroles_enabled" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN autoroles_enabled INTEGER DEFAULT 0")
        if "autoroles_user" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN autoroles_user TEXT DEFAULT '[]'")
        if "autoroles_bot" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN autoroles_bot TEXT DEFAULT '[]'")
        if "bot_admin_roles" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN bot_admin_roles TEXT DEFAULT '[]'")
        if "welcome_bg_url" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN welcome_bg_url TEXT")
        if "goodbye_bg_url" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN goodbye_bg_url TEXT")
        if "language" not in cols:
            conn.execute("ALTER TABLE guilds ADD COLUMN language TEXT DEFAULT 'vi'")
            
        cursor.execute("PRAGMA table_info(leveling_settings)")
        lvl_cols = [row[1] for row in cursor.fetchall()]
        if "stack_rewards" not in lvl_cols:
            conn.execute("ALTER TABLE leveling_settings ADD COLUMN stack_rewards INTEGER DEFAULT 0")
            
        cursor.execute("PRAGMA table_info(automod_settings)")
        am_cols = [row[1] for row in cursor.fetchall()]
        if "immune_roles" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN immune_roles TEXT DEFAULT '[]'")
        if "spam_allowed_channels" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN spam_allowed_channels TEXT DEFAULT '[]'")
        if "anti_invite_enabled" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN anti_invite_enabled INTEGER DEFAULT 0")
        if "anti_caps_enabled" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN anti_caps_enabled INTEGER DEFAULT 0")
        if "anti_mentions_enabled" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN anti_mentions_enabled INTEGER DEFAULT 0")
        if "max_mentions" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN max_mentions INTEGER DEFAULT 5")
        if "timeout_duration_minutes" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN timeout_duration_minutes INTEGER DEFAULT 5")
        if "anti_raid_enabled" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN anti_raid_enabled INTEGER DEFAULT 0")
        if "raid_join_per_window" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN raid_join_per_window INTEGER DEFAULT 5")
        if "raid_action" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN raid_action TEXT DEFAULT 'lockdown'")
        if "anti_nuke_enabled" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN anti_nuke_enabled INTEGER DEFAULT 0")
        if "nuke_actions" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN nuke_actions TEXT DEFAULT '[\"channel_delete\",\"role_delete\",\"guild_update\"]'")
        if "raid_locked" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN raid_locked INTEGER DEFAULT 0")
        if "raid_snapshot" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN raid_snapshot TEXT DEFAULT '[]'")
            
        cursor.execute("PRAGMA table_info(music_playlists)")
        pl_cols = [row[1] for row in cursor.fetchall()]
        if "creator_id" not in pl_cols:
            conn.execute("ALTER TABLE music_playlists ADD COLUMN creator_id TEXT")
        if "creator_name" not in pl_cols:
            conn.execute("ALTER TABLE music_playlists ADD COLUMN creator_name TEXT")
            
        cursor.execute("PRAGMA table_info(ai_settings)")
        ai_cols = [row[1] for row in cursor.fetchall()]
        if "api_key" not in ai_cols:
            conn.execute("ALTER TABLE ai_settings ADD COLUMN api_key TEXT DEFAULT ''")

        cursor.execute("PRAGMA table_info(fun_interactions)")
        fi_cols = [row[1] for row in cursor.fetchall()]
        if "last_used" not in fi_cols:
            conn.execute("ALTER TABLE fun_interactions ADD COLUMN last_used REAL DEFAULT 0")
            # Dữ liệu cũ không có mốc thời gian → coi như vừa dùng, để lần prune đầu
            # tiên KHÔNG xoá sạch lịch sử đếm (nhờ vậy không mất dữ liệu của user).
            conn.execute("UPDATE fun_interactions SET last_used = ? WHERE last_used IS NULL OR last_used = 0", (time.time(),))

        # ─── Support thread: một người chỉ được có MỘT thread đang mở ──────────
        # get_or_create_support_thread từng kiểu SELECT-rồi-INSERT, nên hai phiên cùng
        # mở tạo ra hai thread 'open' cho một user (chỉ thread_id là UNIQUE). Phải gom
        # bản cũ về 'resolved' TRƯỚC khi tạo index: nếu còn trùng lặp thì
        # CREATE UNIQUE INDEX thất bại im lặng và ràng buộc coi như không có.
        try:
            conn.execute("""
                UPDATE support_threads SET status = 'resolved'
                WHERE status != 'resolved'
                  AND id NOT IN (
                      SELECT MAX(id) FROM support_threads
                      WHERE status != 'resolved' GROUP BY user_id
                  )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_support_threads_one_open
                ON support_threads(user_id) WHERE status != 'resolved'
            """)
        except sqlite3.Error as exc:
            logger.warning(f"[Schema] Không tạo được idx_support_threads_one_open: {exc}")

        conn.commit()

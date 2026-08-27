"""
database.py — Shared SQLite database module.
Sync functions for Flask/dashboard, async functions for discord.py/bot.
"""
import os
import sqlite3
import json
from typing import Optional, Dict, List, Any
import aiosqlite
from cache import cache

# ─── Path setup ────────────────────────────────────────────────────────────────
# This file lives at v2/database.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "bot.db")

def init_db():
    """Create all tables if they don't exist (sync, called at startup)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
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
                log_channel_id  TEXT
            );

            CREATE TABLE IF NOT EXISTS automod_warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT,
                user_id     TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                PRIMARY KEY (guild_id, user_id, target_id, action)
            );
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
            
        conn.commit()

DEFAULT_MODULES = [
    "welcome_goodbye", "autoroles", "leveling", "utility", "info",
    "music", "tickets", "reactionroles", "automods", "logger",
    "giveaways", "economy", "tempvoice", "customcommands", "ai", "remind",
    "moderation", "fun", "birthday"
]

# ─── Blacklist (sync — Flask) ──────────────────────────────────────────────────

def get_blacklist() -> List[Dict]:
    """Return all blacklisted guilds."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_blacklist ORDER BY kicked_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO guild_blacklist (guild_id, guild_name, reason)
            VALUES (?, ?, ?)
            """,
            (guild_id, guild_name, reason),
        )
        conn.commit()


def remove_from_blacklist(guild_id: str):
    """Remove a guild from the blacklist."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM guild_blacklist WHERE guild_id = ?", (guild_id,))
        conn.commit()


def is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (sync)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        row = conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return row is not None


# ─── Blacklist (async — discord.py bot) ───────────────────────────────────────

async def async_is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (async)."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
    return row is not None


async def async_add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist (async)."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO guild_blacklist (guild_id, guild_name, reason)
            VALUES (?, ?, ?)
            """,
            (guild_id, guild_name, reason),
        )
        await conn.commit()


# ─── Sync helpers (Flask / dashboard) ─────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> Dict:
    return dict(row)

_DEFAULT_SETTINGS = {
    "welcome_channel_id":  None,
    "welcome_message":     "Xin chào {user}, chào mừng đến với **{server}**! 🎉",
    "welcome_use_embed":   1,
    "welcome_embed_color": "#57F287",
    "welcome_embed_title": "🎉 Chào mừng thành viên mới!",
    "welcome_bg_url":      "",
    "goodbye_channel_id":  None,
    "goodbye_message":     "Tạm biệt **{user_name}**, chúc bạn nhiều may mắn! 👋",
    "goodbye_use_embed":   1,
    "goodbye_embed_color": "#ED4245",
    "goodbye_embed_title": "👋 Tạm biệt!",
    "goodbye_bg_url":      "",
    "autoroles_enabled":   0,
    "autoroles_user":      "[]",
    "autoroles_bot":       "[]",
    "language":            "vi",
}

def get_guild_settings(guild_id: str) -> Dict:
    cache_key = f"settings:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    
    result = {"guild_id": guild_id, **_DEFAULT_SETTINGS}
    if row:
        result = _row_to_dict(row)
        
    cache.set(cache_key, result, ttl=300)
    return result

def upsert_guild(guild_id: str, **fields):
    """Insert or update specific guild settings columns."""
    if not fields:
        return
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (guild_id,)
        )
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE guilds SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE guild_id = ?",
            [*fields.values(), guild_id],
        )
        conn.commit()
    cache.delete(f"settings:{guild_id}")

def get_guild_modules(guild_id: str) -> Dict[str, bool]:
    cache_key = f"modules:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        rows = conn.execute(
            "SELECT module_name, enabled FROM guild_modules WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    result = {m: True for m in DEFAULT_MODULES}
    for module_name, enabled in rows:
        result[module_name] = bool(enabled)
        
    cache.set(cache_key, result, ttl=300)
    return result

def set_module(guild_id: str, module_name: str, enabled: bool):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute(
            """INSERT INTO guild_modules (guild_id, module_name, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, module_name) DO UPDATE SET enabled = excluded.enabled""",
            (guild_id, module_name, int(enabled)),
        )
        conn.commit()
    cache.delete(f"modules:{guild_id}")

set_module_enabled = set_module

def get_guild_channels(guild_id: str) -> List[Dict]:
    """Return cached text channels (type=0) for a guild."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 0 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_categories(guild_id: str) -> List[Dict]:
    """Return cached category channels (type=4) for a guild."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 4 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_voice_channels(guild_id: str) -> List[Dict]:
    """Return cached voice channels (type=2) for a guild."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 2 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_roles(guild_id: str) -> List[Dict]:
    """Return cached roles for a guild."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_roles WHERE guild_id = ? ORDER BY position DESC",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_meta(guild_id: str) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guild_meta WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def get_bot_guild_ids() -> List[str]:
    """Return list of guild IDs the bot is currently in (from cache)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        rows = conn.execute("SELECT guild_id FROM guild_meta").fetchall()
    return [r[0] for r in rows]

def get_saved_embeds(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM saved_embeds WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        ).fetchall()
    result = []
    for row in rows:
        d = _row_to_dict(row)
        try:
            d["embed_data"] = json.loads(d["embed_json"])
        except Exception:
            d["embed_data"] = {}
        result.append(d)
    return result

def save_embed(guild_id: str, name: str, embed_data: Dict) -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        cur = conn.execute(
            "INSERT INTO saved_embeds (guild_id, name, embed_json) VALUES (?, ?, ?)",
            (guild_id, name, json.dumps(embed_data, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid

def delete_embed(embed_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute(
            "DELETE FROM saved_embeds WHERE id = ? AND guild_id = ?",
            (embed_id, guild_id),
        )
        conn.commit()

def get_top_users(guild_id: str, limit: int = 10) -> list:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM user_levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?", 
            (guild_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

# ─── Ticket helpers (Sync) ────────────────────────────────────────────────────

def get_ticket_panels(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panels = conn.execute(
            "SELECT * FROM ticket_panels WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)
        ).fetchall()
        
        result = []
        for p in panels:
            p_dict = _row_to_dict(p)
            buttons = conn.execute(
                "SELECT * FROM ticket_buttons WHERE panel_id = ?", (p_dict["id"],)
            ).fetchall()
            p_dict["buttons"] = [_row_to_dict(b) for b in buttons]
            result.append(p_dict)
        return result

def get_ticket_panel(panel_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panel = conn.execute(
            "SELECT * FROM ticket_panels WHERE id = ?", (panel_id,)
        ).fetchone()
        if not panel:
            return None
        p_dict = _row_to_dict(panel)
        buttons = conn.execute(
            "SELECT * FROM ticket_buttons WHERE panel_id = ?", (panel_id,)
        ).fetchall()
        p_dict["buttons"] = [_row_to_dict(b) for b in buttons]
        return p_dict

def save_ticket_panel(guild_id: str, panel_data: dict, buttons_data: List[dict]) -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panel_id = panel_data.get("id")
        
        if panel_id:
            conn.execute(
                """UPDATE ticket_panels 
                   SET name = ?, channel_id = ?, title = ?, description = ?, color = ?, 
                       image_url = ?, thumbnail_url = ?, footer_text = ?, support_role_id = ?
                   WHERE id = ? AND guild_id = ?""",
                (
                    panel_data["name"], panel_data["channel_id"], panel_data.get("title"),
                    panel_data.get("description"), panel_data.get("color", "#5865F2"),
                    panel_data.get("image_url"), panel_data.get("thumbnail_url"),
                    panel_data.get("footer_text"), panel_data.get("support_role_id"),
                    panel_id, guild_id
                )
            )
        else:
            cursor = conn.execute(
                """INSERT INTO ticket_panels 
                   (guild_id, name, channel_id, title, description, color, image_url, thumbnail_url, footer_text, support_role_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id, panel_data["name"], panel_data["channel_id"], panel_data.get("title"),
                    panel_data.get("description"), panel_data.get("color", "#5865F2"),
                    panel_data.get("image_url"), panel_data.get("thumbnail_url"),
                    panel_data.get("footer_text"), panel_data.get("support_role_id")
                )
            )
            panel_id = cursor.lastrowid
            
        conn.execute("DELETE FROM ticket_buttons WHERE panel_id = ?", (panel_id,))
        for btn in buttons_data:
            conn.execute(
                """INSERT INTO ticket_buttons (panel_id, label, style, category_id)
                   VALUES (?, ?, ?, ?)""",
                (panel_id, btn["label"], btn.get("style", "primary"), btn["category_id"])
            )
        conn.commit()
        return panel_id

def delete_ticket_panel(panel_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM ticket_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM ticket_buttons WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_panel_message_id(panel_id: int, message_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("UPDATE ticket_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

# ─── Reaction Roles helpers (Sync) ────────────────────────────────────────────

def get_reaction_roles_panels(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panels = conn.execute(
            "SELECT * FROM reaction_roles_panels WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)
        ).fetchall()
        
        result = []
        for p in panels:
            p_dict = _row_to_dict(p)
            items = conn.execute(
                "SELECT * FROM reaction_roles_items WHERE panel_id = ?", (p_dict["id"],)
            ).fetchall()
            p_dict["items"] = [_row_to_dict(i) for i in items]
            result.append(p_dict)
        return result

def get_reaction_roles_panel(panel_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panel = conn.execute(
            "SELECT * FROM reaction_roles_panels WHERE id = ?", (panel_id,)
        ).fetchone()
        if not panel:
            return None
        p_dict = _row_to_dict(panel)
        items = conn.execute(
            "SELECT * FROM reaction_roles_items WHERE panel_id = ?", (panel_id,)
        ).fetchall()
        p_dict["items"] = [_row_to_dict(i) for i in items]
        return p_dict

def save_reaction_roles_panel(guild_id: str, panel_data: dict, items_data: List[dict]) -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        panel_id = panel_data.get("id")
        
        if panel_id:
            conn.execute(
                """UPDATE reaction_roles_panels 
                   SET name = ?, channel_id = ?, title = ?, description = ?, color = ?, 
                       image_url = ?, thumbnail_url = ?, footer_text = ?
                   WHERE id = ? AND guild_id = ?""",
                (
                    panel_data["name"], panel_data["channel_id"], panel_data.get("title"),
                    panel_data.get("description"), panel_data.get("color", "#5865F2"),
                    panel_data.get("image_url"), panel_data.get("thumbnail_url"),
                    panel_data.get("footer_text"),
                    panel_id, guild_id
                )
            )
        else:
            cursor = conn.execute(
                """INSERT INTO reaction_roles_panels 
                   (guild_id, name, channel_id, title, description, color, image_url, thumbnail_url, footer_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id, panel_data["name"], panel_data["channel_id"], panel_data.get("title"),
                    panel_data.get("description"), panel_data.get("color", "#5865F2"),
                    panel_data.get("image_url"), panel_data.get("thumbnail_url"),
                    panel_data.get("footer_text")
                )
            )
            panel_id = cursor.lastrowid
            
        conn.execute("DELETE FROM reaction_roles_items WHERE panel_id = ?", (panel_id,))
        for item in items_data:
            conn.execute(
                """INSERT INTO reaction_roles_items (panel_id, emoji, role_id)
                   VALUES (?, ?, ?)""",
                (panel_id, item["emoji"], item["role_id"])
            )
        conn.commit()
        return panel_id

def delete_reaction_roles_panel(panel_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM reaction_roles_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM reaction_roles_items WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_reaction_roles_message_id(panel_id: int, message_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("UPDATE reaction_roles_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

# ─── Async helpers (discord.py / bot) ─────────────────────────────────────────

async def async_get_guild_settings(guild_id: str) -> dict:
    cache_key = f"settings:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    result = dict(row) if row else {"guild_id": guild_id, **_DEFAULT_SETTINGS}
    await cache.aset(cache_key, result, ttl=300)
    return result

async def async_get_logger_settings(guild_id: str) -> dict:
    cache_key = f"logger_settings:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM logger_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    if row:
        result = dict(row)
    else:
        result = {
            "guild_id": guild_id,
            "log_channel_id": "",
            "log_message_edit": 1,
            "log_message_delete": 1,
            "log_member_join_leave": 1,
            "log_member_kick_ban": 1,
            "log_member_role_change": 1,
            "log_channel_change": 1,
            "log_role_change": 1,
            "log_automod": 1,
            "log_ticket": 1
        }
    await cache.aset(cache_key, result, ttl=300)
    return result

# --- Dashboard Analytics (Stats) --------------------------------------------
async def async_increment_stat(guild_id: str, event_type: str, event_label: str, amount: int = 1):
    """
    Increment a stat counter for a specific event and label.
    Aggregated by current hour (YYYY-MM-DD HH:00:00).
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    date_hour = now.strftime("%Y-%m-%d %H:00:00")
    
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT INTO guild_stats (guild_id, event_type, event_label, date_hour, count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, event_type, event_label, date_hour) 
            DO UPDATE SET count = count + ?
        """, (guild_id, event_type, event_label, date_hour, amount, amount))
        await db.commit()

def get_guild_stats(guild_id: str, days: int = 7) -> list:
    """
    Get all stats for a guild within the last N days.
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    start_date = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
    
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT event_type, event_label, date_hour, count 
            FROM guild_stats 
            WHERE guild_id = ? AND date_hour >= ?
            ORDER BY date_hour ASC
        """, (guild_id, start_date))
        return [_row_to_dict(row) for row in cur.fetchall()]

async def async_is_module_enabled(guild_id: str, module_name: str) -> bool:
    # Đọc cả dict modules (đã được cache ở get_guild_modules / set_module) để tận dụng
    # cache key "modules:{guild_id}" dùng chung giữa sync (dashboard) và async (bot).
    modules = await async_get_guild_modules(guild_id)
    return modules.get(module_name, True)  # Default: enabled


async def async_get_guild_modules(guild_id: str) -> Dict[str, bool]:
    cache_key = f"modules:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute(
            "SELECT module_name, enabled FROM guild_modules WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
    result = {m: True for m in DEFAULT_MODULES}
    for module_name, enabled in rows:
        result[module_name] = bool(enabled)
    await cache.aset(cache_key, result, ttl=300)
    return result

async def async_cache_guild(guild_id: str, name: str, icon: Optional[str], member_count: int):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute(
            """INSERT INTO guild_meta (guild_id, guild_name, guild_icon, member_count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 guild_name=excluded.guild_name,
                 guild_icon=excluded.guild_icon,
                 member_count=excluded.member_count,
                 updated_at=CURRENT_TIMESTAMP""",
            (guild_id, name, icon, member_count),
        )
        await db.commit()

async def async_remove_guild(guild_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM guild_meta WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def async_cache_channels(guild_id: str, channels: List[Dict]):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM guild_channels WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_channels (guild_id, channel_id, channel_name, channel_type) VALUES (?, ?, ?, ?)",
            [(guild_id, ch["id"], ch["name"], ch["type"]) for ch in channels],
        )
        await db.commit()

async def async_cache_roles(guild_id: str, roles: List[Dict]):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM guild_roles WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_roles (guild_id, role_id, role_name, color_hex, position) VALUES (?, ?, ?, ?, ?)",
            [(guild_id, r["id"], r["name"], r["color_hex"], r["position"]) for r in roles],
        )
        await db.commit()

# ─── Ticket async helpers ─────────────────────────────────────────────────────

async def async_get_all_ticket_panels() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ticket_panels") as cur:
            panels = await cur.fetchall()
        
        result = []
        for p in panels:
            p_dict = dict(p)
            async with db.execute(
                "SELECT * FROM ticket_buttons WHERE panel_id = ?", (p_dict["id"],)
            ) as btn_cur:
                buttons = await btn_cur.fetchall()
            p_dict["buttons"] = [dict(b) for b in buttons]
            result.append(p_dict)
        return result

async def async_get_ticket_button(button_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT b.*, p.guild_id, p.support_role_id, p.name as panel_name
               FROM ticket_buttons b
               JOIN ticket_panels p ON b.panel_id = p.id
               WHERE b.id = ?""", (button_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


# ─── Playlist Helpers ─────────────────────────────────────────────────────────

def get_playlists(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? ORDER BY id DESC", (guild_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tracks"] = get_playlist_tracks(d["id"])
            result.append(d)
        return result

def get_playlist(playlist_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def get_playlist_by_name(guild_id: str, name: str) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        cursor = conn.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        conn.commit()
        return cursor.lastrowid

def delete_playlist(playlist_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        conn.commit()

def add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        pos_row = conn.execute("SELECT MAX(position) FROM music_playlist_tracks WHERE playlist_id = ?", (playlist_id,)).fetchone()
        pos = (pos_row[0] or 0) + 1 if pos_row else 1
        
        cursor = conn.execute(
            """INSERT INTO music_playlist_tracks 
               (playlist_id, title, url, duration, webpage_url, thumbnail, uploader, position) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                track.get("title", "Unknown"),
                track.get("url", ""),
                track.get("duration", 0),
                track.get("webpage_url", ""),
                track.get("thumbnail", ""),
                track.get("uploader") or track.get("channel", "—"),
                pos
            )
        )
        conn.commit()
        return cursor.lastrowid

def delete_track_from_playlist(track_id: int):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        conn.commit()

def get_playlist_tracks(playlist_id: int) -> List[Dict]:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)).fetchall()
        return [dict(r) for r in rows]

# ─── Playlist Async Helpers ───────────────────────────────────────────────────

async def async_get_playlists(guild_id: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlists WHERE guild_id = ? ORDER BY id DESC", (guild_id,)) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tracks"] = await async_get_playlist_tracks(d["id"])
            result.append(d)
        return result

async def async_get_playlist_by_name(guild_id: str, name: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)) as cur:
            row = await cur.fetchone()
        if row:
            d = dict(row)
            d["tracks"] = await async_get_playlist_tracks(d["id"])
            return d
        return None

async def async_create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cursor = await db.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        await db.commit()
        return cursor.lastrowid

async def async_delete_playlist(playlist_id: int, guild_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        await db.commit()

async def async_add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute("SELECT MAX(position) FROM music_playlist_tracks WHERE playlist_id = ?", (playlist_id,)) as cur:
            pos_row = await cur.fetchone()
        pos = (pos_row[0] or 0) + 1 if pos_row else 1
        
        cursor = await db.execute(
            """INSERT INTO music_playlist_tracks 
               (playlist_id, title, url, duration, webpage_url, thumbnail, uploader, position) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                track.get("title", "Unknown"),
                track.get("url", ""),
                track.get("duration", 0),
                track.get("webpage_url", ""),
                track.get("thumbnail", ""),
                track.get("uploader") or track.get("channel", "—"),
                pos
            )
        )
        await db.commit()
        return cursor.lastrowid

async def async_delete_track_from_playlist(track_id: int):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        await db.commit()

async def async_get_playlist_tracks(playlist_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def async_get_reaction_role_item(message_id: str, emoji: str) -> Optional[str]:
    """Returns the role_id if the reaction matches a configured reaction role item."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute(
            """SELECT i.role_id 
               FROM reaction_roles_items i
               JOIN reaction_roles_panels p ON i.panel_id = p.id
               WHERE p.message_id = ? AND i.emoji = ?""",
            (message_id, emoji)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row[0]
    return None


# ─── Automods ──────────────────────────────────────────────────────────────────

_DEFAULT_AUTOMOD = {
    "bad_words": "[]",
    "blacklist_links": "[]",
    "whitelist_links": "[]",
    "spam_enabled": 0,
    "bad_words_enabled": 0,
    "links_enabled": 0,
    "anti_invite_enabled": 0,
    "anti_caps_enabled": 0,
    "anti_mentions_enabled": 0,
    "max_mentions": 5,
    "timeout_duration_minutes": 5,
    "notify_role_id": None,
    "log_channel_id": None,
    "immune_roles": "[]",
    "spam_allowed_channels": "[]"
}

def get_logger_settings(guild_id: str) -> dict:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT * FROM logger_settings WHERE guild_id = ?
        """, (guild_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "log_channel_id": "",
            "log_message_edit": 1,
            "log_message_delete": 1,
            "log_member_join_leave": 1,
            "log_member_kick_ban": 1,
            "log_member_role_change": 1,
            "log_channel_change": 1,
            "log_role_change": 1,
            "log_automod": 1,
            "log_ticket": 1
        }

def set_logger_settings(guild_id: str, settings: dict):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO logger_settings (
                guild_id, log_channel_id, log_message_edit, log_message_delete,
                log_member_join_leave, log_member_kick_ban, log_member_role_change,
                log_channel_change, log_role_change, log_automod, log_ticket
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                log_channel_id=excluded.log_channel_id,
                log_message_edit=excluded.log_message_edit,
                log_message_delete=excluded.log_message_delete,
                log_member_join_leave=excluded.log_member_join_leave,
                log_member_kick_ban=excluded.log_member_kick_ban,
                log_member_role_change=excluded.log_member_role_change,
                log_channel_change=excluded.log_channel_change,
                log_role_change=excluded.log_role_change,
                log_automod=excluded.log_automod,
                log_ticket=excluded.log_ticket
        """, (
            guild_id,
            settings.get("log_channel_id", ""),
            settings.get("log_message_edit", 1),
            settings.get("log_message_delete", 1),
            settings.get("log_member_join_leave", 1),
            settings.get("log_member_kick_ban", 1),
            settings.get("log_member_role_change", 1),
            settings.get("log_channel_change", 1),
            settings.get("log_role_change", 1),
            settings.get("log_automod", 1),
            settings.get("log_ticket", 1)
        ))
        conn.commit()
    cache.delete(f"logger_settings:{guild_id}")

def get_automod_settings(guild_id: str) -> dict:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        if row:
            res = _row_to_dict(row)
            res["bad_words"] = json.loads(res.get("bad_words") or "[]")
            res["blacklist_links"] = json.loads(res.get("blacklist_links") or "[]")
            res["whitelist_links"] = json.loads(res.get("whitelist_links") or "[]")
            res["immune_roles"] = json.loads(res.get("immune_roles") or "[]")
            res["spam_allowed_channels"] = json.loads(res.get("spam_allowed_channels") or "[]")
            return res
        return dict(_DEFAULT_AUTOMOD)

def upsert_automod_settings(guild_id: str, **kwargs):
    s = get_automod_settings(guild_id)
    s.update(kwargs)
    bad_words = json.dumps(s.get("bad_words", [])) if isinstance(s.get("bad_words"), list) else s.get("bad_words", "[]")
    blacklist_links = json.dumps(s.get("blacklist_links", [])) if isinstance(s.get("blacklist_links"), list) else s.get("blacklist_links", "[]")
    whitelist_links = json.dumps(s.get("whitelist_links", [])) if isinstance(s.get("whitelist_links"), list) else s.get("whitelist_links", "[]")
    immune_roles = json.dumps(s.get("immune_roles", [])) if isinstance(s.get("immune_roles"), list) else s.get("immune_roles", "[]")
    spam_allowed_channels = json.dumps(s.get("spam_allowed_channels", [])) if isinstance(s.get("spam_allowed_channels"), list) else s.get("spam_allowed_channels", "[]")
    
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO automod_settings (
                guild_id, bad_words, blacklist_links, whitelist_links, 
                spam_enabled, bad_words_enabled, links_enabled,
                anti_invite_enabled, anti_caps_enabled, anti_mentions_enabled,
                max_mentions, timeout_duration_minutes,
                notify_role_id, log_channel_id,
                immune_roles, spam_allowed_channels
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                bad_words=excluded.bad_words,
                blacklist_links=excluded.blacklist_links,
                whitelist_links=excluded.whitelist_links,
                spam_enabled=excluded.spam_enabled,
                bad_words_enabled=excluded.bad_words_enabled,
                links_enabled=excluded.links_enabled,
                anti_invite_enabled=excluded.anti_invite_enabled,
                anti_caps_enabled=excluded.anti_caps_enabled,
                anti_mentions_enabled=excluded.anti_mentions_enabled,
                max_mentions=excluded.max_mentions,
                timeout_duration_minutes=excluded.timeout_duration_minutes,
                notify_role_id=excluded.notify_role_id,
                log_channel_id=excluded.log_channel_id,
                immune_roles=excluded.immune_roles,
                spam_allowed_channels=excluded.spam_allowed_channels
        """, (
            guild_id, bad_words, blacklist_links, whitelist_links,
            int(s.get("spam_enabled", 0)), int(s.get("bad_words_enabled", 0)), int(s.get("links_enabled", 0)),
            int(s.get("anti_invite_enabled", 0)), int(s.get("anti_caps_enabled", 0)), int(s.get("anti_mentions_enabled", 0)),
            int(s.get("max_mentions", 5)), int(s.get("timeout_duration_minutes", 5)),
            s.get("notify_role_id"), s.get("log_channel_id"),
            immune_roles, spam_allowed_channels
        ))
        conn.commit()

async def async_get_automod_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM automod_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                res = dict(row)
                res["bad_words"] = json.loads(res.get("bad_words") or "[]")
                res["blacklist_links"] = json.loads(res.get("blacklist_links") or "[]")
                res["whitelist_links"] = json.loads(res.get("whitelist_links") or "[]")
                res["immune_roles"] = json.loads(res.get("immune_roles") or "[]")
                res["spam_allowed_channels"] = json.loads(res.get("spam_allowed_channels") or "[]")
                return res
            return dict(_DEFAULT_AUTOMOD)

async def async_add_automod_warning(guild_id: str, user_id: str) -> int:
    """Returns the total number of warnings the user has in the last 24 hours (including this one)."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        # Delete warnings older than 24h for all users in this guild (cleanup)
        await db.execute("DELETE FROM automod_warnings WHERE guild_id = ? AND created_at <= datetime('now', '-1 day')", (guild_id,))
        
        # Add new warning
        await db.execute("INSERT INTO automod_warnings (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
        
        # Get count
        async with db.execute("SELECT COUNT(*) FROM automod_warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 1
            
        await db.commit()
        return count

async def async_clear_automod_warnings(guild_id: str, user_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM automod_warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()

# ─── Leveling (Sync & Async) ───────────────────────────────────────────────────

_DEFAULT_LEVELING = {
    "message_xp_min": 15,
    "message_xp_max": 25,
    "voice_xp": 10,
    "announce_channel_id": "current",
    "announce_message": "🎉 Chúc mừng {user} đã đạt cấp **{level}**!",
    "stack_rewards": 0
}

def get_leveling_settings(guild_id: str) -> dict:
    cache_key = f"leveling:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            result = dict(row)
        else:
            result = dict(_DEFAULT_LEVELING)
            
    cache.set(cache_key, result, ttl=300)
    return result

def set_leveling_settings(guild_id: str, settings: dict):
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO leveling_settings (guild_id, message_xp_min, message_xp_max, voice_xp, announce_channel_id, announce_message, stack_rewards)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                message_xp_min=excluded.message_xp_min,
                message_xp_max=excluded.message_xp_max,
                voice_xp=excluded.voice_xp,
                announce_channel_id=excluded.announce_channel_id,
                announce_message=excluded.announce_message,
                stack_rewards=excluded.stack_rewards
        """, (
            guild_id,
            int(settings.get("message_xp_min", 15)),
            int(settings.get("message_xp_max", 25)),
            int(settings.get("voice_xp", 10)),
            settings.get("announce_channel_id"),
            settings.get("announce_message", _DEFAULT_LEVELING["announce_message"]),
            int(settings.get("stack_rewards", 0))
        ))
        conn.commit()
    cache.delete(f"leveling:{guild_id}")

def get_level_roles(guild_id: str) -> dict:
    """Return dict mapping level (int) to role_id (str)"""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        rows = conn.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)).fetchall()
        return {row[0]: row[1] for row in rows}

def set_level_roles(guild_id: str, roles: dict):
    """roles is a dict of {level: role_id}"""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM level_roles WHERE guild_id = ?", (guild_id,))
        for level_str, role_id in roles.items():
            if not role_id:
                continue
            try:
                level = int(level_str)
                conn.execute("INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)", (guild_id, level, role_id))
            except ValueError:
                pass
        conn.commit()

async def async_get_leveling_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return dict(_DEFAULT_LEVELING)

async def async_get_level_roles(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def async_get_user_level(guild_id: str, user_id: str) -> dict:
    cache_key = f"level:{guild_id}:{user_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
            else:
                result = {"guild_id": guild_id, "user_id": user_id, "xp": 0, "level": 0, "last_message_at": 0, "last_voice_xp_at": 0}
                
    await cache.aset(cache_key, result, ttl=120) # 2 mins TTL
    return result


async_get_user_xp = async_get_user_level

async def async_update_user_xp(guild_id: str, user_id: str, xp: int, level: int, last_message_at: float = None, last_voice_xp_at: float = None):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        query = "INSERT INTO user_levels (guild_id, user_id, xp, level"
        values = [guild_id, user_id, xp, level]
        updates = ["xp = excluded.xp", "level = excluded.level"]
        
        if last_message_at is not None:
            query += ", last_message_at"
            values.append(last_message_at)
            updates.append("last_message_at = excluded.last_message_at")
            
        if last_voice_xp_at is not None:
            query += ", last_voice_xp_at"
            values.append(last_voice_xp_at)
            updates.append("last_voice_xp_at = excluded.last_voice_xp_at")
            
        query += ") VALUES (" + ", ".join(["?"] * len(values)) + ") ON CONFLICT(guild_id, user_id) DO UPDATE SET " + ", ".join(updates)
        
        await db.execute(query, tuple(values))
        await db.commit()
    await cache.adelete(f"level:{guild_id}:{user_id}")

async def async_reset_user_xp(guild_id: str, user_id: str):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()
    await cache.adelete(f"level:{guild_id}:{user_id}")

async def async_get_top_users(guild_id: str, limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, xp, level FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def async_get_user_rank(guild_id: str, user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        # Get rank based on XP
        async with db.execute("SELECT COUNT(*) + 1 FROM user_levels WHERE guild_id = ? AND xp > (SELECT xp FROM user_levels WHERE guild_id = ? AND user_id = ?)", (guild_id, guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return 1

# ─── Giveaway Functions ────────────────────────────────────────────────────────
async def async_create_giveaway(guild_id: str, channel_id: str, message_id: str, host_id: str, prize: str, winners_count: int, end_at: int, req_role_id: str = None, req_account_age_days: int = 0):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days))
        await db.commit()

async def async_get_giveaway(message_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def async_update_giveaway(message_id: str, participants_json: str = None, ended: int = None):
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        if participants_json is not None and ended is not None:
            await db.execute("UPDATE giveaways SET participants_json = ?, ended = ? WHERE message_id = ?", (participants_json, ended, message_id))
        elif participants_json is not None:
            await db.execute("UPDATE giveaways SET participants_json = ? WHERE message_id = ?", (participants_json, message_id))
        elif ended is not None:
            await db.execute("UPDATE giveaways SET ended = ? WHERE message_id = ?", (ended, message_id))
        await db.commit()

async def async_get_active_giveaways() -> list:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE ended = 0") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# ─── i18n Language Helpers ─────────────────────────────────────────────────────

def set_guild_language(guild_id: str, language: str) -> None:
    """
    Set guild language — sync version for Flask Dashboard.
    Delegates to upsert_guild and auto-invalidates the settings cache.
    """
    upsert_guild(guild_id, language=language)


async def async_set_guild_language(guild_id: str, language: str) -> None:
    """
    Set guild language — async version for Discord Bot.
    Uses asyncio.to_thread so it never blocks the event loop.
    """
    import asyncio
    await asyncio.to_thread(upsert_guild, guild_id, language=language)
    # Invalidate Redis/memory cache so bot picks up the change immediately
    await cache.adelete(f"settings:{guild_id}")


# ═════════════════════════════════════════════════════════════════════════════════
# ─── MODULE: ECONOMY & SERVER SHOP ─────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════

def get_economy_settings(guild_id: str) -> dict:
    """Sync — Get economy settings for dashboard."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {"guild_id": guild_id, "daily_amount": 100, "streak_bonus": 20, "starting_balance": 50, "currency_symbol": "🪙", "currency_name": "Coins"}
        return _row_to_dict(row)


def update_economy_settings(guild_id: str, daily_amount: int, streak_bonus: int, starting_balance: int, currency_symbol: str = "🪙", currency_name: str = "Coins") -> None:
    """Sync — Update economy settings."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO economy_settings (guild_id, daily_amount, streak_bonus, starting_balance, currency_symbol, currency_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                daily_amount=excluded.daily_amount,
                streak_bonus=excluded.streak_bonus,
                starting_balance=excluded.starting_balance,
                currency_symbol=excluded.currency_symbol,
                currency_name=excluded.currency_name
        """, (guild_id, daily_amount, streak_bonus, starting_balance, currency_symbol, currency_name))
        conn.commit()


def get_economy_shop(guild_id: str) -> list:
    """Sync — List all shop items in a server."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM economy_shop WHERE guild_id = ? ORDER BY price ASC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]


def add_economy_shop_item(guild_id: str, role_id: str, name: str, price: int, stock: int = -1) -> int:
    """Sync — Add new role to server shop."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        cursor = conn.execute("""
            INSERT INTO economy_shop (guild_id, role_id, name, price, stock)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, role_id, name, price, stock))
        conn.commit()
        return cursor.lastrowid


def delete_economy_shop_item(item_id: int, guild_id: str) -> None:
    """Sync — Delete a shop item."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM economy_shop WHERE id = ? AND guild_id = ?", (item_id, guild_id))
        conn.commit()


def get_top_economy_users(guild_id: str, limit: int = 10) -> list:
    """Sync — Get top richest members for leaderboard."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT user_id, wallet, bank, (wallet + bank) as total, daily_streak
            FROM economy_users
            WHERE guild_id = ?
            ORDER BY total DESC LIMIT ?
        """, (guild_id, limit)).fetchall()
        return [_row_to_dict(r) for r in rows]


def update_user_balance(guild_id: str, user_id: str, wallet: int, bank: int) -> None:
    """Sync — Admin update user balance on web."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO economy_users (guild_id, user_id, wallet, bank)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                wallet=excluded.wallet,
                bank=excluded.bank
        """, (guild_id, user_id, wallet, bank))
        conn.commit()


# Async Economy (Bot)
async def async_get_economy_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"guild_id": guild_id, "daily_amount": 100, "streak_bonus": 20, "starting_balance": 50, "currency_symbol": "🪙", "currency_name": "Coins"}
            return dict(row)


async def async_get_economy_user(guild_id: str, user_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if not row:
                # Lấy starting balance
                settings = await async_get_economy_settings(guild_id)
                start_bal = settings.get("starting_balance", 50)
                await db.execute("""
                    INSERT OR IGNORE INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
                    VALUES (?, ?, ?, 0, 0, 0)
                """, (guild_id, user_id, start_bal))
                await db.commit()
                return {"guild_id": guild_id, "user_id": user_id, "wallet": start_bal, "bank": 0, "daily_streak": 0, "last_daily_at": 0}
            return dict(row)


async def async_claim_daily(guild_id: str, user_id: str, reward: int, streak: int) -> dict:
    import time
    now = time.time()
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, ?, 0, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                wallet = wallet + ?,
                daily_streak = ?,
                last_daily_at = ?
        """, (guild_id, user_id, reward, streak, now, reward, streak, now))
        await db.commit()
    return await async_get_economy_user(guild_id, user_id)


async def async_modify_wallet(guild_id: str, user_id: str, delta: int) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        # Ensure user exists
        await async_get_economy_user(guild_id, user_id)
        await db.execute("""
            UPDATE economy_users
            SET wallet = MAX(0, wallet + ?)
            WHERE guild_id = ? AND user_id = ?
        """, (delta, guild_id, user_id))
        await db.commit()
    return await async_get_economy_user(guild_id, user_id)


async def async_transfer_money(guild_id: str, from_user_id: str, to_user_id: str, amount: int) -> bool:
    if amount <= 0:
        return False
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT wallet FROM economy_users WHERE guild_id = ? AND user_id = ?", (guild_id, from_user_id)) as cur:
            sender = await cur.fetchone()
            if not sender or sender["wallet"] < amount:
                return False
        
        await db.execute("UPDATE economy_users SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, from_user_id))
        # Ensure receiver exists
        await async_get_economy_user(guild_id, to_user_id)
        await db.execute("UPDATE economy_users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, to_user_id))
        await db.commit()
        return True


async def async_get_economy_shop(guild_id: str) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_shop WHERE guild_id = ? ORDER BY price ASC", (guild_id,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def async_deposit_money(guild_id: str, user_id: str, amount_raw: str | int) -> tuple[bool, int, dict, str]:
    """
    Deposit money from wallet into bank.
    Returns: (success: bool, amount_deposited: int, updated_user: dict, error_code: str)
    error_codes: 'invalid_amount', 'wallet_empty', 'not_enough_wallet', ''
    """
    user = await async_get_economy_user(guild_id, user_id)
    wallet = user.get("wallet", 0)
    
    if isinstance(amount_raw, str) and amount_raw.lower() in ("all", "max"):
        if wallet <= 0:
            return False, 0, user, "wallet_empty"
        amount = wallet
    else:
        try:
            amount = int(amount_raw)
        except (ValueError, TypeError):
            return False, 0, user, "invalid_amount"
        if amount <= 0:
            return False, 0, user, "invalid_amount"
        if wallet < amount:
            return False, 0, user, "not_enough_wallet"
            
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            UPDATE economy_users
            SET wallet = wallet - ?, bank = bank + ?
            WHERE guild_id = ? AND user_id = ?
        """, (amount, amount, guild_id, user_id))
        await db.commit()
        
    updated = await async_get_economy_user(guild_id, user_id)
    return True, amount, updated, ""


async def async_withdraw_money(guild_id: str, user_id: str, amount_raw: str | int) -> tuple[bool, int, dict, str]:
    """
    Withdraw money from bank into wallet.
    Returns: (success: bool, amount_withdrawn: int, updated_user: dict, error_code: str)
    error_codes: 'invalid_amount', 'bank_empty', 'not_enough_bank', ''
    """
    user = await async_get_economy_user(guild_id, user_id)
    bank = user.get("bank", 0)
    
    if isinstance(amount_raw, str) and amount_raw.lower() in ("all", "max"):
        if bank <= 0:
            return False, 0, user, "bank_empty"
        amount = bank
    else:
        try:
            amount = int(amount_raw)
        except (ValueError, TypeError):
            return False, 0, user, "invalid_amount"
        if amount <= 0:
            return False, 0, user, "invalid_amount"
        if bank < amount:
            return False, 0, user, "not_enough_bank"
            
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            UPDATE economy_users
            SET bank = bank - ?, wallet = wallet + ?
            WHERE guild_id = ? AND user_id = ?
        """, (amount, amount, guild_id, user_id))
        await db.commit()
        
    updated = await async_get_economy_user(guild_id, user_id)
    return True, amount, updated, ""


async def async_buy_shop_item(guild_id: str, user_id: str, item_id: int) -> tuple[bool, str, str, int]:
    """Return (success, role_id, error_message_or_item_name, item_price). Paid with Bank balance."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_shop WHERE id = ? AND guild_id = ?", (item_id, guild_id)) as cur:
            item = await cur.fetchone()
            if not item:
                return False, "", "item_not_found", 0
            if item["stock"] == 0:
                return False, "", "out_of_stock", item["price"]
            
            user = await async_get_economy_user(guild_id, user_id)
            if user.get("bank", 0) < item["price"]:
                return False, "", "not_enough_bank", item["price"]
            
            # Trừ tiền từ BANK và trừ stock nếu có giới hạn
            await db.execute("UPDATE economy_users SET bank = bank - ? WHERE guild_id = ? AND user_id = ?", (item["price"], guild_id, user_id))
            if item["stock"] > 0:
                await db.execute("UPDATE economy_shop SET stock = stock - 1 WHERE id = ?", (item_id,))
            await db.commit()
            return True, item["role_id"], item["name"], item["price"]


async def async_get_top_economy(guild_id: str, limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, wallet, bank, (wallet + bank) as total, daily_streak
            FROM economy_users
            WHERE guild_id = ?
            ORDER BY total DESC LIMIT ?
        """, (guild_id, limit)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════════
# ─── MODULE: TEMPORARY VOICE CHANNELS ──────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════

def get_tempvoice_settings(guild_id: str) -> dict:
    """Sync — Get tempvoice settings."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {"guild_id": guild_id, "enabled": 0, "hub_channel_id": "", "category_id": "", "name_template": "🔊 Phòng của {user}", "default_limit": 0}
        return _row_to_dict(row)


def update_tempvoice_settings(guild_id: str, enabled: int, hub_channel_id: str, category_id: str, name_template: str = "🔊 Phòng của {user}", default_limit: int = 0) -> None:
    """Sync — Update tempvoice settings."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO tempvoice_settings (guild_id, enabled, hub_channel_id, category_id, name_template, default_limit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled=excluded.enabled,
                hub_channel_id=excluded.hub_channel_id,
                category_id=excluded.category_id,
                name_template=excluded.name_template,
                default_limit=excluded.default_limit
        """, (guild_id, enabled, hub_channel_id, category_id, name_template, default_limit))
        conn.commit()


def get_active_temp_channels(guild_id: str) -> list:
    """Sync — List currently active temporary voice channels."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tempvoice_active WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]


async def async_get_tempvoice_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tempvoice_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {"guild_id": guild_id, "enabled": 0, "hub_channel_id": "", "category_id": "", "name_template": "🔊 Phòng của {user}", "default_limit": 0}
            return dict(row)


async def async_add_active_temp_channel(channel_id: str, guild_id: str, owner_id: str) -> None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT OR REPLACE INTO tempvoice_active (channel_id, guild_id, owner_id, is_locked)
            VALUES (?, ?, ?, 0)
        """, (channel_id, guild_id, owner_id))
        await db.commit()


async def async_remove_active_temp_channel(channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM tempvoice_active WHERE channel_id = ?", (channel_id,))
        await db.commit()


async def async_get_active_temp_channel(channel_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tempvoice_active WHERE channel_id = ?", (channel_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_update_temp_channel_lock(channel_id: str, is_locked: int) -> None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("UPDATE tempvoice_active SET is_locked = ? WHERE channel_id = ?", (is_locked, channel_id))
        await db.commit()


# ═════════════════════════════════════════════════════════════════════════════════
# ─── MODULE: CUSTOM COMMANDS & AUTO-RESPONDERS ─────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════

def get_custom_commands(guild_id: str) -> list:
    """Sync — List all custom commands for dashboard."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM custom_commands WHERE guild_id = ? ORDER BY id DESC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_custom_command(cmd_id: int, guild_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id)).fetchone()
        return _row_to_dict(row) if row else None


def add_custom_command(guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, creator_id: str = "") -> int:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        cursor = conn.execute("""
            INSERT INTO custom_commands (guild_id, trigger, match_type, response_text, embed_json, is_enabled, uses_count, creator_id)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?)
        """, (guild_id, trigger.strip().lower(), match_type, response_text, embed_json, creator_id))
        conn.commit()
        return cursor.lastrowid


def update_custom_command(cmd_id: int, guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, is_enabled: int = 1) -> None:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            UPDATE custom_commands
            SET trigger = ?, match_type = ?, response_text = ?, embed_json = ?, is_enabled = ?
            WHERE id = ? AND guild_id = ?
        """, (trigger.strip().lower(), match_type, response_text, embed_json, is_enabled, cmd_id, guild_id))
        conn.commit()


def delete_custom_command(cmd_id: int, guild_id: str) -> None:
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("DELETE FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id))
        conn.commit()


async def async_get_custom_commands(guild_id: str) -> list:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_commands WHERE guild_id = ? AND is_enabled = 1", (guild_id,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def async_find_custom_command(guild_id: str, message_content: str) -> dict | None:
    """Find matching custom command (exact, contains, startswith)."""
    text = message_content.strip().lower()
    commands = await async_get_custom_commands(guild_id)
    for cmd in commands:
        trigger = cmd["trigger"].lower()
        mtype = cmd.get("match_type", "exact")
        if mtype == "exact" and text == trigger:
            return cmd
        elif mtype == "startswith" and text.startswith(trigger):
            return cmd
        elif mtype == "contains" and trigger in text:
            return cmd
    return None


async def async_add_custom_command(guild_id: str, trigger: str, match_type: str, response_text: str, embed_json: str = None, creator_id: str = "") -> int:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cursor = await db.execute("""
            INSERT INTO custom_commands (guild_id, trigger, match_type, response_text, embed_json, is_enabled, uses_count, creator_id)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?)
        """, (guild_id, trigger.strip().lower(), match_type, response_text, embed_json, creator_id))
        await db.commit()
        return cursor.lastrowid


async def async_delete_custom_command(cmd_id: int, guild_id: str) -> None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM custom_commands WHERE id = ? AND guild_id = ?", (cmd_id, guild_id))
        await db.commit()


async def async_increment_custom_command_usage(cmd_id: int) -> None:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("UPDATE custom_commands SET uses_count = uses_count + 1 WHERE id = ?", (cmd_id,))
        await db.commit()


# ═════════════════════════════════════════════════════════════════════════════════
# ─── MODULE: AI CHAT & SMART ASSISTANT ─────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════

def get_ai_settings(guild_id: str) -> dict:
    """Sync — Get AI settings for dashboard."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {
                "guild_id": guild_id, "enabled": 0, "ai_channel_id": "",
                "personality_preset": "friendly", "custom_prompt": "",
                "allow_ask": 1, "allow_summarize": 1, "rate_limit": 5,
                "api_key": ""
            }
        return _row_to_dict(row)


def update_ai_settings(guild_id: str, enabled: int, ai_channel_id: str, personality_preset: str = "friendly", custom_prompt: str = "", allow_ask: int = 1, allow_summarize: int = 1, rate_limit: int = 5, api_key: str = "") -> None:
    """Sync — Update AI settings."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO ai_settings (guild_id, enabled, ai_channel_id, personality_preset, custom_prompt, allow_ask, allow_summarize, rate_limit, api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled=excluded.enabled,
                ai_channel_id=excluded.ai_channel_id,
                personality_preset=excluded.personality_preset,
                custom_prompt=excluded.custom_prompt,
                allow_ask=excluded.allow_ask,
                allow_summarize=excluded.allow_summarize,
                rate_limit=excluded.rate_limit,
                api_key=excluded.api_key
        """, (guild_id, enabled, ai_channel_id, personality_preset, custom_prompt, allow_ask, allow_summarize, rate_limit, api_key))
        conn.commit()


async def async_get_ai_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {
                    "guild_id": guild_id, "enabled": 0, "ai_channel_id": "",
                    "personality_preset": "friendly", "custom_prompt": "",
                    "allow_ask": 1, "allow_summarize": 1, "rate_limit": 5,
                    "api_key": ""
                }
            return dict(row)


# ═════════════════════════════════════════════════════════════════════════════════
# ─── MODULE: BOT GLOBAL SETTINGS (ADMIN / BOT OWNER) ───────────────────────────
# ═════════════════════════════════════════════════════════════════════════════════

def get_global_setting(key: str, default: str = "") -> str:
    """Sync — Get a global bot configuration setting."""
    cache_key = f"global_setting:{key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        row = conn.execute("SELECT value FROM bot_global_settings WHERE key = ?", (key,)).fetchone()
        val = str(row[0]) if row and row[0] is not None else default
        cache.set(cache_key, val, ttl=300)
        return val


def set_global_setting(key: str, value: str) -> None:
    """Sync — Save a global bot configuration setting."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("""
            INSERT INTO bot_global_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
    cache.delete(f"global_setting:{key}")


async def async_get_global_setting(key: str, default: str = "") -> str:
    """Async — Get a global bot configuration setting."""
    cache_key = f"global_setting:{key}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute("SELECT value FROM bot_global_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            val = str(row[0]) if row and row[0] is not None else default
            await cache.aset(cache_key, val, ttl=300)
            return val


# ─── Database Maintenance & WAL Checkpoint ─────────────────────────────────────

def wal_checkpoint() -> str:
    """Sync — Checkpoint and truncate WAL file to keep database file size minimal."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        res = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        conn.commit()
        return f"WAL Checkpoint TRUNCATE: {res}"


async def async_wal_checkpoint() -> str:
    """Async — Checkpoint and truncate WAL file."""
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute("PRAGMA wal_checkpoint(TRUNCATE);") as cur:
            res = await cur.fetchone()
            return f"WAL Checkpoint TRUNCATE: {res}"


# ─── Reminders System DB Functions ─────────────────────────────────────────────

async def async_add_reminder(user_id: str, guild_id: str, channel_id: str, reason: str, remind_at: int) -> int:
    """Add a new reminder for user."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute("""
            INSERT INTO reminders (user_id, guild_id, channel_id, reason, remind_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, channel_id, reason, remind_at))
        await db.commit()
        return cur.lastrowid


async def async_get_due_reminders(now_ts: int) -> list:
    """Fetch all reminders that are due to be triggered (remind_at <= now_ts)."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM reminders WHERE remind_at <= ? ORDER BY remind_at ASC LIMIT 50", (now_ts,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def async_delete_reminder(reminder_id: int):
    """Delete a reminder by ID after triggering or user cancellation."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()


async def async_get_user_reminders(user_id: str, guild_id: str = None) -> list:
    """Fetch active upcoming reminders for a user."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        if guild_id:
            query = "SELECT * FROM reminders WHERE user_id = ? AND guild_id = ? ORDER BY remind_at ASC LIMIT 20"
            params = (user_id, guild_id)
        else:
            query = "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at ASC LIMIT 20"
            params = (user_id,)
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]



# ─── Moderation Warnings DB Functions ──────────────────────────────────────────

async def async_add_mod_warning(guild_id: str, user_id: str, mod_id: str, reason: str) -> int:
    """Add a moderation warning. Returns the new warning ID."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute("""
            INSERT INTO mod_warnings (guild_id, user_id, mod_id, reason)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, reason))
        await db.commit()
        return cur.lastrowid


async def async_get_mod_warnings(guild_id: str, user_id: str) -> list:
    """Get all active warnings for a user in a guild."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mod_warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def async_count_mod_warnings(guild_id: str, user_id: str) -> int:
    """Count total warnings for a user."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM mod_warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def async_delete_mod_warning(warning_id: int, guild_id: str) -> bool:
    """Delete a warning by ID. Returns True if deleted."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute(
            "DELETE FROM mod_warnings WHERE id = ? AND guild_id = ?",
            (warning_id, guild_id),
        )
        await db.commit()
        return cur.rowcount > 0


def get_mod_warnings_count_sync(guild_id: str) -> int:
    """Sync — count total warnings in guild (for dashboard)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM mod_warnings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row[0] if row else 0


# ─── Marriage / Fun DB Functions ───────────────────────────────────────────────

async def async_get_marriage(guild_id: str, user_id: str) -> dict | None:
    """Get the marriage record for a user (either as user1 or user2)."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_marriages WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (guild_id, user_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_create_marriage(guild_id: str, user1_id: str, user2_id: str) -> int:
    """Create a marriage between two users. Returns the new ID."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute("""
            INSERT INTO user_marriages (guild_id, user1_id, user2_id)
            VALUES (?, ?, ?)
        """, (guild_id, user1_id, user2_id))
        await db.commit()
        return cur.lastrowid


async def async_delete_marriage(guild_id: str, user_id: str) -> bool:
    """Delete a marriage involving user_id."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute(
            "DELETE FROM user_marriages WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (guild_id, user_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def async_add_love_points(guild_id: str, user_id: str, points: int = 1):
    """Increment love_points for a marriage."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute(
            "UPDATE user_marriages SET love_points = love_points + ? WHERE guild_id = ? AND (user1_id = ? OR user2_id = ?)",
            (points, guild_id, user_id, user_id),
        )
        await db.commit()


def get_marriages_count_sync(guild_id: str) -> int:
    """Sync — count marriages in guild (for dashboard)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_marriages WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row[0] if row else 0


async def async_increment_fun_interaction(guild_id: str, user_id: str, target_id: str, action: str) -> int:
    """Increment interaction count between user and target for a given action. Returns new count."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT INTO fun_interactions (guild_id, user_id, target_id, action, count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(guild_id, user_id, target_id, action)
            DO UPDATE SET count = count + 1
        """, (guild_id, user_id, target_id, action))
        await db.commit()
        async with db.execute("""
            SELECT count FROM fun_interactions
            WHERE guild_id = ? AND user_id = ? AND target_id = ? AND action = ?
        """, (guild_id, user_id, target_id, action)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 1


async def async_get_fun_interaction_count(guild_id: str, user_id: str, target_id: str, action: str) -> int:
    """Get interaction count between user and target for a given action."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        async with db.execute("""
            SELECT count FROM fun_interactions
            WHERE guild_id = ? AND user_id = ? AND target_id = ? AND action = ?
        """, (guild_id, user_id, target_id, action)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ─── Birthday DB Functions ─────────────────────────────────────────────────────

async def async_set_birthday(user_id: str, day: int, month: int, year: int | None = None):
    """Set or update a user's birthday."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("""
            INSERT INTO user_birthdays (user_id, day, month, year, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET day=excluded.day, month=excluded.month, year=excluded.year, updated_at=CURRENT_TIMESTAMP
        """, (user_id, day, month, year))
        await db.commit()


async def async_get_birthday(user_id: str) -> dict | None:
    """Get a user's birthday."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_birthdays WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def async_remove_birthday(user_id: str) -> bool:
    """Remove a user's birthday."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        cur = await db.execute("DELETE FROM user_birthdays WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def async_get_birthdays_today(day: int, month: int) -> list:
    """Get all users whose birthday is today."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_birthdays WHERE day = ? AND month = ?", (day, month)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def async_get_upcoming_birthdays(current_month: int, current_day: int, limit: int = 10) -> list:
    """Get upcoming birthdays sorted by nearest date."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        # Sort by how far the birthday is from today (wrapping around year)
        async with db.execute("""
            SELECT *, 
                CASE 
                    WHEN (month > ? OR (month = ? AND day >= ?)) THEN (month - ?) * 31 + (day - ?)
                    ELSE (month + 12 - ?) * 31 + (day - ?)
                END AS distance
            FROM user_birthdays
            ORDER BY distance ASC
            LIMIT ?
        """, (current_month, current_month, current_day, current_month, current_day, current_month, current_day, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def async_get_birthday_settings(guild_id: str) -> dict:
    """Get birthday settings for a guild."""
    defaults = {
        "guild_id": guild_id, "enabled": 1, "channel_id": None,
        "role_id": None, "message_template": None,
        "gift_coins": 500, "gift_xp": 200,
    }
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM birthday_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return defaults


async def async_upsert_birthday_settings(guild_id: str, **fields):
    """Insert or update birthday settings."""
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
        await db.execute("INSERT OR IGNORE INTO birthday_settings (guild_id) VALUES (?)", (guild_id,))
        if fields:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            await db.execute(
                f"UPDATE birthday_settings SET {set_clause} WHERE guild_id = ?",
                [*fields.values(), guild_id],
            )
        await db.commit()


def get_birthday_settings_sync(guild_id: str) -> dict:
    """Sync — get birthday settings (for dashboard)."""
    defaults = {
        "guild_id": guild_id, "enabled": 1, "channel_id": None,
        "role_id": None, "message_template": None,
        "gift_coins": 500, "gift_xp": 200,
    }
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM birthday_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            return _row_to_dict(row)
    return defaults


def upsert_birthday_settings_sync(guild_id: str, **fields):
    """Sync — upsert birthday settings (for dashboard)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("INSERT OR IGNORE INTO birthday_settings (guild_id) VALUES (?)", (guild_id,))
        if fields:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE birthday_settings SET {set_clause} WHERE guild_id = ?",
                [*fields.values(), guild_id],
            )
        conn.commit()


def get_birthdays_this_month_count(guild_id: str, month: int) -> int:
    """Sync — count members with birthdays this month who are in the guild (approximation)."""
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_birthdays WHERE month = ?", (month,)
        ).fetchone()
        return row[0] if row else 0

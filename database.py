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
    with sqlite3.connect(DB_PATH) as conn:
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
            
        conn.commit()

DEFAULT_MODULES = ["utility", "welcome_goodbye", "info", "music", "tickets", "autoroles", "reactionroles", "automods", "leveling"]

# ─── Blacklist (sync — Flask) ──────────────────────────────────────────────────

def get_blacklist() -> List[Dict]:
    """Return all blacklisted guilds."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_blacklist ORDER BY kicked_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist."""
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM guild_blacklist WHERE guild_id = ?", (guild_id,))
        conn.commit()


def is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (sync)."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return row is not None


# ─── Blacklist (async — discord.py bot) ───────────────────────────────────────

async def async_is_blacklisted(guild_id: str) -> bool:
    """Check if a guild is blacklisted (async)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM guild_blacklist WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
    return row is not None


async def async_add_to_blacklist(guild_id: str, guild_name: str = "", reason: str = "Bị kick bởi Owner"):
    """Add a guild to the blacklist (async)."""
    async with aiosqlite.connect(DB_PATH) as conn:
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
}

def get_guild_settings(guild_id: str) -> Dict:
    cache_key = f"settings:{guild_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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

    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO guild_modules (guild_id, module_name, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, module_name) DO UPDATE SET enabled = excluded.enabled""",
            (guild_id, module_name, int(enabled)),
        )
        conn.commit()
    cache.delete(f"modules:{guild_id}")

def get_guild_channels(guild_id: str) -> List[Dict]:
    """Return cached text channels (type=0) for a guild."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 0 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_categories(guild_id: str) -> List[Dict]:
    """Return cached category channels (type=4) for a guild."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_channels WHERE guild_id = ? AND channel_type = 4 ORDER BY channel_name",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_roles(guild_id: str) -> List[Dict]:
    """Return cached roles for a guild."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM guild_roles WHERE guild_id = ? ORDER BY position DESC",
            (guild_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]

def get_guild_meta(guild_id: str) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guild_meta WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None

def get_bot_guild_ids() -> List[str]:
    """Return list of guild IDs the bot is currently in (from cache)."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT guild_id FROM guild_meta").fetchall()
    return [r[0] for r in rows]

def get_saved_embeds(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO saved_embeds (guild_id, name, embed_json) VALUES (?, ?, ?)",
            (guild_id, name, json.dumps(embed_data, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid

def delete_embed(embed_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM saved_embeds WHERE id = ? AND guild_id = ?",
            (embed_id, guild_id),
        )
        conn.commit()

def get_top_users(guild_id: str, limit: int = 10) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM user_levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?", 
            (guild_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

# ─── Ticket helpers (Sync) ────────────────────────────────────────────────────

def get_ticket_panels(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM ticket_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM ticket_buttons WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_panel_message_id(panel_id: int, message_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE ticket_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

# ─── Reaction Roles helpers (Sync) ────────────────────────────────────────────

def get_reaction_roles_panels(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM reaction_roles_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM reaction_roles_items WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_reaction_roles_message_id(panel_id: int, message_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE reaction_roles_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

# ─── Async helpers (discord.py / bot) ─────────────────────────────────────────

async def async_get_guild_settings(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {"guild_id": guild_id, **_DEFAULT_SETTINGS}

async def async_get_logger_settings(guild_id: str) -> dict:
    cache_key = f"logger_settings:{guild_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH) as db:
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
    
    async with aiosqlite.connect(DB_PATH) as db:
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
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT event_type, event_label, date_hour, count 
            FROM guild_stats 
            WHERE guild_id = ? AND date_hour >= ?
            ORDER BY date_hour ASC
        """, (guild_id, start_date))
        return [_row_to_dict(row) for row in cur.fetchall()]

async def async_is_module_enabled(guild_id: str, module_name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT enabled FROM guild_modules WHERE guild_id = ? AND module_name = ?",
            (guild_id, module_name),
        ) as cur:
            row = await cur.fetchone()
    return bool(row[0]) if row else True  # Default: enabled

async def async_cache_guild(guild_id: str, name: str, icon: Optional[str], member_count: int):
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM guild_meta WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def async_cache_channels(guild_id: str, channels: List[Dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM guild_channels WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_channels (guild_id, channel_id, channel_name, channel_type) VALUES (?, ?, ?, ?)",
            [(guild_id, ch["id"], ch["name"], ch["type"]) for ch in channels],
        )
        await db.commit()

async def async_cache_roles(guild_id: str, roles: List[Dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM guild_roles WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO guild_roles (guild_id, role_id, role_name, color_hex, position) VALUES (?, ?, ?, ?, ?)",
            [(guild_id, r["id"], r["name"], r["color_hex"], r["position"]) for r in roles],
        )
        await db.commit()

# ─── Ticket async helpers ─────────────────────────────────────────────────────

async def async_get_all_ticket_panels() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? ORDER BY id DESC", (guild_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tracks"] = get_playlist_tracks(d["id"])
            result.append(d)
        return result

def get_playlist(playlist_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def get_playlist_by_name(guild_id: str, name: str) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)).fetchone()
        if row:
            d = dict(row)
            d["tracks"] = get_playlist_tracks(d["id"])
            return d
        return None

def create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        conn.commit()
        return cursor.lastrowid

def delete_playlist(playlist_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        conn.commit()

def add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        conn.commit()

def get_playlist_tracks(playlist_id: int) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)).fetchall()
        return [dict(r) for r in rows]

# ─── Playlist Async Helpers ───────────────────────────────────────────────────

async def async_get_playlists(guild_id: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlists WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)) as cur:
            row = await cur.fetchone()
        if row:
            d = dict(row)
            d["tracks"] = await async_get_playlist_tracks(d["id"])
            return d
        return None

async def async_create_playlist(guild_id: str, name: str, creator_id: str = "", creator_name: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO music_playlists (guild_id, name, creator_id, creator_name) VALUES (?, ?, ?, ?)", (guild_id, name, creator_id, creator_name))
        await db.commit()
        return cursor.lastrowid

async def async_delete_playlist(playlist_id: int, guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM music_playlists WHERE id = ? AND guild_id = ?", (playlist_id, guild_id))
        await db.commit()

async def async_add_track_to_playlist(playlist_id: int, track: Dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM music_playlist_tracks WHERE id = ?", (track_id,))
        await db.commit()

async def async_get_playlist_tracks(playlist_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def async_get_reaction_role_item(message_id: str, emoji: str) -> Optional[str]:
    """Returns the role_id if the reaction matches a configured reaction role item."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
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
    
    with sqlite3.connect(DB_PATH) as conn:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            result = dict(row)
        else:
            result = dict(_DEFAULT_LEVELING)
            
    cache.set(cache_key, result, ttl=300)
    return result

def set_leveling_settings(guild_id: str, settings: dict):
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)).fetchall()
        return {row[0]: row[1] for row in rows}

def set_level_roles(guild_id: str, roles: dict):
    """roles is a dict of {level: role_id}"""
    with sqlite3.connect(DB_PATH) as conn:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM leveling_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return dict(_DEFAULT_LEVELING)

async def async_get_level_roles(guild_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def async_get_user_level(guild_id: str, user_id: str) -> dict:
    cache_key = f"level:{guild_id}:{user_id}"
    cached = await cache.aget(cache_key)
    if cached is not None:
        return cached

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                result = dict(row)
            else:
                result = {"guild_id": guild_id, "user_id": user_id, "xp": 0, "level": 0, "last_message_at": 0, "last_voice_xp_at": 0}
                
    await cache.aset(cache_key, result, ttl=120) # 2 mins TTL
    return result

async def async_update_user_xp(guild_id: str, user_id: str, xp: int, level: int, last_message_at: float = None, last_voice_xp_at: float = None):
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()
    await cache.adelete(f"level:{guild_id}:{user_id}")

async def async_get_top_users(guild_id: str, limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, xp, level FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def async_get_user_rank(guild_id: str, user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        # Get rank based on XP
        async with db.execute("SELECT COUNT(*) + 1 FROM user_levels WHERE guild_id = ? AND xp > (SELECT xp FROM user_levels WHERE guild_id = ? AND user_id = ?)", (guild_id, guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return 1

# ─── Giveaway Functions ────────────────────────────────────────────────────────
async def async_create_giveaway(guild_id: str, channel_id: str, message_id: str, host_id: str, prize: str, winners_count: int, end_at: int, req_role_id: str = None, req_account_age_days: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, channel_id, message_id, host_id, prize, winners_count, end_at, req_role_id, req_account_age_days))
        await db.commit()

async def async_get_giveaway(message_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def async_update_giveaway(message_id: str, participants_json: str = None, ended: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if participants_json is not None and ended is not None:
            await db.execute("UPDATE giveaways SET participants_json = ?, ended = ? WHERE message_id = ?", (participants_json, ended, message_id))
        elif participants_json is not None:
            await db.execute("UPDATE giveaways SET participants_json = ? WHERE message_id = ?", (participants_json, message_id))
        elif ended is not None:
            await db.execute("UPDATE giveaways SET ended = ? WHERE message_id = ?", (ended, message_id))
        await db.commit()

async def async_get_active_giveaways() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM giveaways WHERE ended = 0") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


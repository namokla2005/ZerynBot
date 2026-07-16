"""
database.py — Shared SQLite database module.
Sync functions for Flask/dashboard, async functions for discord.py/bot.
"""
import os
import sqlite3
import json
from typing import Optional, Dict, List, Any
import aiosqlite

# ─── Path setup ────────────────────────────────────────────────────────────────
# This file lives at v2/database.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "bot.db")

def init_db():
    """Create all tables if they don't exist (sync, called at startup)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id              TEXT PRIMARY KEY,
                welcome_channel_id    TEXT,
                welcome_message       TEXT DEFAULT 'Xin chào {user}, chào mừng đến với **{server}**! 🎉',
                welcome_use_embed     INTEGER DEFAULT 1,
                welcome_embed_color   TEXT DEFAULT '#57F287',
                welcome_embed_title   TEXT DEFAULT '🎉 Chào mừng thành viên mới!',
                goodbye_channel_id    TEXT,
                goodbye_message       TEXT DEFAULT 'Tạm biệt **{user_name}**, chúc bạn nhiều may mắn! 👋',
                goodbye_use_embed     INTEGER DEFAULT 1,
                goodbye_embed_color   TEXT DEFAULT '#ED4245',
                goodbye_embed_title   TEXT DEFAULT '👋 Tạm biệt!',
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

            CREATE TABLE IF NOT EXISTS guild_roles (
                guild_id   TEXT,
                role_id    TEXT,
                role_name  TEXT,
                color_hex  TEXT,
                position   INTEGER,
                PRIMARY KEY (guild_id, role_id)
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
            
        cursor.execute("PRAGMA table_info(automod_settings)")
        am_cols = [row[1] for row in cursor.fetchall()]
        if "immune_roles" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN immune_roles TEXT DEFAULT '[]'")
        if "spam_allowed_channels" not in am_cols:
            conn.execute("ALTER TABLE automod_settings ADD COLUMN spam_allowed_channels TEXT DEFAULT '[]'")
            
        conn.commit()

DEFAULT_MODULES = ["utility", "welcome_goodbye", "info", "music", "tickets", "autoroles", "reactionroles", "automods"]

# ─── Sync helpers (Flask / dashboard) ─────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> Dict:
    return dict(row)

_DEFAULT_SETTINGS = {
    "welcome_channel_id":  None,
    "welcome_message":     "Xin chào {user}, chào mừng đến với **{server}**! 🎉",
    "welcome_use_embed":   1,
    "welcome_embed_color": "#57F287",
    "welcome_embed_title": "🎉 Chào mừng thành viên mới!",
    "goodbye_channel_id":  None,
    "goodbye_message":     "Tạm biệt **{user_name}**, chúc bạn nhiều may mắn! 👋",
    "goodbye_use_embed":   1,
    "goodbye_embed_color": "#ED4245",
    "goodbye_embed_title": "👋 Tạm biệt!",
    "autoroles_enabled":   0,
    "autoroles_user":      "[]",
    "autoroles_bot":       "[]",
}

def get_guild_settings(guild_id: str) -> Dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row:
        return _row_to_dict(row)
    return {"guild_id": guild_id, **_DEFAULT_SETTINGS}

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

def get_guild_modules(guild_id: str) -> Dict[str, bool]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT module_name, enabled FROM guild_modules WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    result = {m: True for m in DEFAULT_MODULES}
    for module_name, enabled in rows:
        result[module_name] = bool(enabled)
    return result

def set_module(guild_id: str, module_name: str, enabled: bool):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO guild_modules (guild_id, module_name, enabled) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, module_name) DO UPDATE SET enabled = excluded.enabled""",
            (guild_id, module_name, int(enabled)),
        )
        conn.commit()

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

async def async_get_guild_settings(guild_id: str) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {"guild_id": guild_id, **_DEFAULT_SETTINGS}

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

def create_playlist(guild_id: str, name: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("INSERT INTO music_playlists (guild_id, name) VALUES (?, ?)", (guild_id, name))
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

async def async_create_playlist(guild_id: str, name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO music_playlists (guild_id, name) VALUES (?, ?)", (guild_id, name))
        await db.commit()
        return cursor.lastrowid

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

async def async_get_playlist_tracks(playlist_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM music_playlist_tracks WHERE playlist_id = ? ORDER BY position ASC", (playlist_id,)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

# ─── Reaction Roles ───────────────────────────────────────────────────────────

def get_reaction_roles_panels(guild_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM reaction_roles_panels WHERE guild_id = ?", (guild_id,)).fetchall()
        panels = [_row_to_dict(r) for r in rows]
        for p in panels:
            items_rows = conn.execute("SELECT * FROM reaction_roles_items WHERE panel_id = ?", (p["id"],)).fetchall()
            p["items"] = [_row_to_dict(r) for r in items_rows]
        return panels

def get_reaction_roles_panel(panel_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM reaction_roles_panels WHERE id = ?", (panel_id,)).fetchone()
        if row:
            p = _row_to_dict(row)
            items_rows = conn.execute("SELECT * FROM reaction_roles_items WHERE panel_id = ?", (panel_id,)).fetchall()
            p["items"] = [_row_to_dict(r) for r in items_rows]
            return p
        return None

def save_reaction_roles_panel(guild_id: str, panel_data: dict, items_data: list) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        panel_id = panel_data.get("id")
        
        if panel_id:
            cur.execute("""
                UPDATE reaction_roles_panels
                SET name = ?, channel_id = ?, color = ?, title = ?, description = ?,
                    thumbnail_url = ?, image_url = ?, footer_text = ?
                WHERE id = ? AND guild_id = ?
            """, (
                panel_data.get("name"), panel_data.get("channel_id"),
                panel_data.get("color"), panel_data.get("title"), panel_data.get("description"),
                panel_data.get("thumbnail_url"), panel_data.get("image_url"), panel_data.get("footer_text"),
                panel_id, guild_id
            ))
            cur.execute("DELETE FROM reaction_roles_items WHERE panel_id = ?", (panel_id,))
        else:
            cur.execute("""
                INSERT INTO reaction_roles_panels 
                (guild_id, name, channel_id, color, title, description, thumbnail_url, image_url, footer_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id, panel_data.get("name"), panel_data.get("channel_id"),
                panel_data.get("color"), panel_data.get("title"), panel_data.get("description"),
                panel_data.get("thumbnail_url"), panel_data.get("image_url"), panel_data.get("footer_text")
            ))
            panel_id = cur.lastrowid
            
        for b in items_data:
            cur.execute("""
                INSERT INTO reaction_roles_items (panel_id, emoji, role_id)
                VALUES (?, ?, ?)
            """, (panel_id, b.get("emoji"), b.get("role_id")))
            
        conn.commit()
        return panel_id

def delete_reaction_roles_panel(panel_id: int, guild_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM reaction_roles_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.commit()

def update_reaction_roles_message_id(panel_id: int, message_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE reaction_roles_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()


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
    "notify_role_id": None,
    "log_channel_id": None,
    "immune_roles": "[]",
    "spam_allowed_channels": "[]"
}

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
                spam_enabled, bad_words_enabled, links_enabled, notify_role_id, log_channel_id,
                immune_roles, spam_allowed_channels
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                bad_words=excluded.bad_words,
                blacklist_links=excluded.blacklist_links,
                whitelist_links=excluded.whitelist_links,
                spam_enabled=excluded.spam_enabled,
                bad_words_enabled=excluded.bad_words_enabled,
                links_enabled=excluded.links_enabled,
                notify_role_id=excluded.notify_role_id,
                log_channel_id=excluded.log_channel_id,
                immune_roles=excluded.immune_roles,
                spam_allowed_channels=excluded.spam_allowed_channels
        """, (
            guild_id, bad_words, blacklist_links, whitelist_links,
            int(s.get("spam_enabled", 0)), int(s.get("bad_words_enabled", 0)), int(s.get("links_enabled", 0)),
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

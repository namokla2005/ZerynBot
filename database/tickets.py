"""
tickets.py — Panel ticket & reaction roles (sync cho dashboard, async cho bot).

Tách từ `database.py` (Giai đoạn 3.3).
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from cache import cache

from .conn import _connect_async, _connect_sync, _row_to_dict, get_db_connection, get_db_path

logger = logging.getLogger("ZerynBot.Database")

def get_ticket_panels(guild_id: str) -> List[Dict]:
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
        conn.execute("DELETE FROM ticket_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM ticket_buttons WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_panel_message_id(panel_id: int, message_id: str):
    with _connect_sync() as conn:
        conn.execute("UPDATE ticket_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

def get_reaction_roles_panels(guild_id: str) -> List[Dict]:
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
        conn.execute("DELETE FROM reaction_roles_panels WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        conn.execute("DELETE FROM reaction_roles_items WHERE panel_id = ?", (panel_id,))
        conn.commit()

def update_reaction_roles_message_id(panel_id: int, message_id: str):
    with _connect_sync() as conn:
        conn.execute("UPDATE reaction_roles_panels SET message_id = ? WHERE id = ?", (message_id, panel_id))
        conn.commit()

async def async_get_all_ticket_panels() -> List[Dict]:
    async with _connect_async() as db:
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
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT b.*, p.guild_id, p.support_role_id, p.name as panel_name
               FROM ticket_buttons b
               JOIN ticket_panels p ON b.panel_id = p.id
               WHERE b.id = ?""", (button_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

async def async_get_reaction_role_item(message_id: str, emoji: str) -> Optional[str]:
    """Returns the role_id if the reaction matches a configured reaction role item."""
    async with _connect_async() as db:
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

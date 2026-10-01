"""
economy.py — Kinh tế & shop: ví/ngân hàng, daily, chuyển tiền, inventory, bet.

Tách từ `database.py` (Giai đoạn 3.3). Các hàm dùng transaction SQLite để chống
overspend khi nhiều guild thao tác đồng thời.
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

def get_economy_settings(guild_id: str) -> dict:
    """Sync — Get economy settings for dashboard."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {"guild_id": guild_id, "daily_amount": 100, "streak_bonus": 20, "starting_balance": 50, "currency_symbol": "🪙", "currency_name": "Coins"}
        return _row_to_dict(row)

def update_economy_settings(guild_id: str, daily_amount: int, streak_bonus: int, starting_balance: int, currency_symbol: str = "🪙", currency_name: str = "Coins") -> None:
    """Sync — Update economy settings."""
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM economy_shop WHERE guild_id = ? ORDER BY price ASC", (guild_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]

def add_economy_shop_item(guild_id: str, role_id: str, name: str, price: int, stock: int = -1) -> int:
    """Sync — Add new role to server shop."""
    with _connect_sync() as conn:
        cursor = conn.execute("""
            INSERT INTO economy_shop (guild_id, role_id, name, price, stock)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, role_id, name, price, stock))
        conn.commit()
        return cursor.lastrowid

def delete_economy_shop_item(item_id: int, guild_id: str) -> None:
    """Sync — Delete a shop item."""
    with _connect_sync() as conn:
        conn.execute("DELETE FROM economy_shop WHERE id = ? AND guild_id = ?", (item_id, guild_id))
        conn.commit()

def get_top_economy_users(guild_id: str, limit: int = 10) -> list:
    """Sync — Get top richest members for leaderboard."""
    with _connect_sync() as conn:
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
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO economy_users (guild_id, user_id, wallet, bank)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                wallet=excluded.wallet,
                bank=excluded.bank
        """, (guild_id, user_id, wallet, bank))
        conn.commit()

async def async_get_economy_settings(guild_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"guild_id": guild_id, "daily_amount": 100, "streak_bonus": 20, "starting_balance": 50, "currency_symbol": "🪙", "currency_name": "Coins"}
            return dict(row)

async def async_get_economy_user(guild_id: str, user_id: str) -> dict:
    async with _connect_async() as db:
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

async def async_claim_daily(
    guild_id: str,
    user_id: str,
    reward: int,
    streak: int,
    cutoff: float = None,
    now: float = None,
) -> Optional[dict]:
    """Điểm danh NGUYÊN TỬ: chỉ cộng tiền nếu `last_daily_at <= cutoff`.

    Trước đây cog tự kiểm tra cooldown rồi mới gọi hàm này (check-then-act): hai
    tin nhắn gần như đồng thời đều qua được vòng kiểm tra → cộng tiền 2 lần.
    Giờ điều kiện nằm trong chính câu UPDATE; nếu `rowcount == 0` nghĩa là người
    dùng vừa điểm danh ở request khác → trả về None để cog báo cooldown.

    `cutoff=None` = bỏ qua kiểm tra (dùng cho lần điểm danh đầu / admin set).
    """
    now = time.time() if now is None else now
    async with _connect_async() as db:
        if cutoff is None:
            await db.execute("""
                INSERT INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
                VALUES (?, ?, ?, 0, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    wallet = wallet + ?,
                    daily_streak = ?,
                    last_daily_at = ?
            """, (guild_id, user_id, reward, streak, now, reward, streak, now))
            await db.commit()
        else:
            # Người dùng MỚI phải có last_daily_at = 0 (không phải `now`), nếu không
            # UPDATE bên dưới sẽ không khớp điều kiện và lần điểm danh đầu bị chặn.
            await db.execute("""
                INSERT INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
                VALUES (?, ?, 0, 0, 0, 0)
                ON CONFLICT(guild_id, user_id) DO NOTHING
            """, (guild_id, user_id))
            cursor = await db.execute("""
                UPDATE economy_users
                SET wallet = wallet + ?, daily_streak = ?, last_daily_at = ?
                WHERE guild_id = ? AND user_id = ? AND last_daily_at <= ?
            """, (reward, streak, now, guild_id, user_id, cutoff))
            await db.commit()
            if cursor.rowcount == 0:
                return None
    return await async_get_economy_user(guild_id, user_id)

async def async_claim_economy_cooldown(
    guild_id: str,
    user_id: str,
    action_type: str,
    cooldown: float,
    now: float = None,
) -> bool:
    """Giữ chỗ cooldown NGUYÊN TỬ cho `work` / `fish` / `hunt`.

    Trả False nếu cooldown chưa hết (đã có request khác chiếm slot). Nhờ vậy 2 lệnh
    gửi cùng lúc không thể cùng qua được cooldown (trước đây là check-then-act).
    """
    now = time.time() if now is None else now
    threshold = now - cooldown
    async with _connect_async() as db:
        await db.execute("""
            INSERT OR IGNORE INTO economy_cooldowns (guild_id, user_id, action_type, last_used)
            VALUES (?, ?, ?, 0)
        """, (guild_id, user_id, action_type))
        cursor = await db.execute("""
            UPDATE economy_cooldowns
            SET last_used = ?
            WHERE guild_id = ? AND user_id = ? AND action_type = ? AND last_used <= ?
        """, (now, guild_id, user_id, action_type, threshold))
        await db.commit()
        return cursor.rowcount > 0

async def async_modify_wallet(guild_id: str, user_id: str, delta: int) -> dict:
    async with _connect_async() as db:
        # Ensure user exists
        await async_get_economy_user(guild_id, user_id)
        await db.execute("""
            UPDATE economy_users
            SET wallet = MAX(0, wallet + ?)
            WHERE guild_id = ? AND user_id = ?
        """, (delta, guild_id, user_id))
        await db.commit()
    return await async_get_economy_user(guild_id, user_id)

async def async_place_bet(guild_id: str, user_id: str, amount: int) -> bool:
    """Trừ tiền cược NGUYÊN TỬ: chỉ thành công nếu wallet >= amount.
    Chặn 2 lệnh cược đồng thời vượt số dư ví."""
    if amount <= 0:
        return False
    async with _connect_async() as db:
        await db.execute("""
            INSERT OR IGNORE INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, 50, 0, 0, 0)
        """, (guild_id, user_id))
        cursor = await db.execute("""
            UPDATE economy_users
            SET wallet = wallet - ?
            WHERE guild_id = ? AND user_id = ? AND wallet >= ?
        """, (amount, guild_id, user_id, amount))
        if cursor.rowcount > 0:
            now = time.time()
            await db.execute("""
                INSERT INTO economy_transactions (guild_id, user_id, kind, amount, created_at)
                VALUES (?, ?, 'bet', ?, ?)
            """, (guild_id, user_id, -amount, now))
            await db.commit()
            return True
        return False

async def async_log_transaction(guild_id: str, user_id: str, kind: str, amount: int, counterparty: Optional[str] = None, note: Optional[str] = None) -> None:
    """Ghi nhận một giao dịch vào nhật ký tài chính economy_transactions."""
    try:
        async with _connect_async() as db:
            await db.execute("""
                INSERT INTO economy_transactions (guild_id, user_id, kind, amount, counterparty, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, user_id, kind, amount, counterparty, note, time.time()))
            await db.commit()
    except Exception as exc:
        logger.debug(f"[EconomyTx] log transaction error: {exc}")

async def async_get_user_transactions(guild_id: str, user_id: str, limit: int = 20) -> list:
    """Lấy danh sách các giao dịch gần đây của người dùng."""
    try:
        async with _connect_async() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM economy_transactions
                WHERE guild_id = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (guild_id, user_id, limit)) as cur:
                rows = await cur.fetchall()
                return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.debug(f"[EconomyTx] get transactions error: {exc}")
        return []

async def async_transfer_money(guild_id: str, from_user_id: str, to_user_id: str, amount: int) -> bool:
    if amount <= 0 or from_user_id == to_user_id:
        return False
    async with _connect_async() as db:
        # P2: Đảm bảo người nhận tồn tại trên CHÍNH KẾT NỐI NÀY để loại trừ hoàn toàn deadlock khóa ghi SQLite
        await db.execute("""
            INSERT OR IGNORE INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, 50, 0, 0, 0)
        """, (guild_id, to_user_id))

        # Trừ ví người gửi nguyên tử với điều kiện wallet >= amount
        cursor = await db.execute("""
            UPDATE economy_users
            SET wallet = wallet - ?
            WHERE guild_id = ? AND user_id = ? AND wallet >= ?
        """, (amount, guild_id, from_user_id, amount))
        if cursor.rowcount == 0:
            return False

        # Cộng ví người nhận
        await db.execute("""
            UPDATE economy_users
            SET wallet = wallet + ?
            WHERE guild_id = ? AND user_id = ?
        """, (amount, guild_id, to_user_id))

        # Ghi transaction log cho cả người gửi và người nhận trên cùng transaction
        now = time.time()
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, kind, amount, counterparty, created_at)
            VALUES (?, ?, 'transfer_out', ?, ?, ?)
        """, (guild_id, from_user_id, -amount, to_user_id, now))
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, kind, amount, counterparty, created_at)
            VALUES (?, ?, 'transfer_in', ?, ?, ?)
        """, (guild_id, to_user_id, amount, from_user_id, now))

        await db.commit()
        return True

async def async_get_economy_shop(guild_id: str) -> list:
    async with _connect_async() as db:
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
    is_all = isinstance(amount_raw, str) and amount_raw.lower() in ("all", "max")

    if not is_all:
        try:
            amount = int(amount_raw)
        except (ValueError, TypeError):
            return False, 0, user, "invalid_amount"
        if amount <= 0:
            return False, 0, user, "invalid_amount"

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        if is_all:
            async with db.execute("SELECT wallet FROM economy_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cur:
                row = await cur.fetchone()
                if not row or row["wallet"] <= 0:
                    current = await async_get_economy_user(guild_id, user_id)
                    return False, 0, current, "wallet_empty"
                amount = row["wallet"]

            cursor = await db.execute("""
                UPDATE economy_users
                SET wallet = 0, bank = bank + ?
                WHERE guild_id = ? AND user_id = ? AND wallet = ?
            """, (amount, guild_id, user_id, amount))
        else:
            cursor = await db.execute("""
                UPDATE economy_users
                SET wallet = wallet - ?, bank = bank + ?
                WHERE guild_id = ? AND user_id = ? AND wallet >= ?
            """, (amount, amount, guild_id, user_id, amount))

        await db.commit()
        if cursor.rowcount == 0:
            current = await async_get_economy_user(guild_id, user_id)
            return False, 0, current, "not_enough_wallet"

    updated = await async_get_economy_user(guild_id, user_id)
    return True, amount, updated, ""

async def async_withdraw_money(guild_id: str, user_id: str, amount_raw: str | int) -> tuple[bool, int, dict, str]:
    """
    Withdraw money from bank into wallet.
    Returns: (success: bool, amount_withdrawn: int, updated_user: dict, error_code: str)
    error_codes: 'invalid_amount', 'bank_empty', 'not_enough_bank', ''
    """
    user = await async_get_economy_user(guild_id, user_id)
    is_all = isinstance(amount_raw, str) and amount_raw.lower() in ("all", "max")

    if not is_all:
        try:
            amount = int(amount_raw)
        except (ValueError, TypeError):
            return False, 0, user, "invalid_amount"
        if amount <= 0:
            return False, 0, user, "invalid_amount"

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        if is_all:
            async with db.execute("SELECT bank FROM economy_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cur:
                row = await cur.fetchone()
                if not row or row["bank"] <= 0:
                    current = await async_get_economy_user(guild_id, user_id)
                    return False, 0, current, "bank_empty"
                amount = row["bank"]

            cursor = await db.execute("""
                UPDATE economy_users
                SET bank = 0, wallet = wallet + ?
                WHERE guild_id = ? AND user_id = ? AND bank = ?
            """, (amount, guild_id, user_id, amount))
        else:
            cursor = await db.execute("""
                UPDATE economy_users
                SET bank = bank - ?, wallet = wallet + ?
                WHERE guild_id = ? AND user_id = ? AND bank >= ?
            """, (amount, amount, guild_id, user_id, amount))

        await db.commit()
        if cursor.rowcount == 0:
            current = await async_get_economy_user(guild_id, user_id)
            return False, 0, current, "not_enough_bank"

    updated = await async_get_economy_user(guild_id, user_id)
    return True, amount, updated, ""

async def async_buy_shop_item(guild_id: str, user_id: str, item_id: int) -> tuple[bool, str, str, int]:
    """Return (success, role_id, error_message_or_item_name, item_price). Paid with Bank balance."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM economy_shop WHERE id = ? AND guild_id = ?", (item_id, guild_id)) as cur:
            item = await cur.fetchone()
            if not item:
                return False, "", "item_not_found", 0
            if item["stock"] == 0:
                return False, "", "out_of_stock", item["price"]

        price = item["price"]
        # P2: Đảm bảo user tồn tại trên CHÍNH KẾT NỐI NÀY (tránh deadlock kết nối lồng)
        await db.execute("""
            INSERT OR IGNORE INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, 50, 0, 0, 0)
        """, (guild_id, user_id))

        # Trừ tiền từ BANK có ràng buộc điều kiện bank >= price
        cur_user = await db.execute("""
            UPDATE economy_users
            SET bank = bank - ?
            WHERE guild_id = ? AND user_id = ? AND bank >= ?
        """, (price, guild_id, user_id, price))
        if cur_user.rowcount == 0:
            return False, "", "not_enough_bank", price

        # Nếu item có giới hạn tồn kho (stock > 0), trừ stock có điều kiện
        if item["stock"] > 0:
            cur_stock = await db.execute("""
                UPDATE economy_shop
                SET stock = stock - 1
                WHERE id = ? AND guild_id = ? AND stock > 0
            """, (item_id, guild_id))
            if cur_stock.rowcount == 0:
                # Hết hàng ngay tại thời điểm mua -> hoàn tiền lại vào bank
                await db.execute("""
                    UPDATE economy_users SET bank = bank + ? WHERE guild_id = ? AND user_id = ?
                """, (price, guild_id, user_id))
                await db.commit()
                return False, "", "out_of_stock", price

        await db.commit()
        return True, item["role_id"], item["name"], price

async def async_refund_shop_purchase(
    guild_id: str,
    user_id: str,
    item_name: str,
    price: int,
    item_id: Optional[int] = None,
    restore_stock: bool = True,
) -> bool:
    """Hoàn tiền khi mua hàng thất bại (role không còn / bot không gán được role).

    Trước đây `/buy` trừ tiền bank + trừ stock rồi mới gán role; nếu role đã bị xoá
    hoặc `add_roles` lỗi thì người dùng mất tiền mà không nhận được gì.
    Dùng chung 1 transaction để tránh hoàn tiền nửa vời.
    """
    if price <= 0:
        return False
    try:
        async with _connect_async() as db:
            await db.execute("""
                UPDATE economy_users SET bank = bank + ? WHERE guild_id = ? AND user_id = ?
            """, (price, guild_id, user_id))

            if restore_stock and item_id is not None:
                # Chỉ trả lại stock cho item có giới hạn tồn kho (stock >= 0).
                await db.execute("""
                    UPDATE economy_shop SET stock = stock + 1
                    WHERE id = ? AND guild_id = ? AND stock >= 0
                """, (item_id, guild_id))

            await db.execute("""
                INSERT INTO economy_transactions (guild_id, user_id, kind, amount, counterparty, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, user_id, "refund", price, None, f"Hoàn tiền mua '{item_name}' (không gán được role)", time.time()))
            await db.commit()
        logger.info(f"[Economy] Refunded {price} to {user_id} for item '{item_name}'")
        return True
    except Exception as exc:
        logger.error(f"[Economy] refund_shop_purchase error: {exc}")
        return False

async def async_get_top_economy(guild_id: str, limit: int = 10) -> list:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, wallet, bank, (wallet + bank) as total, daily_streak
            FROM economy_users
            WHERE guild_id = ?
            ORDER BY total DESC LIMIT ?
        """, (guild_id, limit)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def async_get_inventory(guild_id: str, user_id: str) -> list[dict]:
    """Lấy danh sách vật phẩm trong túi đồ của user, sắp xếp theo độ hiếm và tên."""
    rarity_order = "CASE rarity WHEN 'legendary' THEN 1 WHEN 'epic' THEN 2 WHEN 'rare' THEN 3 ELSE 4 END"
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"""
            SELECT * FROM user_inventory
            WHERE guild_id = ? AND user_id = ? AND quantity > 0
            ORDER BY {rarity_order}, item_name ASC
        """, (guild_id, user_id)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def async_get_inventory_item(guild_id: str, user_id: str, item_id: str) -> dict | None:
    """Lấy thông tin một vật phẩm cụ thể trong túi đồ."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM user_inventory
            WHERE guild_id = ? AND user_id = ? AND item_id = ? AND quantity > 0
        """, (guild_id, user_id, item_id)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def async_add_inventory_item(
    guild_id: str,
    user_id: str,
    item_id: str,
    item_name: str,
    item_type: str,
    rarity: str = "common",
    quantity: int = 1,
    sell_price: int = 50
) -> dict:
    """Thêm hoặc cộng dồn số lượng vật phẩm vào túi đồ."""
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO user_inventory (guild_id, user_id, item_id, item_name, item_type, rarity, quantity, sell_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                sell_price = excluded.sell_price,
                item_name = excluded.item_name,
                updated_at = CURRENT_TIMESTAMP
        """, (guild_id, user_id, item_id, item_name, item_type, rarity, quantity, sell_price))
        await db.commit()
    return await async_get_inventory_item(guild_id, user_id, item_id) or {}

async def async_sell_inventory_item(guild_id: str, user_id: str, item_id: str, quantity: int = 1) -> tuple[bool, int, str]:
    """Bán một số lượng vật phẩm chỉ định lấy tiền vào ví. Trả về (success, total_earned, item_name)."""
    if quantity <= 0:
        return False, 0, ""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM user_inventory
            WHERE guild_id = ? AND user_id = ? AND item_id = ? AND quantity >= ?
        """, (guild_id, user_id, item_id, quantity)) as cur:
            item = await cur.fetchone()
            if not item:
                return False, 0, ""

        earned = item["sell_price"] * quantity
        if item["quantity"] == quantity:
            await db.execute("DELETE FROM user_inventory WHERE id = ?", (item["id"],))
        else:
            await db.execute("UPDATE user_inventory SET quantity = quantity - ? WHERE id = ?", (quantity, item["id"]))

        # Cộng tiền vào ví
        await db.execute("""
            INSERT INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET wallet = wallet + ?
        """, (guild_id, user_id, earned, earned))
        await db.commit()
        return True, earned, item["item_name"]

async def async_sell_all_inventory(guild_id: str, user_id: str, rarity: str = None) -> tuple[int, int]:
    """Bán toàn bộ vật phẩm (hoặc lọc theo rarity) lấy tiền vào ví. Trả về (items_sold_count, total_earned)."""
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM user_inventory WHERE guild_id = ? AND user_id = ? AND quantity > 0"
        params = [guild_id, user_id]
        if rarity:
            query += " AND rarity = ?"
            params.append(rarity)

        async with db.execute(query, tuple(params)) as cur:
            items = await cur.fetchall()

        if not items:
            return 0, 0

        total_earned = sum(item["sell_price"] * item["quantity"] for item in items)
        total_count = sum(item["quantity"] for item in items)

        delete_query = "DELETE FROM user_inventory WHERE guild_id = ? AND user_id = ?"
        delete_params = [guild_id, user_id]
        if rarity:
            delete_query += " AND rarity = ?"
            delete_params.append(rarity)

        await db.execute(delete_query, tuple(delete_params))
        await db.execute("""
            INSERT INTO economy_users (guild_id, user_id, wallet, bank, daily_streak, last_daily_at)
            VALUES (?, ?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET wallet = wallet + ?
        """, (guild_id, user_id, total_earned, total_earned))
        await db.commit()
        return total_count, total_earned

async def async_get_economy_cooldown(guild_id: str, user_id: str, action_type: str) -> float:
    """Lấy timestamp lần cuối thực hiện action (work, fish, hunt, rob...)."""
    async with _connect_async() as db:
        async with db.execute(
            "SELECT last_used FROM economy_cooldowns WHERE guild_id = ? AND user_id = ? AND action_type = ?",
            (guild_id, user_id, action_type)
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0

async def async_set_economy_cooldown(guild_id: str, user_id: str, action_type: str, last_used: float = None) -> None:
    """Ghi nhận timestamp thực hiện action."""
    import time
    ts = last_used if last_used is not None else time.time()
    async with _connect_async() as db:
        await db.execute("""
            INSERT INTO economy_cooldowns (guild_id, user_id, action_type, last_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, action_type) DO UPDATE SET last_used = excluded.last_used
        """, (guild_id, user_id, action_type, ts))
        await db.commit()

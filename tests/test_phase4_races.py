"""Tests Phase 4 — race condition & tiền tệ.

Mỗi test đều chạy THẬT (nhiều request đồng thời trên DB tạm) và kiểm tra số dư/cuối
cùng, không đọc cờ nội bộ — đây chính là lớp kiểm tra mà 158 test cũ còn thiếu.
"""
import asyncio
import json
import sqlite3
import time

import pytest


GUILD = "g_p4"


def _set_starting_balance(db_path, guild_id, amount):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO economy_settings (guild_id, starting_balance) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET starting_balance = excluded.starting_balance",
            (guild_id, amount),
        )
        conn.commit()


# ─── H3: /sell double-pay ─────────────────────────────────────────────────────

async def test_two_concurrent_sells_of_one_item_pay_once(temp_db):
    import database as db

    user = "u_sell_1"
    await db.async_add_inventory_item(GUILD, user, "item_x", "Rare Charm", "consumable",
                                      "rare", 1, 700)

    results = await asyncio.gather(
        db.async_sell_inventory_item(GUILD, user, "item_x", 1),
        db.async_sell_inventory_item(GUILD, user, "item_x", 1),
    )
    earned = [r[1] for r in results if r[0]]
    assert len(earned) == 1, f"cả hai lượt bán cùng thành công: {results}"
    wallet = (await db.async_get_economy_user(GUILD, user))["wallet"]
    assert wallet == 700, f"được cộng tiền 2 lần: wallet={wallet}"


async def test_concurrent_partial_sell_cannot_oversell(temp_db):
    import database as db

    user = "u_sell_2"
    await db.async_add_inventory_item(GUILD, user, "item_y", "Potion", "consumable",
                                      "common", 3, 100)
    results = await asyncio.gather(*[
        db.async_sell_inventory_item(GUILD, user, "item_y", 2) for _ in range(4)
    ])
    sold = sum(1 for ok, _, _ in results if ok)
    assert sold == 1, f"4 lệnh bán 2/3 item, chỉ 1 lệnh hợp lệ, thực tế: {sold}"
    item = await db.async_get_inventory_item(GUILD, user, "item_y")
    assert item["quantity"] == 1, f"số lượng bị âm/lệch: {item['quantity']}"


async def test_sell_all_twice_pays_once(temp_db):
    import database as db

    user = "u_sellall"
    await db.async_add_inventory_item(GUILD, user, "a", "A", "consumable", "rare", 2, 500)
    await db.async_add_inventory_item(GUILD, user, "b", "B", "consumable", "rare", 1, 300)

    results = await asyncio.gather(
        db.async_sell_all_inventory(GUILD, user),
        db.async_sell_all_inventory(GUILD, user),
    )
    total_earned = sum(r[1] for r in results)
    assert total_earned == 1300, f"bán 2 lần thu {total_earned} (đúng ra 1300): {results}"
    assert sum(r[0] for r in results) == 3, "số item bán được bị nhân đôi"


# ─── H5: starting_balance & /pay cho user mới ─────────────────────────────────

async def test_starting_balance_zero_mints_nothing(temp_db):
    import database as db

    _set_starting_balance(temp_db, GUILD, 0)
    ok = await db.async_place_bet(GUILD, "u_poor", 10)
    assert ok is False, "guild đặt starting_balance=0 mà user mới vẫn cược được"
    user = await db.async_get_economy_user(GUILD, "u_poor")
    assert user["wallet"] == 0, f"mint hardcode 50 coin: {user['wallet']}"


async def test_starting_balance_is_respected_on_mint(temp_db):
    import database as db

    _set_starting_balance(temp_db, GUILD, 5000)
    assert await db.async_place_bet(GUILD, "u_rich", 100) is True
    user = await db.async_get_economy_user(GUILD, "u_rich")
    assert user["wallet"] == 4900, (
        f"phải bắt đầu từ 5000 rồi cược 100, thực tế {user['wallet']} (hardcode 50?)"
    )


async def test_pay_from_brand_new_user_succeeds(temp_db):
    """Lỗi cũ: chỉ người NHẬN được INSERT OR IGNORE, nên UPDATE trừ tiền của người gửi
    khớp 0 dòng -> `/pay` thất bại với user chưa từng chạm economy."""
    import database as db

    _set_starting_balance(temp_db, GUILD, 500)
    ok = await db.async_transfer_money(GUILD, "u_new_sender", "u_new_receiver", 200)
    assert ok is True, "/pay từ user hoàn toàn mới vẫn thất bại"
    sender = await db.async_get_economy_user(GUILD, "u_new_sender")
    receiver = await db.async_get_economy_user(GUILD, "u_new_receiver")
    assert sender["wallet"] == 300, sender
    assert receiver["wallet"] == 700, receiver


# ─── H4: XP lost update ───────────────────────────────────────────────────────

def _level_from_xp(xp):
    import math

    return math.floor(0.1 * math.sqrt(xp))


async def test_concurrent_xp_adds_are_not_lost(temp_db):
    import database as db

    user = "u_xp"
    results = await asyncio.gather(*[
        db.async_add_user_xp(GUILD, user, 5, level_from_xp=_level_from_xp)
        for _ in range(20)
    ])
    row = await db.async_get_user_level(GUILD, user)
    assert row["xp"] == 100, (
        f"20 lần +5 XP phải ra 100, thực tế {row['xp']} — read-modify-write đè nhau"
    )
    assert row["level"] == _level_from_xp(100)


async def test_xp_add_never_goes_negative(temp_db):
    import database as db

    await db.async_add_user_xp(GUILD, "u_xp2", 50, level_from_xp=_level_from_xp)
    result = await db.async_add_user_xp(GUILD, "u_xp2", -9999, level_from_xp=_level_from_xp)
    assert result["xp"] == 0, f"XP bị âm: {result['xp']}"


async def test_message_and_voice_xp_do_not_clobber_each_other(temp_db):
    """Mô phỏng đúng kịch bản bug: loop XP voice và XP tin nhắn ghi cùng lúc."""
    import database as db

    user = "u_xp3"
    await asyncio.gather(
        db.async_add_user_xp(GUILD, user, 20, level_from_xp=_level_from_xp, last_message_at=time.time()),
        db.async_add_user_xp(GUILD, user, 30, level_from_xp=_level_from_xp, last_voice_xp_at=time.time()),
    )
    row = await db.async_get_user_level(GUILD, user)
    assert row["xp"] == 50, f"một trong hai nguồn XP bị mất: {row['xp']}"
    assert row.get("last_message_at") and row.get("last_voice_xp_at")


# ─── H12: giveaway participants ───────────────────────────────────────────────

async def test_concurrent_giveaway_entries_are_not_lost(temp_db):
    import database as db

    msg_id = "gw_p4_1"
    await db.async_create_giveaway(GUILD, "ch1", msg_id, "u_host", "Prize", 1, int(time.time()) + 3600)
    users = [f"u{i}" for i in range(25)]
    results = await asyncio.gather(*[
        db.async_toggle_giveaway_participant(msg_id, u) for u in users
    ])
    gw = await db.async_get_giveaway(msg_id)
    participants = json.loads(gw["participants_json"])
    assert len(participants) == 25, (
        f"25 người bấm tham gia, chỉ còn {len(participants)} — blob JSON đè nhau"
    )
    assert all(r["joined"] for r in results)


async def test_giveaway_toggle_removes_and_rejects_after_end(temp_db):
    import database as db

    msg_id = "gw_p4_2"
    await db.async_create_giveaway(GUILD, "ch1", msg_id, "u_host", "Prize", 1, int(time.time()) + 3600)
    first = await db.async_toggle_giveaway_participant(msg_id, "u_a")
    assert first["joined"] is True
    second = await db.async_toggle_giveaway_participant(msg_id, "u_a")
    assert second["joined"] is False and second["participants"] == []
    await db.async_update_giveaway(msg_id, ended=1)
    assert await db.async_toggle_giveaway_participant(msg_id, "u_b") is None, (
        "giveaway đã kết thúc mà vẫn ghi được người vào"
    )


# ─── H21: support thread ──────────────────────────────────────────────────────

def test_only_one_open_support_thread_per_user(temp_db):
    import database as db

    t1 = db.get_or_create_support_thread("u_sup", "Alice", "")
    t2 = db.get_or_create_support_thread("u_sup", "Alice", "")
    assert t1["thread_id"] == t2["thread_id"], "hai lần gọi tạo hai thread mở"
    with sqlite3.connect(temp_db) as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM support_threads WHERE user_id='u_sup' AND status != 'resolved'"
        ).fetchone()[0]
    assert open_count == 1


def test_support_thread_unique_index_exists(temp_db):
    with sqlite3.connect(temp_db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_support_threads_one_open" in names, "ràng buộc một-thread-mở chưa được tạo"

    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO support_threads (thread_id, user_id, user_name, status)"
            " VALUES ('ok1','u_dup','Alice','open')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO support_threads (thread_id, user_id, user_name, status)"
                " VALUES ('ok2','u_dup','Alice','open')"
            )
        # Thread ĐÃ resolved thì không bị ràng buộc chặn (partial index).
        conn.execute(
            "INSERT INTO support_threads (thread_id, user_id, user_name, status)"
            " VALUES ('ok3','u_dup','Alice','resolved')"
        )
        conn.commit()
    finally:
        conn.close()


def test_activity_log_read_does_not_delete(temp_db):
    """Đường ĐỌC không được ghi: mỗi lượt poll /admin từng chạy một DELETE, giành
    write-lock của SQLite đang phục vụ bot."""
    old = time.time() - (400 * 86400)
    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO activity_logs (guild_id, user_id, user_name, event_type, action, created_at)"
            " VALUES ('g','u','n','admin_action','x',?)", (old,),
        )
        conn.commit()

    import asyncio
    import database as db
    asyncio.run(db.async_get_system_activity_logs(limit=50, days_ttl=7))

    with sqlite3.connect(temp_db) as conn:
        still_there = conn.execute(
            "SELECT COUNT(*) FROM activity_logs WHERE created_at < ?", (time.time() - 100 * 86400,)
        ).fetchone()[0]
    assert still_there == 1, "hàm đọc đã xóa bản ghi — việc đó của job prune"


# ─── H11: /warn leo quyền (wiring) ────────────────────────────────────────────

def test_warn_has_role_hierarchy_guards():
    """Soạn thảo guard giống /kick — kiểm tra bằng wiring vì runtime cần guild thật."""
    import inspect
    from cogs.moderation import Moderation

    src = inspect.getsource(Moderation.warn.callback if hasattr(Moderation.warn, "callback") else Moderation.warn)
    assert "member.top_role >= interaction.user.top_role" in src, (
        "/warn thiếu guard chặn mod thao tác người cấp cao hơn"
    )
    assert "interaction.guild.me.top_role" in src, (
        "/warn thiếu guard vai trò bot — auto-kick sẽ chạy bằng quyền của bot"
    )

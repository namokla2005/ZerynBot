"""Phase 3 — trần giữ liệu của `economy_transactions` (M1).

Bất biến phía vận hành: một server chạy 24/7 trên máy 6GB không được tích sổ phụ vô
hạn, NHƯNG prune phải chỉ ăn đúng dòng cũ. Kiểu cột là phần dễ gãy nhất — cùng họ
bẫy epoch-vs-TEXT đã từng khiến job prune xóa sạch reminders chưa tới hạn.
"""
import sqlite3
import time

import pytest

DAY = 86400


def _sync_conn():
    import database
    return sqlite3.connect(database.get_db_path())


async def _seed_two_transactions(guild_id: str):
    from database import async_log_transaction
    await async_log_transaction(guild_id, "u_old", "work", 100)
    await async_log_transaction(guild_id, "u_new", "work", 100)
    con = _sync_conn()
    try:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM economy_transactions WHERE guild_id = ? ORDER BY id", (guild_id,)
        ).fetchall()]
        old_id, new_id = ids[0], ids[1]
        con.execute("UPDATE economy_transactions SET created_at = ? WHERE id = ?",
                    (time.time() - 400 * DAY, old_id))
        con.execute("UPDATE economy_transactions SET created_at = ? WHERE id = ?",
                    (time.time() - 5 * DAY, new_id))
        con.commit()
    finally:
        con.close()
    return old_id, new_id


def _surviving_users(guild_id: str):
    con = _sync_conn()
    try:
        return sorted(r[0] for r in con.execute(
            "SELECT user_id FROM economy_transactions WHERE guild_id = ?", (guild_id,)
        ).fetchall())
    finally:
        con.close()


async def test_only_transactions_past_the_window_are_pruned(temp_db):
    """Mặc định 365 ngày (user đã duyệt): dòng 400 ngày bay, dòng 5 ngày còn."""
    from database import async_prune_old_data
    await _seed_two_transactions("g_ret_1")

    deleted = await async_prune_old_data()

    assert deleted.get("economy_transactions") == 1, (
        f"prune phải báo đúng 1 dòng bị xóa, thực tế: {deleted}"
    )
    assert _surviving_users("g_ret_1") == ["u_new"], "phải giữ đúng giao dịch 5 ngày tuổi"


async def test_window_is_configurable(temp_db):
    from database import async_prune_old_data
    await _seed_two_transactions("g_ret_1b")

    deleted = await async_prune_old_data(economy_tx_days=3)

    assert deleted.get("economy_transactions") == 2, deleted
    assert _surviving_users("g_ret_1b") == []


async def test_prune_reports_zero_when_nothing_is_old_enough(temp_db):
    from database import async_log_transaction, async_prune_old_data
    await async_log_transaction("g_ret_2", "u1", "work", 10)
    await async_log_transaction("g_ret_2", "u2", "fish", 20)

    deleted = await async_prune_old_data(economy_tx_days=365)

    assert deleted.get("economy_transactions") == 0
    assert _surviving_users("g_ret_2") == ["u1", "u2"]


async def test_prune_predicate_matches_the_column_type(temp_db):
    """Đổi loại cột `created_at` mà quên đổi vị từ là xóa nhầm (hoặc không xóa gì) IM LẶNG."""
    con = _sync_conn()
    try:
        cols = {r[1]: r[2].upper() for r in con.execute("PRAGMA table_info(economy_transactions)")}
    finally:
        con.close()
    assert cols.get("CREATED_AT", cols.get("created_at")) == "REAL", (
        f"created_at không còn là REAL epoch ({cols}); prune dùng số học epoch phải được "
        "xem lại TRƯỚC khi nó âm thầm xóa sạch lịch sử kinh tế của user"
    )


async def test_wallet_and_bank_balances_are_never_pruned(temp_db):
    """Retention chỉ đánh vào sổ phụ, không được chạm số dư — đó là dữ liệu member."""
    from database import async_prune_old_data, async_get_economy_user
    await async_get_economy_user("g_ret_3", "u_rich")   # tạo dòng economy_users
    con = _sync_conn()
    try:
        con.execute("UPDATE economy_users SET wallet = 5000, bank = 9000 "
                    "WHERE guild_id = 'g_ret_3' AND user_id = 'u_rich'")
        con.execute("UPDATE economy_users SET last_daily_at = ? "
                    "WHERE guild_id = 'g_ret_3' AND user_id = 'u_rich'", (time.time() - 900 * DAY,))
        con.commit()
    finally:
        con.close()

    await async_prune_old_data()

    con = _sync_conn()
    try:
        row = con.execute("SELECT wallet, bank FROM economy_users "
                          "WHERE guild_id='g_ret_3' AND user_id='u_rich'").fetchone()
    finally:
        con.close()
    assert row == (5000, 9000), f"số dư bị prune ăn mất: {row}"


class _FakeCursor:
    def __init__(self, rowcount):
        self.rowcount = rowcount

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeDb:
    """Kết nối giả ghi lại SỐ câu DELETE và SỐ lần commit — chính là thứ WAL cần."""

    def __init__(self, rowcounts):
        self._rowcounts = list(rowcounts)
        self.statements = []
        self.commits = 0

    def execute(self, sql, params=()):
        self.statements.append(sql)
        return _FakeCursor(self._rowcounts.pop(0))

    async def commit(self):
        self.commits += 1


async def test_prune_deletes_in_batches_and_commits_between_batches(temp_db):
    """Một câu DELETE ăn cả năm lịch sử sẽ giữ write-lock WAL và treo /work, /pay, /bet."""
    from database.maintenance import _delete_in_batches

    db = _FakeDb([2, 2, 1])
    deleted = await _delete_in_batches(db, "economy_transactions", "created_at < ?", (0.0,), batch=2)

    assert deleted == 5
    assert len(db.statements) == 3, f"cần 3 mẻ cho 5 dòng với batch=2, thực tế {len(db.statements)}"
    assert db.commits == 3, f"phải nhả write-lock sau MỖI mẻ (commit), thực tế {db.commits}"
    assert all("LIMIT" in s.upper() for s in db.statements), db.statements


async def test_batch_loop_stops_on_a_short_batch(temp_db):
    """Mẻ trả về ít hơn batch = hết việc -> dừng, không quét tiếp vô nghĩa."""
    from database.maintenance import _delete_in_batches

    db = _FakeDb([2, 0])
    deleted = await _delete_in_batches(db, "t", "x < ?", (0.0,), batch=2)

    assert deleted == 2
    assert len(db.statements) == 2, db.statements
    assert db._rowcounts == [], "loop phải dừng ngay sau mẻ ngắn, không gọi thêm execute"


async def test_rejects_a_non_identifier_table_name(temp_db):
    import pytest as _pt
    from database.maintenance import _delete_in_batches

    with _pt.raises(ValueError):
        await _delete_in_batches(_FakeDb([]), 'economy_transactions; DROP TABLE reminders; --',
                                 "created_at < ?", (0.0,))


async def test_prune_predicate_is_covered_by_an_index(temp_db):
    """Mẻ DELETE LIMIT n mà không có index created_at = full-scan bảng lớn nhất MỖI mẻ."""
    con = _sync_conn()
    try:
        idx_names = [r[1] for r in con.execute("PRAGMA index_list(economy_transactions)")]
        covered = []
        for name in idx_names:
            cols = [r[2] for r in con.execute(f"PRAGMA index_info('{name}')")]
            if cols and cols[0] == "created_at":
                covered.append(name)
    finally:
        con.close()
    assert covered, (
        f"không index nào bắt đầu bằng created_at (idx: {idx_names}) — "
        "_delete_in_batches sẽ quét toàn bộ bảng ở mỗi mẻ"
    )


async def test_old_mod_warnings_are_pruned_but_recent_ones_survive(temp_db):
    """mod_warnings la TEXT 'YYYY-MM-DD HH:MM:SS' — khong phai epoch, dung sai la mat lich su."""
    import sqlite3
    from database import async_prune_old_data, init_db

    init_db()
    con = sqlite3.connect(database_path())
    try:
        now = time.time()
        for who, age in (("u_old", 500), ("u_new", 10)):
            con.execute(
                "INSERT INTO mod_warnings (guild_id, user_id, mod_id, reason, created_at) "
                "VALUES ('g_warn', ?, 'm1', 'vi pham', datetime(?, 'unixepoch'))",
                (who, now - age * DAY),
            )
        con.commit()
    finally:
        con.close()

    deleted = await async_prune_old_data()

    assert deleted.get("mod_warnings") == 1, deleted
    assert _warning_users("g_warn") == ["u_new"]


def database_path():
    import database
    return database.get_db_path()


def _warning_users(guild_id: str):
    con = sqlite3.connect(database_path())
    try:
        return sorted(r[0] for r in con.execute(
            "SELECT user_id FROM mod_warnings WHERE guild_id = ?", (guild_id,)
        ).fetchall())
    finally:
        con.close()

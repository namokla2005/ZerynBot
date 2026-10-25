"""P2-B — Không xoá log khi đọc, economy không nhận giá âm, automod bắt domain trần,
module gate cho app_commands.Group, và các giới hạn payload.
"""
import asyncio
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_COGS = os.path.join(ROOT, "bot", "cogs")
sys.path.insert(0, _COGS)
try:
    import automod as am  # noqa: E402
    import customcommands as cc  # noqa: E402
    import tempvoice as tv  # noqa: E402
finally:
    sys.path.remove(_COGS)


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_read_activity_logs_does_not_delete_old_rows(temp_db):
    import database as db

    old_ts = time.time() - 8 * 86400
    with db.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO activity_logs (guild_id, user_name, action, event_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("g1", "u1", "/old", "command", old_ts),
        )
        conn.commit()

    logs = db.get_system_activity_logs(limit=10, days_ttl=7)
    assert all(row["action"] != "/old" for row in logs)

    with db.get_db_connection() as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM activity_logs WHERE action = '/old'"
        ).fetchone()[0]
    assert left == 1, "đường đọc đã xoá log cũ (phải để maintenance job làm)"


def test_negative_price_cannot_mint_money(temp_db):
    import database as db

    db.add_economy_shop_item("g1", "role1", "Negative", -500, -1)
    item = db.get_economy_shop("g1")[0]
    assert item["price"] >= 1, "giá âm phải bị chặn tại biên DB"

    db.update_user_balance("g1", "u1", 0, 1000)
    with db.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO economy_shop (guild_id, role_id, name, price, stock) VALUES (?, ?, ?, ?, ?)",
            ("g1", "role_x", "Legacy negative", -500, -1),
        )
        conn.commit()
        neg_id = conn.execute(
            "SELECT id FROM economy_shop WHERE name = 'Legacy negative'"
        ).fetchone()[0]

    ok, _role, err, _price = asyncio.run(db.async_buy_shop_item("g1", "u1", neg_id))
    assert ok is False and err == "invalid_price"
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["bank"] == 1000


def test_buy_writes_ledger_and_economy_settings_clamped(temp_db):
    import database as db

    db.update_economy_settings("g1", -10, -10, -10)
    settings = asyncio.run(db.async_get_economy_settings("g1"))
    assert settings["daily_amount"] == 0
    assert settings["starting_balance"] == 0

    db.add_economy_shop_item("g1", "role1", "VIP", 100, -1)
    item = db.get_economy_shop("g1")[0]
    db.update_user_balance("g1", "u1", 0, 500)

    ok, role_id, name, price = asyncio.run(db.async_buy_shop_item("g1", "u1", item["id"]))
    assert ok is True and role_id == "role1" and price == 100
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["bank"] == 400

    txs = asyncio.run(db.async_get_user_transactions("g1", "u1", limit=10))
    assert any(tx["kind"] == "buy" and tx["amount"] == -100 for tx in txs), txs


def test_claim_daily_negative_reward_does_not_mint(temp_db):
    import database as db

    asyncio.run(db.async_claim_daily("g1", "u1", -100, 0))
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["wallet"] == 0


def test_automod_bare_domain_and_unicode_fold():
    assert am.BARE_DOMAIN_PATTERN.findall("discord-nitro.com/claim") == ["discord-nitro.com"]
    folded = am.normalize_scan_text("free\u2011nitro")
    assert "free-nitro" in folded, folded


def test_automod_edit_checks_caps():
    class Guild:
        id = 1
        owner_id = 0

    class Author:
        bot = False
        roles = []
        guild_permissions = types.SimpleNamespace(manage_messages=False, administrator=False)

    class Channel:
        id = 2

    class Msg:
        def __init__(self, content):
            self.guild = Guild()
            self.author = Author()
            self.content = content
            self.mentions = []
            self.role_mentions = []
            self.embeds = []
            self.stickers = []
            self.channel = Channel()

    handled = []

    async def fake_gate(message):
        return {"anti_caps_enabled": True, "anti_mentions_enabled": False}

    async def fake_text(*args, **kwargs):
        return False

    async def fake_handle(message, reason, settings):
        handled.append(reason)

    async def fake_lang(guild):
        return {}

    self_obj = types.SimpleNamespace(
        _automod_gate=fake_gate,
        _check_text_rules=fake_text,
        _handle_violation=fake_handle,
        _reason_lang=fake_lang,
    )
    before = Msg("hello")
    after = Msg("THIS IS ALL CAPS AND LONG ENOUGH")

    asyncio.run(am.Automod.on_message_edit(self_obj, before, after))
    assert handled, "edit thành chữ hoa không bị anti-caps xử lý"


def test_module_gate_for_pure_app_commands(monkeypatch, temp_db):
    class Response:
        def __init__(self):
            self.sent = []

        async def send_message(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    class Interaction:
        def __init__(self):
            self.guild = types.SimpleNamespace(id=1)
            self.response = Response()

    async def fake_enabled(guild_id, module):
        return False

    async def fake_settings(guild_id):
        return {}

    monkeypatch.setattr(tv, "async_is_module_enabled", fake_enabled)
    monkeypatch.setattr(tv, "async_get_guild_settings", fake_settings)
    monkeypatch.setattr(cc, "async_is_module_enabled", fake_enabled)
    monkeypatch.setattr(cc, "async_get_guild_settings", fake_settings)

    inter = Interaction()
    assert asyncio.run(tv.TempVoice.interaction_check(types.SimpleNamespace(), inter)) is False
    assert asyncio.run(cc.CustomCommands.interaction_check(types.SimpleNamespace(), inter)) is False
    assert len(inter.response.sent) == 2


def test_source_guards_for_payload_and_close_gate():
    assert "len(roles) > 20" in _read("bot/cogs/events.py")
    assert "async_is_module_enabled(str(guild.id), \"tickets\")" in _read("bot/cogs/ticket.py")
    assert "async_is_module_enabled" in _read("bot/cogs/reactionroles.py")
    assert "limit=100" in _read("bot/cogs/birthday.py")
    assert "len(desc) + len(line) > 3800" in _read("bot/cogs/economy.py")

"""P4-A — Blackjack được lưu DB: restart hoàn cược, settle idempotent."""
import asyncio
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_COGS = os.path.join(ROOT, "bot", "cogs")
sys.path.insert(0, _COGS)
try:
    import economy as eco  # noqa: E402
finally:
    sys.path.remove(_COGS)


def test_blackjack_game_persists_and_settles_once(temp_db):
    import database as db

    db.update_user_balance("g1", "u1", 0, 0)
    game_id = asyncio.run(db.async_create_blackjack_game(
        "g1", "u1", 100, ["A♠", "K♥"], ["9♣", "7♦"], ["5♠", "6♥"]))
    row = asyncio.run(db.async_get_blackjack_game(game_id))
    assert row and row["bet"] == 100 and row["status"] == "active"

    assert asyncio.run(db.async_update_blackjack_game(
        game_id, player_hand=["A♠", "K♥", "2♣"], deck=["6♥"])) is True
    assert asyncio.run(db.async_get_blackjack_game(game_id))["player_hand"] == ["A♠", "K♥", "2♣"]

    assert asyncio.run(db.async_settle_blackjack_game(
        game_id, "g1", "u1", 200, "win", "blackjack win")) is True
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["wallet"] == 200
    assert asyncio.run(db.async_get_blackjack_game(game_id)) is None

    # Gọi lại không được trả lần hai.
    assert asyncio.run(db.async_settle_blackjack_game(
        game_id, "g1", "u1", 200, "win", "blackjack win")) is False
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["wallet"] == 200


def test_stale_blackjack_games_are_refunded_on_startup(temp_db):
    import database as db

    db.update_user_balance("g1", "u1", 0, 0)
    asyncio.run(db.async_create_blackjack_game(
        "g1", "u1", 250, ["A♠", "K♥"], ["9♣", "7♦"], ["5♠", "6♥"]))

    assert asyncio.run(db.async_refund_stale_blackjack_games()) == 1
    assert asyncio.run(db.async_get_economy_user("g1", "u1"))["wallet"] == 250
    assert asyncio.run(db.async_refund_stale_blackjack_games()) == 0


def test_blackjack_embed_uses_economy_currency():
    ctx = types.SimpleNamespace(
        guild=types.SimpleNamespace(id="g1"),
        author=types.SimpleNamespace(id="u1", display_name="User"),
    )
    view = eco.BlackjackView(None, ctx, 10, {"language": "vi"}, eco_s={"currency_symbol": "💎"})
    embed = view.build_embed()
    assert "💎" in (embed.footer.text or "")


def test_owned_role_refund_helper_is_wired():
    src = open(os.path.join(ROOT, "bot", "cogs", "economy.py"), encoding="utf-8").read()
    assert 'tr(s, "economy.already_own_role", role=role.name)' in src
    assert "async_refund_shop_purchase(" in src

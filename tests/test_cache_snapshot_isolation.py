# -*- coding: utf-8 -*-
"""O2 — cache settings khong con bi "poisoning" boi mot lan mutate nham.

Bat bien: lay settings tu cache, ghi dung vao dict do, roi lay lai -> van gia tri goc.
Cache tra ve DUNG object luu tru, nen mot phep ghi nham o dau do sai toan bo server
suot TTL 30s, khong loi, khong log.
"""
import re
import time
from pathlib import Path

import pytest

import database
from cache import cache
from database import (
    async_get_custom_commands,
    async_get_guild_modules,
    async_get_guild_settings,
    async_get_logger_settings,
    get_guild_modules,
    get_guild_settings,
    get_leveling_settings,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _db(temp_db):
    database.init_db()
    cache.clear()
    yield


def test_sync_settings_survive_a_stray_write():
    first = get_guild_settings("g_o2")
    assert first["language"] == "vi"
    first["language"] = "zz"
    first["welcome_channel_id"] = 999

    assert get_guild_settings("g_o2")["language"] == "vi", "cache bi dau doc ngon ngu"
    assert get_guild_settings("g_o2")["welcome_channel_id"] is None


async def test_async_settings_survive_a_stray_write():
    got = await async_get_guild_settings("g_o2a")
    got["language"] = "de"
    again = await async_get_guild_settings("g_o2a")
    assert again["language"] == "vi", "async getter van tra object dung trong cache"


async def test_modules_dict_survive_a_stray_write():
    mods = get_guild_modules("g_o2m")
    mods["music"] = False
    assert get_guild_modules("g_o2m").get("music", True) is True

    amods = await async_get_guild_modules("g_o2m")
    amods["economy"] = False
    assert (await async_get_guild_modules("g_o2m")).get("economy", True) is True


def test_leveling_settings_survive_a_stray_write():
    s = get_leveling_settings("g_o2l")
    assert s["message_xp_min"] == 15
    s["message_xp_min"] = 9999
    assert get_leveling_settings("g_o2l")["message_xp_min"] == 15


async def test_logger_settings_survive_a_stray_write():
    s = await async_get_logger_settings("g_o2lg")
    s["mod_log_channel_id"] = 12345
    again = await async_get_logger_settings("g_o2lg")
    assert again.get("mod_log_channel_id") != 12345


async def test_custom_command_list_survive_mutation():
    rows = await async_get_custom_commands("g_o2c")
    assert isinstance(rows, list)
    rows.append({"name": "rac"})
    rows.clear()
    again = await async_get_custom_commands("g_o2c")
    assert isinstance(again, list), "phai tra ve list khac, khong phai object da bi clear"


def test_cache_get_returns_a_copy_not_the_live_object():
    from cache import cache
    cache.set("k_o2", {"a": 1})
    got = cache.get("k_o2")
    got["a"] = 999
    assert cache.get("k_o2")["a"] == 1


def test_mutating_source_after_set_does_not_change_the_cache():
    from cache import cache
    payload = {"language": "vi"}
    cache.set("k_o2b", payload)
    payload["language"] = "de"
    assert cache.get("k_o2b")["language"] == "vi", "cache phai nam ban cua rieng no"


def test_immutable_values_pass_through_unchanged():
    from cache import cache
    cache.set("k_o2c", "mot-chuoi")
    cache.set("k_o2d", 42)
    assert cache.get("k_o2c") == "mot-chuoi"
    assert cache.get("k_o2d") == 42


def test_snapshot_deep_copies_nested_containers():
    """Object lồng nhau cũng phải được cô lập (cache từng bị poison qua dict con)."""
    from cache import cache
    inner = {"n": 1}
    cache.set("k_o2e", [inner])
    got = cache.get("k_o2e")
    got.append({"x": 1})
    assert len(cache.get("k_o2e")) == 1, "list cấp ngoài phải được cô lập"
    got2 = cache.get("k_o2e")
    got2[0]["n"] = 5
    assert cache.get("k_o2e")[0]["n"] == 1, "dict lồng nhau vẫn chia sẻ object"

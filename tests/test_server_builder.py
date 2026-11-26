"""Tests cho Server Builder Studio: DB CRUD, Engine diff/ETA, Cog worker offline, va Dashboard API/XSS."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import types
from pathlib import Path

import discord
import pytest
from discord.ext import commands, tasks

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from conftest import MOCK_GUILD_ID, MOCK_USER_ID, authed_client, login, set_csrf_token  # noqa: E402


def _import_engine():
    try:
        import server_builder_engine as sbe
    except (ImportError, ModuleNotFoundError):
        from bot import server_builder_engine as sbe
    return sbe


def _import_cog_module(module_name: str = "server_builder"):
    cogs_dir = str(ROOT / "bot" / "cogs")
    inserted = False
    if cogs_dir not in sys.path:
        sys.path.insert(0, cogs_dir)
        inserted = True
    try:
        return __import__(module_name)
    finally:
        if inserted and cogs_dir in sys.path:
            sys.path.remove(cogs_dir)


# ---------------------------------------------------------------------------
# 1. Database schema & CRUD (temp_db isolated via set_db_path)
# ---------------------------------------------------------------------------

def test_schema_and_db_path_isolation(temp_db):
    import sqlite3
    import database as db

    real_db = ROOT / "data" / "bot.db"
    real_mtime = real_db.stat().st_mtime if real_db.exists() else None

    with sqlite3.connect(temp_db) as raw:
        tables = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "server_builder_jobs" in tables
    assert "server_builder_templates" in tables
    assert "idx_sb_jobs_guild_status" in indexes
    assert "idx_sb_templates_guild" in indexes

    job = db.create_server_builder_job("9001", "1001", {"operations": []}, {"safe_mode": True}, 0, 0.0)
    assert job["job_code"].startswith("SB-")
    assert job["status"] == "queued"

    if real_mtime is not None and real_db.exists():
        assert real_db.stat().st_mtime == real_mtime


def test_single_active_job_lock_and_atomic_claim(temp_db):
    import database as db

    job_a = db.create_server_builder_job("g_lock", "u1", {"operations": []}, {}, 2, 2.0)
    with pytest.raises(db.ActiveJobExistsError) as exc_info:
        db.create_server_builder_job("g_lock", "u2", {"operations": []}, {}, 1, 1.0)
    assert exc_info.value.job["id"] == job_a["id"]

    # Another guild can enqueue concurrently
    job_b = db.create_server_builder_job("g_other", "u1", {"operations": []}, {}, 1, 1.0)

    claimed_a = asyncio.run(db.async_claim_next_server_builder_job())
    assert claimed_a is not None and claimed_a["id"] == job_a["id"]
    assert claimed_a["status"] == "running"
    assert isinstance(claimed_a["plan"], dict)
    assert isinstance(claimed_a["options"], dict)

    # While guild g_lock has running job, claiming returns guild g_other
    claimed_b = asyncio.run(db.async_claim_next_server_builder_job())
    assert claimed_b is not None and claimed_b["id"] == job_b["id"]

    # No more queued jobs
    assert asyncio.run(db.async_claim_next_server_builder_job()) is None

    # Concurrent claimers only claim a single queued job once
    async def _double_claim():
        return await asyncio.gather(
            db.async_claim_next_server_builder_job(),
            db.async_claim_next_server_builder_job(),
        )

    job_race = db.create_server_builder_job("g_race", "u1", {"operations": []}, {}, 1, 1.0)
    r1, r2 = asyncio.run(_double_claim())
    winners = [r for r in (r1, r2) if r is not None]
    assert len(winners) == 1 and winners[0]["id"] == job_race["id"]

    # Complete g_lock job -> new job allowed again
    assert asyncio.run(
        db.async_update_server_builder_job(job_a["id"], expected_statuses=["running"], status="completed")
    )
    assert db.get_active_server_builder_job("g_lock") is None
    job_a2 = db.create_server_builder_job("g_lock", "u1", {"operations": []}, {}, 1, 1.0)
    assert job_a2["id"] != job_a["id"]


def test_job_update_whitelist_cancel_stale_and_idor(temp_db):
    import database as db

    with pytest.raises(ValueError):
        asyncio.run(db.async_update_server_builder_job(1, evil_col="1"))
    with pytest.raises(ValueError):
        asyncio.run(db.async_update_server_builder_job(1, status="bogus"))

    j_queued = db.create_server_builder_job("g1", "u1", {"operations": []}, {}, 3, 3.0)
    assert db.get_server_builder_job(j_queued["id"], guild_id="g_wrong") is None
    assert db.request_cancel_server_builder_job(j_queued["id"], "g_wrong") is False
    assert db.request_cancel_server_builder_job(j_queued["id"], "g1") is True
    cancelled = db.get_server_builder_job(j_queued["id"], guild_id="g1")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] == 1

    # Running + paused_rl stale recovery + running cancel flag
    j_run = db.create_server_builder_job("g1", "u1", {"operations": []}, {}, 3, 3.0)
    claimed = asyncio.run(db.async_claim_next_server_builder_job())
    assert claimed["id"] == j_run["id"]
    assert db.request_cancel_server_builder_job(j_run["id"], "g1") is True
    assert asyncio.run(db.async_is_server_builder_cancel_requested(j_run["id"])) is True

    j_rl = db.create_server_builder_job("g2", "u1", {"operations": []}, {}, 3, 3.0)
    asyncio.run(db.async_claim_next_server_builder_job())
    asyncio.run(db.async_update_server_builder_job(j_rl["id"], status="paused_rl", rate_limit_until=time.time() + 30))

    j_stay_queued = db.create_server_builder_job("g3", "u1", {"operations": []}, {}, 1, 1.0)

    recovered = asyncio.run(db.async_fail_stale_server_builder_jobs("Restarted"))
    assert recovered == 2
    assert db.get_server_builder_job(j_run["id"])["status"] == "failed"
    assert db.get_server_builder_job(j_rl["id"])["status"] == "failed"
    assert db.get_server_builder_job(j_rl["id"])["error_message"] == "Restarted"
    assert db.get_server_builder_job(j_stay_queued["id"])["status"] == "queued"
    assert len(db.list_server_builder_jobs("g1", limit=10)) == 2


def test_templates_limit_and_cross_guild_idor(temp_db):
    import database as db

    saved_ids = []
    for i in range(10):
        tpl = db.save_server_builder_template(
            "g_tpl",
            f"Template {i}",
            "Desc",
            {"categories": [], "uncategorized": []},
            "u1",
        )
        saved_ids.append(tpl["id"])

    with pytest.raises(db.TemplateLimitError):
        db.save_server_builder_template("g_tpl", "Template 11", "", {"categories": []}, "u1")

    # Different guild has independent quota
    other_tpl = db.save_server_builder_template("g_other", "Other", "", {"categories": []}, "u2")
    assert len(db.get_server_builder_templates("g_tpl")) == 10

    # Cross-guild / GLOBAL deletion blocked
    assert db.delete_server_builder_template(saved_ids[0], "g_other") is False
    assert db.delete_server_builder_template(saved_ids[0], "GLOBAL") is False
    assert db.delete_server_builder_template(saved_ids[0], "g_tpl") is True
    assert db.delete_server_builder_template(other_tpl["id"], "g_other") is True


# ---------------------------------------------------------------------------
# 2. Pure Python Server Builder Engine
# ---------------------------------------------------------------------------

def test_engine_sanitize_overwrites_and_presets():
    sbe = _import_engine()

    assert sbe.sanitize_channel_name("  Hello   World!! 🎉 ", sbe.CHANNEL_TYPE_TEXT) == "hello-world"
    assert sbe.sanitize_channel_name("My___News   Feed!!", sbe.CHANNEL_TYPE_ANNOUNCEMENT) == "my___news-feed"
    assert sbe.sanitize_channel_name("!!!", sbe.CHANNEL_TYPE_TEXT) == "channel"
    assert len(sbe.sanitize_channel_name("a" * 150, sbe.CHANNEL_TYPE_TEXT)) == 100

    assert sbe.sanitize_channel_name("  🔊 Học Tập\n\tRoom  ", sbe.CHANNEL_TYPE_VOICE) == "🔊 Học Tập Room"
    assert sbe.sanitize_channel_name("  📢 ANNOUNCEMENT  ", sbe.CHANNEL_TYPE_CATEGORY) == "📢 ANNOUNCEMENT"

    cat_ow = [
        {"id": "@everyone", "type": "role", "allow": ["view_channel", "read_message_history"], "deny": ["send_messages"]},
    ]
    ch_ow_same = [
        {"id": "@everyone", "type": "role", "allow": ["read_message_history", "view_channel"], "deny": ["send_messages"]},
    ]
    ch_ow_diff = [
        {"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": ["send_messages"]},
    ]
    assert sbe.is_overwrites_synced(cat_ow, ch_ow_same) is True
    assert sbe.is_overwrites_synced(cat_ow, ch_ow_diff) is False

    presets = sbe.get_system_presets()
    assert [p["id"] for p in presets] == ["community_4cat", "gaming_squad", "study_class", "creator_community"]
    c4 = presets[0]["tree"]
    assert len(c4["categories"]) == 4
    assert {"welcome", "verify", "music", "tickets", "bot_logs"} <= set(c4["bindings"].keys())


def test_engine_validate_tree_limits_and_warnings():
    sbe = _import_engine()

    # Exact boundary: 50 children passes, 51 fails
    exact_cat = {
        "categories": [{"name": "Max50", "channels": [{"name": f"c-{i}", "type": 0} for i in range(50)]}]
    }
    assert sbe.validate_tree_limits(exact_cat)["ok"] is True

    over_cat = {
        "categories": [{"name": "Big", "channels": [{"name": f"c-{i}", "type": 0} for i in range(51)]}]
    }
    res_cat = sbe.validate_tree_limits(over_cat)
    assert res_cat["ok"] is False
    assert any("50" in e for e in res_cat["errors"])

    # Exact boundary: 500 total channels (incl. categories + uncategorized) passes, 501 fails
    exact_500 = {
        "categories": [
            {"name": f"Cat {c}", "channels": [{"name": f"c-{c}-{i}", "type": 0} for i in range(49)]}
            for c in range(10)
        ]  # 10 categories + 490 children = 500
    }
    assert sbe.validate_tree_limits(exact_500)["ok"] is True
    over_500_uncat = {**exact_500, "uncategorized": [{"name": "extra", "type": 0}]}
    res_total = sbe.validate_tree_limits(over_500_uncat)
    assert res_total["ok"] is False
    assert any("500" in e for e in res_total["errors"])

    # Malformed non-dict payload rejected cleanly
    assert sbe.validate_tree_limits(["bad"])["ok"] is False

    # Role hierarchy + bot view deny warnings
    warn_tree = {
        "roles": [{"id": "555", "name": "Ownerish", "position": 10}],
        "categories": [
            {
                "name": "Private",
                "overwrites": [
                    {"id": "555", "type": "role", "allow": ["view_channel"], "deny": []},
                    {"id": "999", "type": "role", "allow": [], "deny": ["view_channel"]},
                ],
                "channels": [],
            }
        ],
    }
    res_warn = sbe.validate_tree_limits(
        warn_tree, bot_top_role_pos=5, bot_role_ids=["999"], bot_user_id="888"
    )
    assert res_warn["ok"] is True
    assert len(res_warn["warnings"]) >= 2


def test_engine_compute_diff_phases_safe_mode_deletions_and_eta():
    sbe = _import_engine()

    current = {
        "roles": [],
        "categories": [
            {
                "id": "cat1",
                "name": "OLD CAT",
                "position": 0,
                "overwrites": [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}],
                "channels": [
                    {"id": "ch1", "name": "general", "type": 0, "position": 0, "topic": "", "slowmode": 0, "nsfw": False, "overwrites": [], "sync_permissions": False},
                    {"id": "ch_old", "name": "legacy-room", "type": 0, "position": 1, "topic": "", "slowmode": 0, "nsfw": False, "overwrites": []},
                ],
            },
            {
                "id": "cat_old",
                "name": "UNUSED CAT",
                "position": 1,
                "overwrites": [],
                "channels": [],
            },
        ],
        "uncategorized": [],
    }
    target = {
        "roles": [{"temp_id": "r_new", "name": "Mod", "color": "#3498DB", "position": 1}],
        "categories": [
            {
                "temp_id": "cat_keep",
                "id": "cat1",
                "name": "NEW CAT",
                "position": 0,
                "overwrites": [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}],
                "channels": [
                    {"id": "ch1", "name": "chat-chung", "type": 0, "position": 0, "topic": "Updated", "slowmode": 5, "nsfw": False, "sync_permissions": True, "overwrites": []},
                    {"temp_id": "ch_new", "name": "Welcome Gate", "type": 0, "position": 1, "sync_permissions": True, "overwrites": [], "bind_module": "welcome"},
                ],
            }
        ],
        "uncategorized": [],
        "bindings": {"welcome": "ch_new"},
    }

    # 1. Safe Mode ON protects old channels/categories
    safe_diff = sbe.compute_diff(current, target, safe_mode=True, confirm_deletions=False)
    assert safe_diff["summary"]["has_deletions"] is False
    assert safe_diff["summary"]["protected_deletions"] == 2
    assert safe_diff["summary"]["rename_warning"] is True
    assert all(op["op"] not in ("delete_channel", "delete_category") for op in safe_diff["operations"])

    # 2. Safe Mode OFF without confirm_deletions flags has_deletions=True but emits 0 delete ops
    unconfirmed = sbe.compute_diff(current, target, safe_mode=False, confirm_deletions=False)
    assert unconfirmed["summary"]["has_deletions"] is True
    assert len(unconfirmed["summary"]["delete_targets"]) == 2
    assert unconfirmed["summary"]["delete_channels"] == 0
    assert unconfirmed["summary"]["delete_categories"] == 0

    # 3. Safe Mode OFF + confirm_deletions=True deletes children before categories and preserves phase order
    confirmed = sbe.compute_diff(current, target, safe_mode=False, confirm_deletions=True)
    ops = [op["op"] for op in confirmed["operations"]]
    assert "create_role" in ops
    assert "create_channel" in ops
    assert "sync_permissions" in ops
    assert "update_channel" in ops
    assert "bulk_reorder" in ops
    assert "delete_channel" in ops and "delete_category" in ops
    assert ops[-1] == "bind_modules"
    assert ops.index("create_role") < ops.index("create_channel")
    assert ops.index("create_channel") < ops.index("sync_permissions")
    assert ops.index("sync_permissions") < ops.index("update_channel")
    assert ops.index("update_channel") < ops.index("bulk_reorder")
    assert ops.index("bulk_reorder") < ops.index("delete_channel")
    assert ops.index("delete_channel") < ops.index("delete_category")
    assert ops.index("delete_category") < ops.index("bind_modules")

    # 4. recalibrate_eta EMA 0.7 * actual + 0.3 * baseline + rate_limit_until
    eta, ema = sbe.recalibrate_eta(
        completed_steps=2,
        elapsed_seconds=4.0,
        remaining_baseline_cost=5.0,
        prev_avg=1.0,
        rate_limit_until=110.0,
        now=100.0,
    )
    assert ema == pytest.approx(1.7, rel=1e-4)  # 0.7 * (4/2) + 0.3 * 1.0 = 1.7
    assert eta == pytest.approx(5.0 * 1.7 + 10.0, rel=1e-4)


def test_engine_bind_module_sentinels_and_channel_overrides():
    sbe = _import_engine()

    live = {
        "roles": [],
        "categories": [
            {
                "id": "cat1",
                "name": "INFO",
                "position": 0,
                "overwrites": [],
                "channels": [
                    {
                        "id": "ch1",
                        "name": "rules",
                        "type": 0,
                        "position": 0,
                        "topic": "",
                        "slowmode": 0,
                        "nsfw": False,
                        "overwrites": [],
                        "sync_permissions": True,
                    },
                    {
                        "id": "ch2",
                        "name": "welcome",
                        "type": 0,
                        "position": 1,
                        "topic": "",
                        "slowmode": 0,
                        "nsfw": False,
                        "overwrites": [],
                        "sync_permissions": True,
                    },
                ],
            }
        ],
        "uncategorized": [],
    }

    # Unbound sentinels ("none", "", None) on unmodified tree emit 0 operations
    unmodified = json.loads(json.dumps(live))
    unmodified["categories"][0]["channels"][0]["bind_module"] = "none"
    unmodified["categories"][0]["channels"][1]["bind_module"] = None
    unmodified["bindings"] = {"welcome": "none", "music": ""}
    diff_clean = sbe.compute_diff(live, unmodified, safe_mode=True)
    assert diff_clean["summary"]["bind_modules"] is False
    assert diff_clean["summary"]["total_operations"] == 0

    # Channel-level unbind ("none") clears stale target_tree["bindings"], while explicit bind wins
    override = json.loads(json.dumps(live))
    override["categories"][0]["channels"][0]["bind_module"] = "none"
    override["categories"][0]["channels"][1]["bind_module"] = "welcome"
    override["bindings"] = {"welcome": "ch1", "verify": "ch1"}
    diff_override = sbe.compute_diff(live, override, safe_mode=True)
    bind_ops = [op for op in diff_override["operations"] if op["op"] == "bind_modules"]
    assert len(bind_ops) == 1
    assert bind_ops[0]["bindings"] == {"welcome": "ch2"}

    # Preset community_4cat retains role_mod in compute_diff
    c4 = next(p for p in sbe.get_system_presets() if p["id"] == "community_4cat")["tree"]
    diff_preset = sbe.compute_diff({}, c4, safe_mode=True)
    role_ops = [op for op in diff_preset["operations"] if op["op"] == "create_role"]
    assert any(op["temp_id"] == "role_mod" and op["name"] == "Moderator" for op in role_ops)


def test_engine_import_live_tree_is_idempotent_for_decorated_names():
    sbe = _import_engine()

    live = {
        "roles": [],
        "categories": [
            {
                "id": "cat1",
                "name": "📌・THÔNG TIN & ĐỒNG BỘ",
                "position": 0,
                "overwrites": [],
                "channels": [
                    {"id": "ch1", "name": "🚪・gate", "type": 0, "position": 0, "topic": "", "slowmode": 0, "nsfw": False, "overwrites": [], "sync_permissions": True},
                    {"id": "ch2", "name": "📢・thông-báo", "type": 0, "position": 1, "topic": "tin tức", "slowmode": 0, "nsfw": False, "overwrites": [], "sync_permissions": True},
                ],
            }
        ],
        "uncategorized": [],
    }

    # "Tải lên từ Server thật" gửi lại cây live không đổi: tên có emoji/・ sanitize ra slug khác
    # nhưng người dùng chưa sửa gì -> phải là 0 thao tác (không còn rename ảo).
    imported = json.loads(json.dumps(live))
    diff_import = sbe.compute_diff(live, imported, safe_mode=True)
    assert diff_import["summary"]["total_operations"] == 0
    assert diff_import["summary"]["renames"] == 0
    assert diff_import["summary"]["rename_warning"] is False

    # Sửa tên thật thì vẫn phát hiện đúng 1 op rename với tên đã sanitize.
    edited = json.loads(json.dumps(live))
    edited["categories"][0]["channels"][0]["name"] = "Cổng Vào"
    diff_edit = sbe.compute_diff(live, edited, safe_mode=True)
    updates = [op for op in diff_edit["operations"] if op["op"] == "update_channel"]
    assert len(updates) == 1
    assert updates[0]["changes"]["name"] == "cổng-vào"
    assert updates[0]["old_name"] == "🚪・gate"


def test_engine_unchanged_current_bindings_emit_no_bind_op():
    sbe = _import_engine()

    def _channel(cid, name, position, bind_module=None):
        return {
            "id": cid, "name": name, "type": 0, "position": position, "topic": "",
            "slowmode": 0, "nsfw": False, "overwrites": [], "sync_permissions": True,
            "bind_module": bind_module,
        }

    live = {
        "roles": [],
        "categories": [
            {
                "id": "cat1",
                "name": "INFO",
                "position": 0,
                "overwrites": [],
                "channels": [
                    _channel("ch1", "welcome", 0, "welcome"),
                    _channel("ch2", "welcome-2", 1),
                ],
            }
        ],
        "uncategorized": [],
        "bindings": {"welcome": "ch1", "verify": None},
    }

    # 1. Cây import không đổi (bindings hiện tại trùng target) -> không còn bind op ảo
    same = json.loads(json.dumps(live))
    diff_same = sbe.compute_diff(live, same, safe_mode=True)
    assert diff_same["summary"]["bind_modules"] is False
    assert diff_same["summary"]["total_operations"] == 0

    # 2. Chuyển bind sang kênh khác vẫn sinh đúng 1 bind op
    moved = json.loads(json.dumps(live))
    moved["categories"][0]["channels"][0]["bind_module"] = "none"
    moved["categories"][0]["channels"][1]["bind_module"] = "welcome"
    moved["bindings"] = {"welcome": "ch2"}
    diff_moved = sbe.compute_diff(live, moved, safe_mode=True)
    bind_ops = [op for op in diff_moved["operations"] if op["op"] == "bind_modules"]
    assert len(bind_ops) == 1
    assert bind_ops[0]["bindings"] == {"welcome": "ch2"}
    assert diff_moved["summary"]["total_operations"] == 1


def test_engine_roles_idempotency_everyone_and_presets():
    sbe = _import_engine()

    # 1. 52-bit permission registry & unknown bit_60 roundtrip
    assert len(sbe.PERMISSION_BITS) == 52
    bits = (1 << 25) | (1 << 30) | (1 << 43) | (1 << 48) | (1 << 51) | (1 << 52) | (1 << 60)
    expected_flags = sorted([
        "use_vad",
        "manage_guild_expressions",
        "create_guild_expressions",
        "set_voice_channel_status",
        "pin_messages",
        "bypass_slowmode",
        "bit_60",
    ])
    assert sbe.normalize_role_permissions(bits) == expected_flags
    assert sbe.normalize_role_permissions(str(bits)) == expected_flags
    assert sbe.permissions_to_bitfield(expected_flags) == bits
    assert sbe.normalize_role_permissions([
        "use_voice_activation",
        "manage_expressions",
        "create_expressions",
        "read_messages",
        "bit_60",
    ]) == sorted([
        "use_vad",
        "manage_guild_expressions",
        "create_guild_expressions",
        "view_channel",
        "bit_60",
    ])

    # 2. #99aab5 <-> 0 color normalization
    for default_val in (0, "0", "#000000", "#000", "", None, "99aab5", "#99AAB5"):
        assert sbe.normalize_role_color(default_val) == "#99aab5"
    assert sbe.normalize_role_color(0x3498DB) == "#3498db"
    assert sbe.normalize_role_color("#abc") == "#aabbcc"

    # 3. Live-import 0-op idempotency (@everyone, managed, >= bot_top_role_pos, bound roles)
    live = {
        "roles": [
            {
                "id": "@everyone",
                "name": "@everyone",
                "color": "#000000",
                "position": 0,
                "hoist": False,
                "mentionable": False,
                "managed": False,
                "is_everyone": True,
                "permissions": ["view_channel", "send_messages"],
            },
            {
                "id": "4001",
                "name": "ZerynBot",
                "color": 0,
                "position": 8,
                "hoist": False,
                "mentionable": False,
                "managed": True,
                "is_everyone": False,
                "permissions": ["administrator"],
            },
            {
                "id": "4002",
                "name": "CoOwner",
                "color": "#e74c3c",
                "position": 12,
                "hoist": True,
                "mentionable": False,
                "managed": False,
                "is_everyone": False,
                "permissions": ["administrator"],
            },
            {
                "id": "4004",
                "name": "VIP",
                "color": "#f1c40f",
                "position": 4,
                "hoist": True,
                "mentionable": True,
                "managed": False,
                "is_everyone": False,
                "permissions": ["view_channel", "priority_speaker"],
            },
            {
                "id": "4003",
                "name": "Member",
                "color": 0,
                "position": 2,
                "hoist": False,
                "mentionable": False,
                "managed": False,
                "is_everyone": False,
                "permissions": ["view_channel", "use_vad"],
                "bind_role_module": "autoroles_user",
            },
        ],
        "categories": [],
        "uncategorized": [],
        "bindings": {"autoroles_user": "4003"},
    }
    imported = json.loads(json.dumps(live))
    imported["roles"][0]["color"] = 0
    imported["roles"][4]["color"] = "#99aab5"
    diff_idem = sbe.compute_diff(live, imported, safe_mode=True, bot_top_role_pos=10)
    assert diff_idem["errors"] == []
    assert diff_idem["summary"]["total_operations"] == 0

    # Managed role edit skipped with warning; omitting @everyone/managed/>=bot_top never deletes them
    managed_edit = json.loads(json.dumps(live))
    managed_edit["roles"][1]["name"] = "RenamedBot"
    managed_edit["roles"][1]["permissions"] = ["view_channel"]
    diff_managed = sbe.compute_diff(live, managed_edit, safe_mode=True, bot_top_role_pos=10)
    assert diff_managed["summary"]["total_operations"] == 0
    assert any("Managed role" in w for w in diff_managed["warnings"])

    omit_locked = json.loads(json.dumps(live))
    omit_locked["roles"] = [r for r in omit_locked["roles"] if r["id"] in ("4003", "4004")]
    diff_omit_locked = sbe.compute_diff(
        live, omit_locked, safe_mode=False, confirm_deletions=True, bot_top_role_pos=10
    )
    assert diff_omit_locked["summary"]["delete_roles"] == 0
    assert any("cannot be deleted" in w for w in diff_omit_locked["warnings"])

    # 4. @everyone permissions-only edit (non-perm changes ignored, renames == 0)
    ev_non_perm_only = json.loads(json.dumps(live))
    ev_non_perm_only["roles"][0].update({
        "name": "NotEveryone",
        "color": "#ff0000",
        "hoist": True,
        "mentionable": True,
        "position": 5,
    })
    diff_ev_noop = sbe.compute_diff(live, ev_non_perm_only, safe_mode=True, bot_top_role_pos=10)
    assert diff_ev_noop["summary"]["total_operations"] == 0
    assert diff_ev_noop["summary"]["renames"] == 0

    ev_perm_edit = json.loads(json.dumps(ev_non_perm_only))
    ev_perm_edit["roles"][0]["permissions"] = ["view_channel", "send_messages", "embed_links"]
    diff_ev = sbe.compute_diff(live, ev_perm_edit, safe_mode=True, bot_top_role_pos=10)
    assert diff_ev["summary"]["total_operations"] == 1
    assert diff_ev["summary"]["update_roles"] == 1
    assert diff_ev["summary"]["renames"] == 0
    assert diff_ev["summary"]["bulk_reorder_roles"] is False
    ev_op = diff_ev["operations"][0]
    assert ev_op["op"] == "update_role"
    assert ev_op["role_id"] == "@everyone"
    assert ev_op["is_everyone"] is True
    assert set(ev_op["changes"].keys()) == {"permissions", "permissions_bitfield"}
    assert ev_op["changes"]["permissions"] == ["embed_links", "send_messages", "view_channel"]

    # 5. update_role + single batch bulk_reorder_roles + create_role defer_position
    edit_and_reorder = json.loads(json.dumps(live))
    edit_and_reorder["roles"][3].update({
        "name": "Super VIP",
        "color": "#2ecc71",
        "hoist": False,
        "mentionable": False,
        "permissions": ["view_channel", "priority_speaker", "pin_messages"],
        "position": 1,
    })
    edit_and_reorder["roles"][4]["position"] = 4
    edit_and_reorder["roles"].append({
        "temp_id": "r_helper",
        "name": "Helper",
        "color": "#3498db",
        "position": 3,
        "permissions": ["view_channel", "bypass_slowmode"],
    })
    diff_reorder = sbe.compute_diff(live, edit_and_reorder, safe_mode=True, bot_top_role_pos=10)
    assert diff_reorder["errors"] == []
    assert diff_reorder["summary"]["create_roles"] == 1
    assert diff_reorder["summary"]["update_roles"] == 1
    assert diff_reorder["summary"]["bulk_reorder_roles"] is True
    assert diff_reorder["summary"]["reorder_roles"] is True
    op_names = [op["op"] for op in diff_reorder["operations"]]
    assert op_names.count("bulk_reorder_roles") == 1
    assert op_names.index("create_role") < op_names.index("update_role") < op_names.index("bulk_reorder_roles")
    create_op = next(op for op in diff_reorder["operations"] if op["op"] == "create_role")
    assert create_op["defer_position"] is True
    reorder_op = next(op for op in diff_reorder["operations"] if op["op"] == "bulk_reorder_roles")
    reorder_refs = {item["id"] or item["temp_id"] for item in reorder_op["items"]}
    assert reorder_refs == {"4003", "4004", "r_helper"}

    # 6. delete_role gated by safe_mode=False & confirm_deletions=True + protected_role_ids
    del_target = json.loads(json.dumps(live))
    del_target["roles"] = [r for r in del_target["roles"] if r["id"] not in ("4003", "4004")]
    del_target["bindings"] = {}

    diff_safe_del = sbe.compute_diff(live, del_target, safe_mode=True, confirm_deletions=True, bot_top_role_pos=10)
    assert diff_safe_del["summary"]["has_deletions"] is False
    assert diff_safe_del["summary"]["delete_roles"] == 0
    assert diff_safe_del["summary"]["protected_deletions"] == 2

    diff_unconf_del = sbe.compute_diff(live, del_target, safe_mode=False, confirm_deletions=False, bot_top_role_pos=10)
    assert diff_unconf_del["summary"]["has_deletions"] is True
    assert diff_unconf_del["summary"]["delete_roles"] == 0
    assert {t["id"] for t in diff_unconf_del["summary"]["delete_targets"]} == {"4003", "4004"}

    diff_prot_del = sbe.compute_diff(
        live,
        del_target,
        safe_mode=False,
        confirm_deletions=True,
        bot_top_role_pos=10,
        protected_role_ids={"4003"},
    )
    assert diff_prot_del["summary"]["delete_roles"] == 1
    assert diff_prot_del["summary"]["protected_deletions"] == 1
    assert [op["role_id"] for op in diff_prot_del["operations"] if op["op"] == "delete_role"] == ["4004"]
    assert any("Protected role" in w for w in diff_prot_del["warnings"])

    # 7. live_source="cache" and _cache_readonly wipe protection
    diff_cache = sbe.compute_diff(
        live,
        edit_and_reorder,
        safe_mode=False,
        confirm_deletions=True,
        bot_top_role_pos=10,
        live_source="cache",
    )
    assert all(op["op"] not in ("update_role", "delete_role", "bulk_reorder_roles") for op in diff_cache["operations"])
    assert any("Offline SQLite cache mode" in w for w in diff_cache["warnings"])

    live_ro = json.loads(json.dumps(live))
    live_ro["roles"][3]["_cache_readonly"] = True  # 4004
    diff_ro = sbe.compute_diff(
        live_ro, del_target, safe_mode=False, confirm_deletions=True, bot_top_role_pos=10
    )
    assert [op["role_id"] for op in diff_ro["operations"] if op["op"] == "delete_role"] == ["4003"]
    assert any("Offline SQLite cache mode" in w for w in diff_ro["warnings"])

    # 8. user_role_hierarchy_denied check
    diff_hier_edit = sbe.compute_diff(
        live,
        edit_and_reorder,
        safe_mode=True,
        bot_top_role_pos=10,
        is_guild_owner=False,
        user_top_role_pos=4,
    )
    assert diff_hier_edit["operations"] == []
    assert any("user_role_hierarchy_denied" in e for e in diff_hier_edit["errors"])

    diff_hier_del = sbe.compute_diff(
        live,
        del_target,
        safe_mode=False,
        confirm_deletions=True,
        bot_top_role_pos=10,
        is_guild_owner=False,
        user_top_role_pos=4,
    )
    assert diff_hier_del["operations"] == []
    assert any("user_role_hierarchy_denied" in e for e in diff_hier_del["errors"])

    # 9. Safe Mode MAX_GUILD_ROLES = 250 boundary
    roles_250 = [{"temp_id": f"r_{i}", "name": f"R{i}", "position": 1} for i in range(sbe.MAX_GUILD_ROLES)]
    assert sbe.validate_tree_limits({"roles": roles_250})["ok"] is True
    roles_251 = [{"temp_id": f"r_{i}", "name": f"R{i}", "position": 1} for i in range(sbe.MAX_GUILD_ROLES + 1)]
    res_251 = sbe.validate_tree_limits({"roles": roles_251})
    assert res_251["ok"] is False and any("250" in e for e in res_251["errors"])

    curr_248 = {
        "roles": [{"id": f"90{i}", "name": f"Live{i}", "position": 1} for i in range(248)],
        "categories": [],
        "uncategorized": [],
    }
    tgt_250 = {
        "roles": curr_248["roles"] + [
            {"temp_id": "new_1", "name": "New1", "position": 1},
            {"temp_id": "new_2", "name": "New2", "position": 1},
        ],
        "categories": [],
        "uncategorized": [],
    }
    assert sbe.compute_diff(curr_248, tgt_250, safe_mode=True)["errors"] == []
    tgt_over_250 = {
        "roles": tgt_250["roles"] + [{"temp_id": "new_3", "name": "New3", "position": 1}],
        "categories": [],
        "uncategorized": [],
    }
    diff_over_250 = sbe.compute_diff(curr_248, tgt_over_250, safe_mode=True)
    assert any("250" in e for e in diff_over_250["errors"])

    # 10. Explicit role unbinds vs partial roles: [] tree
    curr_bound = {
        "roles": [
            {"id": "@everyone", "name": "@everyone", "position": 0, "is_everyone": True, "permissions": []},
            {"id": "4003", "name": "Member", "position": 2, "color": 0, "permissions": [], "bind_role_module": "autoroles_user"},
            {"id": "4004", "name": "Verified", "position": 3, "color": 0, "permissions": [], "bind_role_module": "verify_verified"},
        ],
        "categories": [],
        "uncategorized": [],
        "bindings": {"autoroles_user": "4003", "verify_verified": "4004"},
    }
    diff_partial = sbe.compute_diff(
        curr_bound,
        {"roles": [], "categories": [], "uncategorized": []},
        safe_mode=True,
    )
    assert diff_partial["summary"]["bind_modules"] is False
    assert diff_partial["summary"]["total_operations"] == 0

    explicit_unbind_target = json.loads(json.dumps(curr_bound))
    explicit_unbind_target["roles"][1]["bind_role_module"] = None
    explicit_unbind_target["bindings"] = {"verify_verified": "4004"}
    diff_unbind = sbe.compute_diff(curr_bound, explicit_unbind_target, safe_mode=True)
    bind_unbind_ops = [op for op in diff_unbind["operations"] if op["op"] == "bind_modules"]
    assert len(bind_unbind_ops) == 1
    assert bind_unbind_ops[0]["bindings"]["autoroles_user"] is None
    assert bind_unbind_ops[0]["bindings"]["verify_verified"] == "4004"

    # 11. All 4 enriched SYSTEM_PRESETS
    presets = sbe.get_system_presets()
    assert [p["id"] for p in presets] == ["community_4cat", "gaming_squad", "study_class", "creator_community"]
    for preset in presets:
        ptree = preset["tree"]
        assert len(ptree["roles"]) >= 3
        assert sbe.validate_tree_limits(ptree)["ok"] is True, preset["id"]
        role_temp_ids = {r["temp_id"] for r in ptree["roles"]}
        assert ptree["bindings"].get("automod_immune") in role_temp_ids
        assert ptree["bindings"].get("autoroles_user") in role_temp_ids
        pdiff = sbe.compute_diff({}, ptree, safe_mode=True)
        assert pdiff["errors"] == [], (preset["id"], pdiff["errors"])
        assert pdiff["summary"]["create_roles"] == len(ptree["roles"])
        assert pdiff["summary"]["bulk_reorder_roles"] is True
        assert pdiff["summary"]["bind_modules"] is True


# ---------------------------------------------------------------------------
# 3. Offline Cog Worker (Fake Discord Guild/Channel/Role harness)
# ---------------------------------------------------------------------------

class FakeRole:
    def __init__(
        self,
        rid: int,
        name: str,
        position: int = 1,
        default: bool = False,
        *,
        colour=None,
        color=None,
        permissions=None,
        hoist: bool = False,
        mentionable: bool = False,
        managed: bool = False,
        guild=None,
    ):
        self.id = rid
        self.name = name
        self.position = position
        resolved_color = colour if colour is not None else color
        self.color = resolved_color if resolved_color is not None else discord.Color.default()
        self.colour = self.color
        if isinstance(permissions, discord.Permissions):
            self.permissions = permissions
        elif isinstance(permissions, int):
            self.permissions = discord.Permissions(permissions)
        else:
            self.permissions = discord.Permissions.none()
        self.hoist = hoist
        self.mentionable = mentionable
        self.managed = managed
        self.guild = guild
        self._default = default
        self.edit_calls = []
        self.delete_calls = []
        self.deleted = False

    def is_default(self):
        return self._default

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "position" in kwargs:
            self.position = kwargs["position"]
        if "colour" in kwargs or "color" in kwargs:
            c = kwargs.get("colour", kwargs.get("color"))
            self.color = c
            self.colour = c
        if "permissions" in kwargs:
            self.permissions = kwargs["permissions"]
        if "hoist" in kwargs:
            self.hoist = bool(kwargs["hoist"])
        if "mentionable" in kwargs:
            self.mentionable = bool(kwargs["mentionable"])

    async def delete(self, **kwargs):
        self.delete_calls.append(kwargs)
        self.deleted = True
        if self.guild is not None and self in self.guild.roles:
            self.guild.roles.remove(self)


class FakeChannel:
    def __init__(self, cid: int, name: str, ctype: int, guild, category=None, position: int = 0, overwrites=None, **extra):
        self.id = cid
        self.name = name
        self.type = types.SimpleNamespace(value=ctype)
        self.guild = guild
        self.category = category
        self.category_id = category.id if category else None
        self.position = position
        self.overwrites = dict(overwrites or {})
        self.topic = extra.get("topic", "")
        self.slowmode_delay = extra.get("slowmode_delay", 0)
        self.nsfw = extra.get("nsfw", False)
        self.bitrate = extra.get("bitrate", 64000)
        self.user_limit = extra.get("user_limit", 0)
        self.news = extra.get("news", ctype == 5)
        self.edits = []
        self.sent = []
        self.deleted = False
        self.set_perm_calls = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "topic" in kwargs:
            self.topic = kwargs["topic"]
        if "slowmode_delay" in kwargs:
            self.slowmode_delay = kwargs["slowmode_delay"]
        if "overwrites" in kwargs:
            self.overwrites = dict(kwargs["overwrites"])

    async def delete(self, **kwargs):
        self.deleted = True

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    async def set_permissions(self, target, overwrite=None, **kwargs):
        self.set_perm_calls.append((target, overwrite, kwargs))
        if overwrite is not None:
            self.overwrites[target] = overwrite


class FakeCategory(FakeChannel):
    def __init__(self, cid: int, name: str, guild, position: int = 0, overwrites=None):
        super().__init__(cid, name, 4, guild, category=None, position=position, overwrites=overwrites)


class FakeHTTP:
    def __init__(self):
        self.bulk_calls = []
        self.move_role_calls = []
        self.channel_edit_calls = []

    async def bulk_channel_update(self, guild_id, payload, reason=None):
        self.bulk_calls.append((guild_id, payload, reason))

    async def edit_channel(self, channel_id, **kwargs):
        self.channel_edit_calls.append((channel_id, kwargs))

    async def move_role_position(self, guild_id, payload, reason=None):
        self.move_role_calls.append((guild_id, payload, reason))


class FakeGuild:
    def __init__(
        self,
        gid: int = 999999999999999999,
        features=(),
        bitrate_limit=96000,
        bot_top_pos=50,
        owner_id: int = 1,
    ):
        self.id = gid
        self.name = "Fake Guild"
        self.icon = None
        self.owner_id = owner_id
        self.features = tuple(features)
        self.bitrate_limit = bitrate_limit
        self.default_role = FakeRole(gid, "@everyone", position=0, default=True, guild=self)
        self.me = types.SimpleNamespace(top_role=FakeRole(888, "ZerynBot", position=bot_top_pos, managed=True, guild=self))
        self.roles = [self.default_role]
        self.categories = []
        self.channels = []
        self.text_channels = []
        self._members = {}
        self._audit_entries = []
        self.banned_users = []
        self._next_id = 1000
        self._state = types.SimpleNamespace(http=FakeHTTP())

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_member(self, uid):
        return self._members.get(uid)

    def get_channel(self, cid):
        for cat in self.categories:
            if cat.id == cid:
                return cat
        return next((c for c in self.channels if c.id == cid), None)

    async def ban(self, user, **kwargs):
        self.banned_users.append((user, kwargs))

    async def audit_logs(self, limit=10, action=None):
        count = 0
        for entry in self._audit_entries:
            if action is None or getattr(entry, "action", None) == action:
                yield entry
                count += 1
                if count >= limit:
                    break

    def _alloc(self):
        self._next_id += 1
        return self._next_id

    async def create_role(self, **kwargs):
        r = FakeRole(
            self._alloc(),
            kwargs["name"],
            position=1,
            colour=kwargs.get("colour", kwargs.get("color")),
            permissions=kwargs.get("permissions"),
            hoist=bool(kwargs.get("hoist", False)),
            mentionable=bool(kwargs.get("mentionable", False)),
            guild=self,
        )
        if self.me.top_role.position <= 1:
            self.me.top_role.position += 1
        self.roles.append(r)
        return r

    async def create_category(self, **kwargs):
        cat = FakeCategory(
            self._alloc(),
            kwargs["name"],
            self,
            position=kwargs.get("position", 0),
            overwrites=kwargs.get("overwrites"),
        )
        self.categories.append(cat)
        self.channels.append(cat)
        return cat

    async def create_text_channel(self, **kwargs):
        is_news = bool(kwargs.get("news", False))
        ch = FakeChannel(
            self._alloc(),
            kwargs["name"],
            5 if is_news else 0,
            self,
            category=kwargs.get("category"),
            position=kwargs.get("position", 0),
            overwrites=kwargs.get("overwrites"),
            topic=kwargs.get("topic", ""),
            slowmode_delay=kwargs.get("slowmode_delay", 0),
            nsfw=kwargs.get("nsfw", False),
            news=is_news,
        )
        self.channels.append(ch)
        self.text_channels.append(ch)
        return ch

    async def create_voice_channel(self, **kwargs):
        ch = FakeChannel(
            self._alloc(),
            kwargs["name"],
            2,
            self,
            category=kwargs.get("category"),
            position=kwargs.get("position", 0),
            overwrites=kwargs.get("overwrites"),
            bitrate=kwargs.get("bitrate", 64000),
            user_limit=kwargs.get("user_limit", 0),
        )
        self.channels.append(ch)
        return ch


class BatchReorderGuild(FakeGuild):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role_position_calls = []

    async def edit_role_positions(self, *, positions, reason=None):
        self.role_position_calls.append((dict(positions), reason))
        for role, pos in positions.items():
            role.position = pos


def _new_cog(guild):
    sb_cog = _import_cog_module()
    cog = sb_cog.ServerBuilder.__new__(sb_cog.ServerBuilder)
    cog.bot = types.SimpleNamespace(get_guild=lambda gid: guild if int(gid) == guild.id else None)
    cog._stale_recovered = False
    from collections import defaultdict, deque
    cog._guild_locks = defaultdict(asyncio.Lock)
    cog._rename_history = defaultdict(deque)
    return sb_cog, cog


def test_cog_executes_4cat_preset_verify_gate_fallback_and_bindings(temp_db):
    import database as db
    sbe = _import_engine()

    guild = FakeGuild(features=(), bitrate_limit=96000)  # non-COMMUNITY -> type 5 falls back to 0
    pending_role = FakeRole(5001, "Unverified", position=1)
    guild.roles.append(pending_role)
    db.upsert_guild(str(guild.id), language="en")
    db.upsert_verify_settings(str(guild.id), enabled=1, hide_channels=1, pending_role_id="5001")

    preset = next(p for p in sbe.get_system_presets() if p["id"] == "community_4cat")["tree"]
    # Mark gate channel as verify binding too so we verify Verify Gate exemption
    preset["bindings"]["verify"] = "ch_gate"
    diff = sbe.compute_diff({}, preset, safe_mode=True)
    plan = {"operations": diff["operations"], "summary": diff["summary"], "bindings": preset["bindings"]}
    options = {"safe_mode": True, "confirm_deletions": False, "auto_bind_modules": True, "send_guides": True}

    job = db.create_server_builder_job(str(guild.id), "111", plan, options, len(diff["operations"]), diff["eta_seconds"])
    claimed = asyncio.run(db.async_claim_next_server_builder_job())

    _, cog = _new_cog(guild)
    asyncio.run(cog._execute_job(claimed))

    done_job = db.get_server_builder_job(job["id"])
    assert done_job["status"] == "completed", done_job
    assert len(guild.categories) == 4
    # Announcement fallback happened on non-COMMUNITY guild
    assert any("lacks COMMUNITY" in entry["message"] for entry in done_job["step_logs"])
    rules_ch = next(c for c in guild.channels if c.name == "rules")
    assert rules_ch.news is False

    # Verify Gate: pending_role view_channel=False added on normal channels, NOT on verify channel (#gate)
    chat_ch = next(c for c in guild.channels if c.name == "chat-chung")
    gate_ch = next(c for c in guild.channels if c.name == "gate")
    assert pending_role in chat_ch.overwrites and chat_ch.overwrites[pending_role].view_channel is False
    assert pending_role not in gate_ch.overwrites

    # Module bindings at Phase 6 + localized English Music Guide embed
    gs = db.get_guild_settings(str(guild.id))
    assert gs["welcome_channel_id"] == str(gate_ch.id)
    assert db.get_verify_settings(str(guild.id))["channel_id"] == str(gate_ch.id)
    logs_ch = next(c for c in guild.channels if c.name == "bot-logs")
    assert db.get_automod_settings(str(guild.id))["log_channel_id"] == str(logs_ch.id)
    assert db.get_logger_settings(str(guild.id))["log_channel_id"] == str(logs_ch.id)

    music_ch = next(c for c in guild.channels if c.name == "set-music")
    assert len(music_ch.sent) == 1
    sent_embed = music_ch.sent[0][1]["embed"]
    assert "Music Control Guide" in sent_embed.title
    assert "/play" in sent_embed.description

    # SQLite guild_channels cache refreshed immediately
    cached_names = {c["channel_name"] for c in db.get_guild_channels(str(guild.id))}
    assert "chat-chung" in cached_names

    # COMMUNITY guild preserves Announcement (news=True)
    comm_guild = FakeGuild(gid=999999999999999998, features=("COMMUNITY",), bitrate_limit=96000)
    comm_tree = {
        "roles": [],
        "categories": [{"temp_id": "c", "name": "INFO", "channels": [{"temp_id": "n", "name": "news", "type": 5}]}],
    }
    comm_diff = sbe.compute_diff({}, comm_tree, safe_mode=True)
    j_comm = db.create_server_builder_job(
        str(comm_guild.id), "111", {"operations": comm_diff["operations"], "summary": comm_diff["summary"], "bindings": {}},
        {"safe_mode": True, "auto_bind_modules": False, "send_guides": False}, len(comm_diff["operations"]), comm_diff["eta_seconds"]
    )
    _, comm_cog = _new_cog(comm_guild)
    asyncio.run(comm_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_comm["id"])["status"] == "completed"
    assert next(c for c in comm_guild.channels if c.name == "news").news is True


def test_cog_bulk_reorder_and_deletion_guard(temp_db):
    import database as db

    guild = FakeGuild()
    existing_cat = FakeCategory(3001, "OLD", guild, position=0)
    existing_ch = FakeChannel(3002, "old-chat", 0, guild, category=existing_cat, position=0)
    guild.categories.append(existing_cat)
    guild.channels.extend([existing_cat, existing_ch])
    _, cog = _new_cog(guild)

    # 1. bulk_reorder resolves category + child temp_ids and omits parent_id on categories
    plan_reorder = {
        "operations": [
            {"op": "create_category", "temp_id": "cat_x", "name": "SORTED", "position": 0, "overwrites": [], "cost_seconds": 1.0, "label": "Create SORTED"},
            {"op": "create_channel", "temp_id": "ch_x", "name": "new-first", "type": 0, "category_temp_id": "cat_x", "position": 0, "overwrites": [], "cost_seconds": 1.0, "label": "Create new-first"},
            {
                "op": "bulk_reorder",
                "items": [
                    {"id": None, "temp_id": "cat_x", "type": 4, "position": 0, "parent_id": None, "parent_temp_id": None},
                    {"id": None, "temp_id": "ch_x", "type": 0, "position": 0, "parent_id": None, "parent_temp_id": "cat_x"},
                    {"id": "3002", "temp_id": None, "type": 0, "position": 1, "parent_id": "3001", "parent_temp_id": None},
                ],
                "cost_seconds": 1.5,
                "label": "Bulk reorder",
            },
        ]
    }
    j_re = db.create_server_builder_job(str(guild.id), "111", plan_reorder, {"auto_bind_modules": False, "send_guides": False}, 3, 3.5)
    c_re = asyncio.run(db.async_claim_next_server_builder_job())
    asyncio.run(cog._execute_job(c_re))
    assert db.get_server_builder_job(j_re["id"])["status"] == "completed"
    assert len(guild._state.http.bulk_calls) == 1
    _, payload, _ = guild._state.http.bulk_calls[0]
    cat_entry = next(row for row in payload if row["position"] == 0 and "parent_id" not in row)
    child_entry = next(row for row in payload if row.get("parent_id") == cat_entry["id"])
    assert child_entry["position"] == 0

    # 2. Safe mode blocks deletion; unsafe + confirmed executes deletion
    plan_del = {"operations": [{"op": "delete_channel", "channel_id": "3002", "name": "old-chat", "type": 0, "cost_seconds": 1.0, "label": "Delete old-chat"}]}
    j_safe = db.create_server_builder_job(str(guild.id), "111", plan_del, {"safe_mode": True, "confirm_deletions": True, "auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    asyncio.run(cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_safe["id"])["status"] == "completed"
    assert existing_ch.deleted is False

    j_unsafe = db.create_server_builder_job(str(guild.id), "111", plan_del, {"safe_mode": False, "confirm_deletions": True, "auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    asyncio.run(cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_unsafe["id"])["status"] == "completed"
    assert existing_ch.deleted is True


def test_cog_bulk_reorder_splits_multi_parent_moves(temp_db):
    """Discord 40009: KHÔNG được đổi parent_id của nhiều kênh trong 1 bulk call.

    Khi >= 1 kênh đổi danh mục thật sự: chuyển từng kênh qua http.edit_channel
    (PATCH /channels/{id}) rồi khoá thứ tự bằng 1 bulk reorder KHÔNG kèm parent_id.
    """
    import database as db

    guild = FakeGuild()
    cat_a = FakeCategory(4001, "CAT-A", guild, position=0)
    cat_b = FakeCategory(4002, "CAT-B", guild, position=1)
    ch_a = FakeChannel(4011, "alpha", 0, guild, category=cat_a, position=0)
    ch_b = FakeChannel(4012, "beta", 0, guild, category=cat_b, position=0)
    guild.categories.extend([cat_a, cat_b])
    guild.channels.extend([cat_a, cat_b, ch_a, ch_b])
    _, cog = _new_cog(guild)

    plan = {
        "operations": [
            {
                "op": "bulk_reorder",
                "items": [
                    {"id": "4001", "temp_id": None, "type": 4, "position": 0, "parent_id": None, "parent_temp_id": None},
                    {"id": "4002", "temp_id": None, "type": 4, "position": 1, "parent_id": None, "parent_temp_id": None},
                    {"id": "4011", "temp_id": None, "type": 0, "position": 0, "parent_id": "4002", "parent_temp_id": None},
                    {"id": "4012", "temp_id": None, "type": 0, "position": 0, "parent_id": "4001", "parent_temp_id": None},
                ],
                "cost_seconds": 1.5,
                "label": "Bulk reorder",
            },
        ]
    }
    job = db.create_server_builder_job(
        str(guild.id), "111", plan, {"auto_bind_modules": False, "send_guides": False}, 1, 1.5
    )
    asyncio.run(cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(job["id"])["status"] == "completed"

    # 2 kênh đổi danh mục → 2 lần PATCH riêng, đúng parent đích
    edits = guild._state.http.channel_edit_calls
    assert len(edits) == 2, edits
    by_id = {cid: kwargs for cid, kwargs in edits}
    assert by_id[4011]["parent_id"] == 4002
    assert by_id[4012]["parent_id"] == 4001

    # Cuối cùng: ĐÚNG 1 bulk call khoá thứ tự, KHÔNG kèm parent_id nào
    assert len(guild._state.http.bulk_calls) == 1
    _, payload, _ = guild._state.http.bulk_calls[0]
    assert all("parent_id" not in row for row in payload)
    assert {row["id"] for row in payload} == {4001, 4002, 4011, 4012}


def test_cog_create_role_succeeds_when_bot_top_role_position_is_1(temp_db):
    import database as db

    # Fresh guild where bot role position == 1 and Moderator target position == 1
    fresh_guild = FakeGuild(gid=999999999999999997, bot_top_pos=1)
    _, cog = _new_cog(fresh_guild)
    plan_fresh = {
        "operations": [
            {
                "op": "create_role",
                "temp_id": "role_mod",
                "name": "Moderator",
                "color": "#3498DB",
                "hoist": True,
                "mentionable": False,
                "permissions": 0,
                "position": 1,
                "cost_seconds": 1.0,
                "label": "Create role: Moderator",
            },
            {
                "op": "create_category",
                "temp_id": "cat_staff",
                "name": "STAFF",
                "position": 0,
                "overwrites": [
                    {"id": "role_mod", "type": "role", "allow": ["view_channel"], "deny": []},
                ],
                "cost_seconds": 1.0,
                "label": "Create category: STAFF",
            },
        ]
    }
    j_fresh = db.create_server_builder_job(
        str(fresh_guild.id), "111", plan_fresh, {"auto_bind_modules": False, "send_guides": False}, 2, 2.0
    )
    asyncio.run(cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_fresh["id"])["status"] == "completed"
    mod_role = next((r for r in fresh_guild.roles if r.name == "Moderator"), None)
    assert mod_role is not None
    assert mod_role.edit_calls == []  # skipped role.edit(position=1) safely when bot top == 1
    assert mod_role in fresh_guild.categories[0].overwrites

    # Guild with bot_top_pos=5 clamps desired position=10 to 4
    mid_guild = FakeGuild(gid=999999999999999996, bot_top_pos=5)
    _, mid_cog = _new_cog(mid_guild)
    plan_clamp = {
        "operations": [
            {
                "op": "create_role",
                "temp_id": "role_hi",
                "name": "HighRole",
                "color": "#E67E22",
                "position": 10,
                "cost_seconds": 1.0,
                "label": "Create role: HighRole",
            }
        ]
    }
    j_mid = db.create_server_builder_job(
        str(mid_guild.id), "111", plan_clamp, {"auto_bind_modules": False, "send_guides": False}, 1, 1.0
    )
    asyncio.run(mid_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_mid["id"])["status"] == "completed"
    hi_role = next(r for r in mid_guild.roles if r.name == "HighRole")
    assert hi_role.edit_calls and hi_role.edit_calls[0]["position"] == 4


def test_cog_rename_deferral_429_paused_rl_and_cancel(temp_db):
    import database as db

    guild = FakeGuild()
    ch = FakeChannel(2001, "old-name", 0, guild)
    guild.channels.append(ch)
    _, cog = _new_cog(guild)

    # 2-in-10m rename/topic deferral: 1st & 2nd renames pass, 3rd defers name/topic without blocking slowmode
    plan_renames = {
        "operations": [
            {"op": "update_channel", "channel_id": "2001", "old_name": "old-name", "new_name": "name-1", "changes": {"name": "name-1"}, "cost_seconds": 1.0, "label": "Rename 1"},
            {"op": "update_channel", "channel_id": "2001", "old_name": "name-1", "new_name": "name-2", "changes": {"name": "name-2"}, "cost_seconds": 1.0, "label": "Rename 2"},
            {"op": "update_channel", "channel_id": "2001", "old_name": "name-2", "new_name": "name-3", "changes": {"name": "name-3", "topic": "deferred-topic", "slowmode": 10}, "cost_seconds": 1.0, "label": "Rename 3"},
        ]
    }
    j1 = db.create_server_builder_job(str(guild.id), "111", plan_renames, {"auto_bind_modules": False, "send_guides": False}, 3, 3.0)
    c1 = asyncio.run(db.async_claim_next_server_builder_job())
    asyncio.run(cog._execute_job(c1))
    done1 = db.get_server_builder_job(j1["id"])
    assert done1["status"] == "completed"
    assert ch.name == "name-2"
    assert ch.topic == ""
    assert ch.slowmode_delay == 10
    assert any(
        all(
            token in entry["message"]
            for token in ("Skipped/deferred", "without retry", "2-in-10m", "2-edits-per-10m")
        )
        for entry in done1["step_logs"]
    )

    # 429 paused_rl recovery + retry
    calls = {"n": 0}
    orig_create = guild.create_text_channel

    async def flaky_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            resp = types.SimpleNamespace(status=429, reason="Too Many Requests", headers={"Retry-After": "0.6"})
            raise discord.HTTPException(resp, "rate limited")
        return await orig_create(**kwargs)

    guild.create_text_channel = flaky_create
    plan_rl = {"operations": [{"op": "create_channel", "temp_id": "c1", "name": "rl-room", "type": 0, "cost_seconds": 1.0, "label": "Create rl-room"}]}
    j2 = db.create_server_builder_job(str(guild.id), "111", plan_rl, {"auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    c2 = asyncio.run(db.async_claim_next_server_builder_job())

    seen_paused = []
    orig_db_update = cog._db_update

    async def spy_update(job_id, **fields):
        if fields.get("status") == "paused_rl":
            seen_paused.append(fields)
        return await orig_db_update(job_id, **fields)

    cog._db_update = spy_update
    asyncio.run(cog._execute_job(c2))
    assert seen_paused and seen_paused[0]["rate_limit_until"] > time.time() - 5
    assert db.get_server_builder_job(j2["id"])["status"] == "completed"
    assert calls["n"] == 2

    # Cancel interruption *during* paused_rl sleep (NOT pre-cancelled before entering 429)
    async def long_429(**kwargs):
        resp = types.SimpleNamespace(status=429, reason="Too Many Requests", headers={"Retry-After": "30"})
        raise discord.HTTPException(resp, "rate limited")

    guild.create_text_channel = long_429
    j3 = db.create_server_builder_job(str(guild.id), "111", plan_rl, {"auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    c3 = asyncio.run(db.async_claim_next_server_builder_job())
    paused_then_cancelled = []

    async def cancel_on_pause(job_id, **fields):
        res = await orig_db_update(job_id, **fields)
        if fields.get("status") == "paused_rl" and job_id == j3["id"]:
            paused_then_cancelled.append(fields["rate_limit_until"])
            db.request_cancel_server_builder_job(j3["id"], str(guild.id))
        return res

    cog._db_update = cancel_on_pause
    t_start = time.monotonic()
    asyncio.run(cog._execute_job(c3))
    elapsed = time.monotonic() - t_start
    assert len(paused_then_cancelled) == 1
    assert elapsed < 5.0
    assert db.get_server_builder_job(j3["id"])["status"] == "cancelled"


def test_cog_on_ready_stale_recovery_and_loadable(temp_db):
    import database as db

    db.create_server_builder_job("g_stale", "1", {"operations": []}, {}, 1, 1.0)
    claimed = asyncio.run(db.async_claim_next_server_builder_job())
    assert claimed["status"] == "running"

    _, cog = _new_cog(FakeGuild())
    asyncio.run(cog.on_ready())
    assert cog._stale_recovered is True
    assert db.get_server_builder_job(claimed["id"])["status"] == "failed"

    # Loadable via discord.py extension loader without adding slash commands
    orig_start = tasks.Loop.start
    tasks.Loop.start = lambda self, *a, **k: None
    try:
        bot = commands.Bot(command_prefix="/", intents=discord.Intents.none(), help_command=None)
        asyncio.run(bot.load_extension("cogs.server_builder"))
        assert "ServerBuilder" in bot.cogs
        assert len(bot.tree.get_commands()) == 0
        asyncio.run(bot.close())
    finally:
        tasks.Loop.start = orig_start


def test_cog_roles_update_batch_reorder_delete_toctou_and_bindings(temp_db):
    import sqlite3
    import database as db

    sb_cog_mod = _import_cog_module("server_builder")
    automod_mod = _import_cog_module("automod")
    events_mod = _import_cog_module("events")

    # 1. create_role (list[str] + permissions_bitfield + #99aab5->default), update_role, @everyone permissions-only, batch reorder
    guild = BatchReorderGuild(gid=999999999999999995, bot_top_pos=6, owner_id=1)
    guild.default_role.permissions = discord.Permissions(1 << 10)
    low_role = FakeRole(5010, "Member", position=1, guild=guild)
    high_role = FakeRole(5011, "CoOwner", position=7, guild=guild)
    managed_role = FakeRole(5012, "IntegrationBot", position=2, managed=True, guild=guild)
    guild.roles.extend([low_role, high_role, managed_role])
    _, cog = _new_cog(guild)

    bitfield_52 = (1 << 25) | (1 << 30) | (1 << 43) | (1 << 48) | (1 << 51) | (1 << 52)
    plan_roles = {
        "operations": [
            {
                "op": "create_role",
                "temp_id": "r_list",
                "name": "VoiceExpr",
                "color": "#99aab5",
                "hoist": True,
                "mentionable": True,
                "permissions": ["use_vad", "manage_guild_expressions", "create_guild_expressions"],
                "position": 10,
                "defer_position": True,
                "cost_seconds": 1.0,
                "label": "Create VoiceExpr",
            },
            {
                "op": "create_role",
                "temp_id": "r_bits",
                "name": "Full52Bit",
                "color": "#3498db",
                "hoist": False,
                "mentionable": False,
                "permissions_bitfield": str(bitfield_52),
                "position": 2,
                "defer_position": True,
                "cost_seconds": 1.0,
                "label": "Create Full52Bit",
            },
            {
                "op": "update_role",
                "role_id": str(low_role.id),
                "is_everyone": False,
                "changes": {
                    "name": "MemberPlus",
                    "color": "#2ecc71",
                    "hoist": True,
                    "mentionable": True,
                    "permissions": ["view_channel", "use_vad"],
                    "permissions_bitfield": str((1 << 10) | (1 << 25)),
                },
                "cost_seconds": 1.0,
                "label": "Update Member",
            },
            {
                "op": "update_role",
                "role_id": "@everyone",
                "is_everyone": True,
                "changes": {
                    "name": "HijackedName",
                    "color": "#ff0000",
                    "hoist": True,
                    "mentionable": True,
                    "permissions": ["view_channel", "send_messages"],
                    "permissions_bitfield": str((1 << 10) | (1 << 11)),
                },
                "cost_seconds": 1.0,
                "label": "Update @everyone",
            },
            {
                "op": "bulk_reorder_roles",
                "items": [
                    {"id": str(high_role.id), "position": 1},
                    {"id": str(managed_role.id), "position": 2},
                    {"id": str(low_role.id), "position": 3},
                    {"id": None, "temp_id": "r_bits", "position": 4},
                    {"id": None, "temp_id": "r_list", "position": 10},
                ],
                "cost_seconds": 1.5,
                "label": "Bulk reorder roles",
            },
        ]
    }
    j_roles = db.create_server_builder_job(
        str(guild.id), "1", plan_roles, {"auto_bind_modules": False, "send_guides": False}, 5, 5.5
    )
    asyncio.run(cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_roles["id"])["status"] == "completed"

    voice_role = next(r for r in guild.roles if r.name == "VoiceExpr")
    assert voice_role.color == discord.Color.default()
    assert voice_role.color.value == 0
    assert voice_role.hoist is True
    assert voice_role.mentionable is True
    assert voice_role.permissions.use_voice_activation is True
    assert voice_role.permissions.manage_expressions is True
    assert voice_role.permissions.create_expressions is True
    assert voice_role.edit_calls == []  # defer_position=True skipped per-role edit

    bits_role = next(r for r in guild.roles if r.name == "Full52Bit")
    assert bits_role.color.value == 0x3498DB
    assert bits_role.permissions.value == bitfield_52
    assert bits_role.permissions.use_voice_activation is True
    assert bits_role.permissions.manage_expressions is True
    assert bits_role.permissions.create_expressions is True
    assert bits_role.permissions.set_voice_channel_status is True
    assert bits_role.permissions.pin_messages is True
    assert bits_role.permissions.bypass_slowmode is True
    assert bits_role.edit_calls == []

    assert low_role.name == "MemberPlus"
    assert low_role.color.value == 0x2ECC71
    assert low_role.hoist is True
    assert low_role.mentionable is True
    assert low_role.permissions.value == ((1 << 10) | (1 << 25))

    assert len(guild.default_role.edit_calls) == 1
    ev_call = guild.default_role.edit_calls[0]
    assert set(ev_call.keys()) == {"permissions", "reason"}
    assert ev_call["permissions"].value == ((1 << 10) | (1 << 11))
    assert guild.default_role.name == "@everyone"

    assert len(guild.role_position_calls) == 1
    batch_positions, _ = guild.role_position_calls[0]
    assert high_role not in batch_positions
    assert managed_role not in batch_positions
    assert guild.default_role not in batch_positions
    assert set(batch_positions.keys()) == {low_role, bits_role, voice_role}
    assert all(1 <= pos <= 5 for pos in batch_positions.values())
    assert len(set(batch_positions.values())) == 3
    assert batch_positions[voice_role] > batch_positions[bits_role] > batch_positions[low_role]

    # 1b. http.move_role_position fallback when guild lacks edit_role_positions
    fb_guild = FakeGuild(gid=999999999999999994, bot_top_pos=5, owner_id=1)
    r_fb1 = FakeRole(5101, "FB1", position=1, guild=fb_guild)
    r_fb2 = FakeRole(5102, "FB2", position=2, guild=fb_guild)
    fb_guild.roles.extend([r_fb1, r_fb2])
    _, fb_cog = _new_cog(fb_guild)
    plan_fb = {
        "operations": [
            {
                "op": "bulk_reorder_roles",
                "items": [
                    {"id": str(r_fb1.id), "position": 9},
                    {"id": str(r_fb2.id), "position": 1},
                ],
                "cost_seconds": 1.5,
                "label": "Fallback reorder",
            }
        ]
    }
    j_fb = db.create_server_builder_job(
        str(fb_guild.id), "1", plan_fb, {"auto_bind_modules": False, "send_guides": False}, 1, 1.5
    )
    asyncio.run(fb_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_fb["id"])["status"] == "completed"
    assert len(fb_guild._state.http.move_role_calls) == 1
    _, move_payload, _ = fb_guild._state.http.move_role_calls[0]
    pos_by_id = {row["id"]: row["position"] for row in move_payload}
    assert pos_by_id[r_fb1.id] <= 4 and pos_by_id[r_fb1.id] > pos_by_id[r_fb2.id]

    # 2. delete_role protections (safe_mode, confirm_deletions, bot_admin_roles, verify_settings, ticket_panels) & _sb_expected_deletes
    del_guild = FakeGuild(gid=999999999999999993, bot_top_pos=10, owner_id=1)
    r_admin = FakeRole(5201, "BotAdmin", position=2, guild=del_guild)
    r_ver = FakeRole(5202, "Verified", position=3, guild=del_guild)
    r_pend = FakeRole(5203, "Pending", position=4, guild=del_guild)
    r_ticket = FakeRole(5204, "TicketSupport", position=5, guild=del_guild)
    r_high = FakeRole(5205, "TooHigh", position=11, guild=del_guild)
    r_managed = FakeRole(5206, "Managed", position=6, managed=True, guild=del_guild)
    r_drop = FakeRole(5207, "Deletable", position=7, guild=del_guild)
    r_fail = FakeRole(5208, "FailDelete", position=8, guild=del_guild)

    async def boom_delete(**kwargs):
        raise RuntimeError("transient delete failure")

    r_fail.delete = boom_delete
    del_guild.roles.extend([r_admin, r_ver, r_pend, r_ticket, r_high, r_managed, r_drop, r_fail])
    _, del_cog = _new_cog(del_guild)

    gid_del = str(del_guild.id)
    db.upsert_guild(gid_del, bot_admin_roles=json.dumps([str(r_admin.id)]))
    db.upsert_verify_settings(gid_del, enabled=1, verified_role_id=str(r_ver.id), pending_role_id=str(r_pend.id))
    db.save_ticket_panel(gid_del, {"name": "Help", "channel_id": "3001", "support_role_id": str(r_ticket.id)}, [])

    plan_del_drop = {"operations": [{"op": "delete_role", "role_id": str(r_drop.id), "name": "Deletable", "cost_seconds": 1.0, "label": "Delete Deletable"}]}
    j_d_safe = db.create_server_builder_job(gid_del, "1", plan_del_drop, {"safe_mode": True, "confirm_deletions": True, "auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    asyncio.run(del_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_d_safe["id"])["status"] == "completed"
    assert r_drop.deleted is False

    j_d_unconf = db.create_server_builder_job(gid_del, "1", plan_del_drop, {"safe_mode": False, "confirm_deletions": False, "auto_bind_modules": False, "send_guides": False}, 1, 1.0)
    asyncio.run(del_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_d_unconf["id"])["status"] == "completed"
    assert r_drop.deleted is False

    plan_del_all = {
        "operations": [
            {"op": "delete_role", "role_id": "@everyone", "name": "@everyone", "cost_seconds": 1.0, "label": "Delete @everyone"},
            {"op": "delete_role", "role_id": str(r_admin.id), "name": "BotAdmin", "cost_seconds": 1.0, "label": "Delete BotAdmin"},
            {"op": "delete_role", "role_id": str(r_ver.id), "name": "Verified", "cost_seconds": 1.0, "label": "Delete Verified"},
            {"op": "delete_role", "role_id": str(r_pend.id), "name": "Pending", "cost_seconds": 1.0, "label": "Delete Pending"},
            {"op": "delete_role", "role_id": str(r_ticket.id), "name": "TicketSupport", "cost_seconds": 1.0, "label": "Delete TicketSupport"},
            {"op": "delete_role", "role_id": str(r_high.id), "name": "TooHigh", "cost_seconds": 1.0, "label": "Delete TooHigh"},
            {"op": "delete_role", "role_id": str(r_managed.id), "name": "Managed", "cost_seconds": 1.0, "label": "Delete Managed"},
            {"op": "delete_role", "role_id": str(r_drop.id), "name": "Deletable", "cost_seconds": 1.0, "label": "Delete Deletable"},
            {"op": "delete_role", "role_id": str(r_fail.id), "name": "FailDelete", "cost_seconds": 1.0, "label": "Delete FailDelete"},
        ]
    }
    j_d_exec = db.create_server_builder_job(gid_del, "1", plan_del_all, {"safe_mode": False, "confirm_deletions": True, "auto_bind_modules": False, "send_guides": False}, 9, 9.0)
    asyncio.run(del_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    done_del = db.get_server_builder_job(j_d_exec["id"])
    assert done_del["status"] == "failed" and done_del["failed_steps"] == 1
    assert r_admin.deleted is False
    assert r_ver.deleted is False
    assert r_pend.deleted is False
    assert r_ticket.deleted is False
    assert r_high.deleted is False
    assert r_managed.deleted is False
    assert del_guild.default_role.deleted is False
    assert r_drop.deleted is True
    assert (gid_del, "role_delete", str(r_drop.id)) in del_cog.bot._sb_expected_deletes
    assert (gid_del, "role_delete", str(r_fail.id)) not in del_cog.bot._sb_expected_deletes

    # 3. Automod._on_delete_event suppresses expected Server Builder deletes while catching concurrent rogue deletes
    am_guild = FakeGuild(gid=999999999999999992, bot_top_pos=10, owner_id=1)
    rogue_actor = types.SimpleNamespace(
        id=777,
        bot=False,
        mention="<@777>",
        guild_permissions=types.SimpleNamespace(administrator=False),
        roles=[],
    )
    am_guild._members[777] = rogue_actor
    am_guild._audit_entries = [
        types.SimpleNamespace(
            action=discord.AuditLogAction.role_delete,
            user=rogue_actor,
            created_at=discord.utils.utcnow(),
        )
    ]
    gid_am = str(am_guild.id)
    db.upsert_guild(gid_am, language="en")
    db.set_module(gid_am, "automods", True)
    db.upsert_automod_settings(gid_am, anti_nuke_enabled=1)

    _, sb_for_am = _new_cog(am_guild)

    async def _run_automod_antinuke():
        am_cog = automod_mod.Automod(sb_for_am.bot)
        try:
            for idx in range(3):
                sb_for_am._register_expected_delete(am_guild.id, "role_delete", 6000 + idx)
                await am_cog.on_guild_role_delete(FakeRole(6000 + idx, f"SBRole{idx}", guild=am_guild))
            for idx in range(2):
                sb_for_am._register_expected_delete(am_guild.id, "channel_delete", 6100 + idx)
                await am_cog.on_guild_channel_delete(FakeChannel(6100 + idx, f"sb-ch-{idx}", 0, am_guild))

            assert am_cog.nuke_cache[gid_am] == []
            assert am_guild.banned_users == []

            for idx in range(4):
                await am_cog.on_guild_role_delete(FakeRole(7000 + idx, f"Rogue{idx}", guild=am_guild))
                sb_for_am._register_expected_delete(am_guild.id, "role_delete", 6200 + idx)
                await am_cog.on_guild_role_delete(FakeRole(6200 + idx, f"SBExtra{idx}", guild=am_guild))

            assert len(am_cog.nuke_cache[gid_am]) == 4
            assert am_guild.banned_users == []

            await am_cog.on_guild_role_delete(FakeRole(7004, "RogueTrigger", guild=am_guild))
            assert len(am_guild.banned_users) == 1
            assert am_guild.banned_users[0][0] is rogue_actor
        finally:
            am_cog.cog_unload()

    asyncio.run(_run_automod_antinuke())

    # 4. Gate 4 TOCTOU check blocking role mutations when actor lacks manage_roles/admin or ceiling drops
    toctou_guild = FakeGuild(gid=999999999999999991, bot_top_pos=15, owner_id=1)
    r_existing = FakeRole(5301, "Existing", position=4, guild=toctou_guild)
    toctou_guild.roles.append(r_existing)
    toctou_guild._members[111] = types.SimpleNamespace(
        guild_permissions=types.SimpleNamespace(administrator=False, manage_roles=False),
        top_role=FakeRole(999, "RevokedUserTop", position=10),
    )
    _, toctou_cog = _new_cog(toctou_guild)
    plan_toctou = {
        "operations": [
            {"op": "create_role", "temp_id": "r_t", "name": "Illegal", "position": 1, "cost_seconds": 1.0, "label": "Create Illegal"},
            {"op": "update_role", "role_id": str(r_existing.id), "changes": {"name": "Hijacked"}, "cost_seconds": 1.0, "label": "Update Existing"},
            {"op": "bulk_reorder_roles", "items": [{"id": str(r_existing.id), "position": 2}], "cost_seconds": 1.5, "label": "Reorder Existing"},
            {"op": "delete_role", "role_id": str(r_existing.id), "name": "Existing", "cost_seconds": 1.0, "label": "Delete Existing"},
        ]
    }
    j_toc = db.create_server_builder_job(
        str(toctou_guild.id), "111", plan_toctou,
        {"safe_mode": False, "confirm_deletions": True, "auto_bind_modules": False, "send_guides": False},
        4, 4.5,
    )
    asyncio.run(toctou_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    done_toc = db.get_server_builder_job(j_toc["id"])
    assert done_toc["status"] == "failed"
    assert done_toc["failed_steps"] == 4
    assert any("Actor no longer holds manage_roles or administrator" in entry["message"] for entry in done_toc["step_logs"])
    assert r_existing.name == "Existing" and r_existing.deleted is False
    assert all(r.name != "Illegal" for r in toctou_guild.roles)

    # TOCTOU actor_top_role_pos check even when actor still has manage_roles=True
    toctou_guild._members[111] = types.SimpleNamespace(
        guild_permissions=types.SimpleNamespace(administrator=False, manage_roles=True),
        top_role=FakeRole(999, "LowUserTop", position=3),
    )
    j_toc2 = db.create_server_builder_job(
        str(toctou_guild.id), "111",
        {"operations": [{"op": "update_role", "role_id": str(r_existing.id), "changes": {"name": "AboveActor"}, "cost_seconds": 1.0, "label": "Update AboveActor"}]},
        {"auto_bind_modules": False, "send_guides": False},
        1, 1.0,
    )
    asyncio.run(toctou_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    done_toc2 = db.get_server_builder_job(j_toc2["id"])
    assert done_toc2["status"] == "failed"
    assert r_existing.name == "Existing"

    # 5. Phase 6 role module bindings (+ explicit None unbinds) & 10-column guild_roles persistence + _sb_active_guilds skip
    bind_guild = FakeGuild(gid=999999999999999990, bot_top_pos=20, owner_id=1)
    gid_bind = str(bind_guild.id)
    db.upsert_guild(gid_bind, autoroles_user=json.dumps(["8000", "8001"]), autoroles_enabled=0)
    db.upsert_automod_settings(gid_bind, immune_roles=["8003", "8002"])
    _, bind_cog = _new_cog(bind_guild)

    plan_bind = {
        "operations": [
            {"op": "create_role", "temp_id": "r_ar", "name": "AutoMember", "color": "#2ecc71", "position": 1, "bind_role_module": "autoroles_user", "cost_seconds": 1.0, "label": "Create AutoMember"},
            {"op": "create_role", "temp_id": "r_ver", "name": "VerifiedRole", "color": "#3498db", "position": 2, "bind_role_module": "verify_verified", "cost_seconds": 1.0, "label": "Create VerifiedRole"},
            {"op": "create_role", "temp_id": "r_pend", "name": "PendingRole", "color": "#95a5a6", "position": 3, "bind_role_module": "verify_pending", "cost_seconds": 1.0, "label": "Create PendingRole"},
            {"op": "create_role", "temp_id": "r_imm", "name": "ImmuneRole", "color": "#e74c3c", "position": 4, "bind_role_module": "automod_immune", "cost_seconds": 1.0, "label": "Create ImmuneRole"},
            {
                "op": "bind_modules",
                "bindings": {
                    "autoroles_user": "r_ar",
                    "verify_verified": "r_ver",
                    "verify_pending": "r_pend",
                    "automod_immune": "r_imm",
                },
                "cost_seconds": 0.5,
                "label": "Bind roles",
            },
        ]
    }
    j_bind = db.create_server_builder_job(
        gid_bind, "1", plan_bind, {"auto_bind_modules": True, "send_guides": False}, 5, 4.5
    )

    # Spy while job is running to verify _sb_active_guilds contains gid_bind mid-job
    active_mid_job = []
    orig_create_role = bind_guild.create_role

    async def spy_create_role(**kwargs):
        active_mid_job.append(gid_bind in getattr(bind_cog.bot, "_sb_active_guilds", set()))
        return await orig_create_role(**kwargs)

    bind_guild.create_role = spy_create_role
    asyncio.run(bind_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_bind["id"])["status"] == "completed"
    assert active_mid_job and all(active_mid_job)
    assert gid_bind not in bind_cog.bot._sb_active_guilds

    ar_role = next(r for r in bind_guild.roles if r.name == "AutoMember")
    ver_role = next(r for r in bind_guild.roles if r.name == "VerifiedRole")
    pend_role = next(r for r in bind_guild.roles if r.name == "PendingRole")
    imm_role = next(r for r in bind_guild.roles if r.name == "ImmuneRole")

    gs_bind = db.get_guild_settings(gid_bind)
    assert json.loads(gs_bind["autoroles_user"]) == [str(ar_role.id), "8001"]
    assert gs_bind["autoroles_enabled"] == 1
    vs_bind = db.get_verify_settings(gid_bind)
    assert vs_bind["verified_role_id"] == str(ver_role.id)
    assert vs_bind["pending_role_id"] == str(pend_role.id)
    am_bind = db.get_automod_settings(gid_bind)
    assert am_bind["immune_roles"] == [str(imm_role.id), "8002"]

    # Explicit None unbinds clear primary bindings cleanly
    plan_unbind = {
        "operations": [
            {
                "op": "bind_modules",
                "bindings": {
                    "autoroles_user": None,
                    "verify_verified": None,
                    "verify_pending": None,
                    "automod_immune": None,
                },
                "cost_seconds": 0.5,
                "label": "Unbind roles",
            }
        ]
    }
    j_unbind = db.create_server_builder_job(
        gid_bind, "1", plan_unbind, {"auto_bind_modules": True, "send_guides": False}, 1, 0.5
    )
    asyncio.run(bind_cog._execute_job(asyncio.run(db.async_claim_next_server_builder_job())))
    assert db.get_server_builder_job(j_unbind["id"])["status"] == "completed"
    assert json.loads(db.get_guild_settings(gid_bind)["autoroles_user"]) == ["8001"]
    vs_unbound = db.get_verify_settings(gid_bind)
    assert vs_unbound["verified_role_id"] is None
    assert vs_unbound["pending_role_id"] is None
    assert db.get_automod_settings(gid_bind)["immune_roles"] == ["8002"]

    # Check 10-column guild_roles cache persisted by ServerBuilder & Events._serialize_roles + _sb_active_guilds skip
    with sqlite3.connect(temp_db) as raw:
        cols = [row[1] for row in raw.execute("PRAGMA table_info(guild_roles)").fetchall()]
    assert cols == [
        "guild_id", "role_id", "role_name", "color_hex", "position",
        "permissions", "hoist", "mentionable", "managed", "is_everyone",
    ]
    cached_roles = {r["role_id"]: r for r in db.get_guild_roles(gid_bind)}
    assert str(imm_role.id) in cached_roles
    assert cached_roles[str(imm_role.id)]["color_hex"] == "#e74c3c"
    assert cached_roles[str(bind_guild.default_role.id)]["is_everyone"] == 1

    # Events cog skips refresh while guild is in _sb_active_guilds, and refreshes once cleared
    ev_bot = types.SimpleNamespace(_sb_active_guilds={gid_bind})
    events_cog = events_mod.Events(ev_bot)
    imm_role.name = "ImmuneEditedDuringBuild"
    asyncio.run(events_cog.on_guild_role_update(imm_role, imm_role))
    assert db.get_guild_roles(gid_bind)[0]["role_name"] != "ImmuneEditedDuringBuild"

    ev_bot._sb_active_guilds.discard(gid_bind)
    serialized_ev = events_cog._serialize_roles(bind_guild)
    serialized_sb = sb_cog_mod._serialize_roles(bind_guild)
    assert {tuple(sorted(r.keys())) for r in serialized_ev} == {tuple(sorted(r.keys())) for r in serialized_sb}
    asyncio.run(events_cog.on_guild_role_update(imm_role, imm_role))
    refreshed = {r["role_id"]: r for r in db.get_guild_roles(gid_bind)}
    assert refreshed[str(imm_role.id)]["role_name"] == "ImmuneEditedDuringBuild"


# ---------------------------------------------------------------------------
# 4. Dashboard routes, RBAC, CSRF, IDOR & XSS Checks
# ---------------------------------------------------------------------------

def _mock_live_discord(monkeypatch, *, perm_bits: int = 0x10 | 0x10000000, bot_top_pos: int = 10, features=None):
    from dashboard import auth

    auth.invalidate_server_builder_tree_cache(MOCK_GUILD_ID)
    monkeypatch.setattr(auth, "_bot_identity_cache", {"ts": time.time(), "id": "900000000000000000"})

    class _Resp:
        def __init__(self, payload, ok=True):
            self._payload = payload
            self.ok = ok

        def json(self):
            return self._payload

    def fake_get(url, *args, **kwargs):
        if url.endswith(f"/guilds/{MOCK_GUILD_ID}/channels"):
            return _Resp([
                {
                    "id": "3001", "name": "📢 ANNOUNCEMENT", "type": 4, "position": 0,
                    "permission_overwrites": [{"id": MOCK_GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}],
                },
                {
                    "id": "3002", "name": "rules", "type": 0, "parent_id": "3001", "position": 0,
                    "permission_overwrites": [{"id": MOCK_GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}],
                },
            ])
        if url.endswith(f"/guilds/{MOCK_GUILD_ID}/roles"):
            return _Resp([
                {"id": MOCK_GUILD_ID, "name": "@everyone", "position": 0, "permissions": "0", "color": 0},
                {"id": "4001", "name": "ZerynBot", "position": bot_top_pos, "permissions": str(perm_bits), "managed": True, "color": 0},
                {"id": "4002", "name": "Owner", "position": bot_top_pos + 5, "permissions": "8", "color": 0},
            ])
        if url.endswith(f"/guilds/{MOCK_GUILD_ID}"):
            return _Resp({"features": features or ["COMMUNITY"], "premium_tier": 1, "owner_id": "1"})
        if f"/guilds/{MOCK_GUILD_ID}/members/" in url:
            return _Resp({"roles": ["4001"]})
        return _Resp({}, ok=False)

    monkeypatch.setattr(auth.requests, "get", fake_get)
    import config
    monkeypatch.setattr(config, "TOKEN", "fake-bot-token")


def test_dashboard_routes_auth_rbac_csrf_and_tree(client, temp_db, monkeypatch):
    import database as db
    from dashboard import auth

    # 1. Unauthenticated UI -> 302, API -> 401
    assert client.get(f"/dashboard/{MOCK_GUILD_ID}/server-builder").status_code == 302
    assert client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/tree").status_code == 401
    assert client.post(f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply", json={"tree": {}}).status_code == 401

    # 2. Wrong guild -> 403
    token = authed_client(client)
    assert client.get("/api/guild/123456789012345678/server-builder/tree").status_code == 403

    # 3. Missing bot_admin_roles -> 403
    db.upsert_guild(MOCK_GUILD_ID, bot_admin_roles=json.dumps(["99999"]))
    monkeypatch.setattr(auth, "get_member_roles", lambda gid, uid: ["11111"])
    assert client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/tree").status_code == 403
    db.upsert_guild(MOCK_GUILD_ID, bot_admin_roles="[]")

    # 4. CSRF enforced on POST/DELETE (including /apply)
    login(client)
    assert client.post(f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply", json={"tree": {}}).status_code == 403
    assert client.post(f"/api/guild/{MOCK_GUILD_ID}/server-builder/preview-diff", json={"tree": {}}).status_code == 403
    assert client.post(f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates", json={"name": "x", "tree": {}}).status_code == 403
    assert client.delete(f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates/1").status_code == 403
    assert client.post(f"/api/guild/{MOCK_GUILD_ID}/server-builder/jobs/1/cancel").status_code == 403

    # 4b. Invalid payloads -> 400
    token = set_csrf_token(client)
    assert client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/preview-diff",
        json={"tree": "not-an-object"},
        headers={"X-CSRF-Token": token},
    ).status_code == 400
    assert client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates",
        json={"name": "", "tree": {}},
        headers={"X-CSRF-Token": token},
    ).status_code == 400

    # 5. Live tree + UI render + cache fallback
    token = authed_client(client)
    _mock_live_discord(monkeypatch)
    ui_resp = client.get(f"/dashboard/{MOCK_GUILD_ID}/server-builder")
    assert ui_resp.status_code == 200
    assert b"sb-bootstrap" in ui_resp.data

    tree_resp = client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/tree")
    assert tree_resp.status_code == 200
    tree_data = tree_resp.get_json()
    assert tree_data["live_source"] == "discord"
    assert tree_data["categories"][0]["channels"][0]["permissions_synced"] is True

    monkeypatch.setattr("dashboard.blueprints.server_builder.get_guild_live_structure", lambda gid: None)
    cache_resp = client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/tree")
    assert cache_resp.status_code == 200
    assert cache_resp.get_json()["live_source"] == "cache"


def test_dashboard_apply_permissions_conflict_deletions_idor_and_templates(client, temp_db, monkeypatch):
    import database as db
    from dashboard import auth

    token = authed_client(client)
    headers = {"X-CSRF-Token": token}
    target_tree = {
        "roles": [],
        "categories": [{"temp_id": "c1", "name": "NEW", "channels": [{"temp_id": "ch1", "name": "chat", "type": 0}]}],
        "uncategorized": [],
    }

    # 1. Missing manage_channels -> 403
    _mock_live_discord(monkeypatch, perm_bits=0)
    resp_no_perm = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": target_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_no_perm.status_code == 403
    assert "manage_channels" in resp_no_perm.get_json()["missing"]

    # 1b. Missing manage_roles when diff creates role/overwrites -> 403
    _mock_live_discord(monkeypatch, perm_bits=0x10)
    role_tree = {
        "roles": [{"temp_id": "r1", "name": "Helper", "position": 1}],
        "categories": [{"temp_id": "c1", "name": "NEW", "overwrites": [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}], "channels": []}],
        "uncategorized": [],
    }
    resp_no_roles = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": role_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_no_roles.status_code == 403
    assert "manage_roles" in resp_no_roles.get_json()["missing"]

    # 2. Deletions unconfirmed when safe_mode=False -> 400
    _mock_live_discord(monkeypatch, perm_bits=0x10 | 0x10000000)
    resp_del = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": target_tree, "safe_mode": False, "confirm_deletions": False},
        headers=headers,
    )
    assert resp_del.status_code == 400
    assert resp_del.get_json()["error"] == "deletion_confirmation_required"

    # 3. Valid apply -> 202; second apply while active -> 409 conflict
    resp_ok = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": target_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_ok.status_code == 202
    job_id = resp_ok.get_json()["job"]["id"]

    resp_409 = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": target_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_409.status_code == 409
    assert resp_409.get_json()["active_job"]["id"] == job_id

    # 4. Cross-guild job IDOR -> 404
    foreign_job = db.create_server_builder_job("888888888888888888", MOCK_USER_ID, {"operations": []}, {}, 1, 1.0)
    assert client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/jobs/{foreign_job['id']}").status_code == 404
    assert client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/jobs/{foreign_job['id']}/cancel",
        headers=headers,
    ).status_code == 404

    # 5. Templates max 10 limit + cross-guild DELETE 404
    foreign_tpl = db.save_server_builder_template("888888888888888888", "Foreign", "", {"categories": []}, MOCK_USER_ID)
    assert client.delete(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates/{foreign_tpl['id']}",
        headers=headers,
    ).status_code == 404

    for i in range(10):
        r = client.post(
            f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates",
            json={"name": f"My Tpl {i}", "description": "d", "tree": target_tree},
            headers=headers,
        )
        assert r.status_code == 201
    r11 = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/templates",
        json={"name": "My Tpl 11", "description": "d", "tree": target_tree},
        headers=headers,
    )
    assert r11.status_code == 400
    assert r11.get_json()["error"] == "template_limit"

    # 6. Discord unavailable -> 503 on apply
    auth.invalidate_server_builder_tree_cache(MOCK_GUILD_ID)
    monkeypatch.setattr("dashboard.blueprints.server_builder.get_guild_live_structure", lambda gid: None)
    resp_503 = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": target_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_503.status_code == 503


def test_dashboard_role_authority_and_escalation_gates(client, temp_db, monkeypatch):
    import config
    import database as db
    from dashboard import auth

    bot_id = "900000000000000000"

    def _mock_role_studio(
        *,
        user_roles,
        bot_perm_bits=0x8,
        bot_top_pos=20,
        owner_id="1",
        extra_roles=(),
        extra_channels=(),
    ):
        auth.invalidate_server_builder_tree_cache(MOCK_GUILD_ID)
        auth._member_roles_cache.clear()
        monkeypatch.setattr(auth, "_bot_identity_cache", {"ts": time.time(), "id": bot_id})
        monkeypatch.setattr(config, "CLIENT_ID", bot_id)
        monkeypatch.setattr(config, "TOKEN", "fake-bot-token")

        class _Resp:
            def __init__(self, payload, ok=True):
                self._payload = payload
                self.ok = ok

            def json(self):
                return self._payload

        channels_payload = [
            {
                "id": "3001", "name": "📢 ANNOUNCEMENT", "type": 4, "position": 0,
                "permission_overwrites": [{"id": MOCK_GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}],
            },
            {
                "id": "3002", "name": "rules", "type": 0, "parent_id": "3001", "position": 0,
                "permission_overwrites": [{"id": MOCK_GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}],
            },
            {
                "id": "3003", "name": "secret-vault", "type": 0, "parent_id": None, "position": 1,
                "permission_overwrites": [{"id": MOCK_GUILD_ID, "type": 0, "allow": "0", "deny": "1024"}],
            },
            *extra_channels,
        ]
        roles_payload = [
            {"id": MOCK_GUILD_ID, "name": "@everyone", "position": 0, "permissions": "0", "color": 0},
            {"id": "4001", "name": "ZerynBot", "position": bot_top_pos, "permissions": str(bot_perm_bits), "managed": True, "color": 0},
            *extra_roles,
        ]

        def fake_get(url, *args, **kwargs):
            if url.endswith(f"/guilds/{MOCK_GUILD_ID}/channels"):
                return _Resp(channels_payload)
            if url.endswith(f"/guilds/{MOCK_GUILD_ID}/roles"):
                return _Resp(roles_payload)
            if url.endswith(f"/guilds/{MOCK_GUILD_ID}"):
                return _Resp({"features": ["COMMUNITY"], "premium_tier": 1, "owner_id": owner_id})
            if url.endswith(f"/guilds/{MOCK_GUILD_ID}/members/{bot_id}"):
                return _Resp({"roles": ["4001"]})
            if url.endswith(f"/guilds/{MOCK_GUILD_ID}/members/{MOCK_USER_ID}"):
                return _Resp({"roles": list(user_roles)})
            return _Resp({}, ok=False)

        monkeypatch.setattr(auth.requests, "get", fake_get)

    def _base_tree(roles, *, include_secret=True):
        uncat = [{"id": "3003", "name": "secret-vault", "type": 0, "position": 1, "overwrites": [{"id": "@everyone", "type": "role", "allow": [], "deny": ["view_channel"]}]}] if include_secret else []
        return {
            "roles": roles,
            "categories": [
                {
                    "id": "3001",
                    "name": "📢 ANNOUNCEMENT",
                    "position": 0,
                    "overwrites": [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}],
                    "channels": [
                        {
                            "id": "3002",
                            "name": "rules",
                            "type": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}],
                        }
                    ],
                }
            ],
            "uncategorized": uncat,
        }

    token = authed_client(client)
    headers = {"X-CSRF-Token": token}

    # 1. GET /tree returns is_guild_owner, user_top_role_pos, user_permissions, and role bindings
    db.upsert_guild(MOCK_GUILD_ID, autoroles_user=json.dumps(["4010"]))
    db.upsert_verify_settings(MOCK_GUILD_ID, enabled=1, verified_role_id="4011", pending_role_id="4012")
    db.upsert_automod_settings(MOCK_GUILD_ID, immune_roles=["4013"])
    _mock_role_studio(
        user_roles=["4013"],
        owner_id="1",
        extra_roles=[
            {"id": "4010", "name": "Member", "position": 2, "permissions": "0", "color": 0},
            {"id": "4011", "name": "Verified", "position": 3, "permissions": "0", "color": 0},
            {"id": "4012", "name": "Pending", "position": 4, "permissions": "0", "color": 0},
            {"id": "4013", "name": "StaffLead", "position": 7, "permissions": str(0x10000000 | 0x10), "color": 0x3498DB},
        ],
    )
    tree_resp = client.get(f"/api/guild/{MOCK_GUILD_ID}/server-builder/tree")
    assert tree_resp.status_code == 200
    tree_data = tree_resp.get_json()
    assert tree_data["is_guild_owner"] is False
    assert tree_data["user_top_role_pos"] == 7
    assert tree_data["user_permissions"]["manage_roles"] is True
    assert tree_data["user_permissions"]["administrator"] is False
    assert set(tree_data["user_permissions"]["member_role_ids"]) == {"4013"}
    assert tree_data["bindings"]["autoroles_user"] == "4010"
    assert tree_data["bindings"]["verify_verified"] == "4011"
    assert tree_data["bindings"]["verify_pending"] == "4012"
    assert tree_data["bindings"]["automod_immune"] == "4013"
    role_by_id = {r["id"]: r for r in tree_data["roles"]}
    assert role_by_id["4010"]["bind_role_module"] == "autoroles_user"
    assert role_by_id["4011"]["bind_role_module"] == "verify_verified"
    assert role_by_id["4012"]["bind_role_module"] == "verify_pending"
    assert role_by_id["4013"]["bind_role_module"] == "automod_immune"

    # 2. Gate 1: manage_channels + manage_guild WITHOUT manage_roles/admin -> 403 user_missing_permissions
    _mock_role_studio(
        user_roles=["4020"],
        owner_id="1",
        extra_roles=[
            {"id": "4020", "name": "ChannelMgr", "position": 5, "permissions": str(0x10 | 0x20), "color": 0},
        ],
    )
    gate1_tree = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4020", "name": "ChannelMgr", "position": 5, "permissions": ["manage_channels", "manage_guild"]},
        {"temp_id": "r_new", "name": "NewRole", "position": 1, "permissions": []},
    ])
    resp_gate1 = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": gate1_tree, "safe_mode": True},
        headers=headers,
    )
    assert resp_gate1.status_code == 403
    assert resp_gate1.get_json()["error"] == "user_missing_permissions"
    assert "manage_roles" in resp_gate1.get_json()["missing"]

    # 3. Gate 2: Non-owner WITH administrator cannot edit/delete/reorder roles >= user_top_role_pos
    gate2_roles = [
        {"id": "4021", "name": "Helper", "position": 2, "permissions": "0", "color": 0},
        {"id": "4030", "name": "CoAdmin", "position": 5, "permissions": "8", "color": 0},
        {"id": "4040", "name": "SeniorAdmin", "position": 6, "permissions": "8", "color": 0},
    ]
    _mock_role_studio(user_roles=["4030"], owner_id="1", extra_roles=gate2_roles)

    # 3a. Edit role above user_top_role_pos (pos 6 >= 5)
    t_edit_above = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4021", "name": "Helper", "position": 2, "permissions": []},
        {"id": "4030", "name": "CoAdmin", "position": 5, "permissions": ["administrator"]},
        {"id": "4040", "name": "HijackedAdmin", "position": 6, "permissions": ["administrator"]},
    ])
    r_g2_edit = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_edit_above, "safe_mode": True},
        headers=headers,
    )
    assert r_g2_edit.status_code == 403
    assert r_g2_edit.get_json()["error"] == "user_role_hierarchy_denied"

    # 3b. Delete role equal to user_top_role_pos (pos 5 >= 5)
    t_del_equal = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4021", "name": "Helper", "position": 2, "permissions": []},
        {"id": "4040", "name": "SeniorAdmin", "position": 6, "permissions": ["administrator"]},
    ])
    r_g2_del = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_del_equal, "safe_mode": False, "confirm_deletions": True},
        headers=headers,
    )
    assert r_g2_del.status_code == 403
    assert r_g2_del.get_json()["error"] == "user_role_hierarchy_denied"

    # 3c. Reorder role >= user_top_role_pos
    t_reorder_hi = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4021", "name": "Helper", "position": 5, "permissions": []},
        {"id": "4030", "name": "CoAdmin", "position": 2, "permissions": ["administrator"]},
        {"id": "4040", "name": "SeniorAdmin", "position": 6, "permissions": ["administrator"]},
    ])
    r_g2_re = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_reorder_hi, "safe_mode": True},
        headers=headers,
    )
    assert r_g2_re.status_code == 403
    assert r_g2_re.get_json()["error"] == "user_role_hierarchy_denied"

    # 4. Gate 3: Non-owner, non-admin with manage_roles cannot grant/revoke missing flags nor touch private channels
    user_bits_g3 = 0x10000000 | 0x10 | 0x400 | 0x800  # manage_roles, manage_channels, view_channel, send_messages
    mod_bits_g3 = 0x400 | 0x4  # view_channel, ban_members
    _mock_role_studio(
        user_roles=["4050"],
        owner_id="1",
        extra_roles=[
            {"id": "4022", "name": "BanMod", "position": 2, "permissions": str(mod_bits_g3), "color": 0},
            {"id": "4050", "name": "RoleMgr", "position": 10, "permissions": str(user_bits_g3), "color": 0},
        ],
    )

    # 4a. Grant administrator (missing)
    t_grant_admin = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4022", "name": "BanMod", "position": 2, "permissions": ["view_channel", "ban_members"]},
        {"id": "4050", "name": "RoleMgr", "position": 10, "permissions": ["manage_roles", "manage_channels", "view_channel", "send_messages"]},
        {"temp_id": "r_adm", "name": "EscAdmin", "position": 1, "permissions": ["administrator"]},
    ])
    r_g3_admin = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_grant_admin, "safe_mode": True},
        headers=headers,
    )
    assert r_g3_admin.status_code == 403
    assert r_g3_admin.get_json()["error"] == "privilege_escalation_denied"
    assert "administrator" in r_g3_admin.get_json()["missing"]

    # 4b. Grant ban_members (missing)
    t_grant_ban = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4022", "name": "BanMod", "position": 2, "permissions": ["view_channel", "ban_members"]},
        {"id": "4050", "name": "RoleMgr", "position": 10, "permissions": ["manage_roles", "manage_channels", "view_channel", "send_messages"]},
        {"temp_id": "r_ban", "name": "EscBan", "position": 1, "permissions": ["ban_members"]},
    ])
    r_g3_ban = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_grant_ban, "safe_mode": True},
        headers=headers,
    )
    assert r_g3_ban.status_code == 403
    assert r_g3_ban.get_json()["error"] == "privilege_escalation_denied"
    assert "ban_members" in r_g3_ban.get_json()["missing"]

    # 4c. Revoke ban_members from existing role 4022 (missing flag)
    t_revoke_ban = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4022", "name": "BanMod", "position": 2, "permissions": ["view_channel"]},
        {"id": "4050", "name": "RoleMgr", "position": 10, "permissions": ["manage_roles", "manage_channels", "view_channel", "send_messages"]},
    ])
    r_g3_rev = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_revoke_ban, "safe_mode": True},
        headers=headers,
    )
    assert r_g3_rev.status_code == 403
    assert r_g3_rev.get_json()["error"] == "privilege_escalation_denied"
    assert "ban_members" in r_g3_rev.get_json()["missing"]

    # 4d. Edit overwrites / delete private channel 3003 without view_channel -> 403 channel_access_denied
    base_g3_roles = [
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4022", "name": "BanMod", "position": 2, "permissions": ["view_channel", "ban_members"]},
        {"id": "4050", "name": "RoleMgr", "position": 10, "permissions": ["manage_roles", "manage_channels", "view_channel", "send_messages"]},
    ]
    t_priv_ow = _base_tree(base_g3_roles, include_secret=True)
    t_priv_ow["uncategorized"][0]["overwrites"] = [{"id": "@everyone", "type": "role", "allow": ["view_channel"], "deny": []}]
    r_g3_ow = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_priv_ow, "safe_mode": True},
        headers=headers,
    )
    assert r_g3_ow.status_code == 403
    assert r_g3_ow.get_json()["error"] == "channel_access_denied"

    t_priv_del = _base_tree(base_g3_roles, include_secret=False)
    r_g3_del = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_priv_del, "safe_mode": False, "confirm_deletions": True},
        headers=headers,
    )
    assert r_g3_del.status_code == 403
    assert r_g3_del.get_json()["error"] == "channel_access_denied"

    # 5a. Non-owner holding the granted flag below user_top_role_pos succeeds with 202
    user_bits_ok = 0x10000000 | 0x10 | 0x2 | 0x400  # manage_roles, manage_channels, kick_members, view_channel
    _mock_role_studio(
        user_roles=["4060"],
        owner_id="1",
        extra_roles=[
            {"id": "4060", "name": "KickMgr", "position": 10, "permissions": str(user_bits_ok), "color": 0},
        ],
    )
    t_ok_user = _base_tree([
        {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
        {"id": "4060", "name": "KickMgr", "position": 10, "permissions": ["manage_roles", "manage_channels", "kick_members", "view_channel"]},
        {"temp_id": "r_jr", "name": "JuniorMod", "position": 3, "permissions": ["kick_members", "view_channel"]},
    ])
    r_ok_user = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_ok_user, "safe_mode": True},
        headers=headers,
    )
    assert r_ok_user.status_code == 202
    job_user_id = r_ok_user.get_json()["job"]["id"]
    asyncio.run(db.async_update_server_builder_job(job_user_id, expected_statuses=["queued"], status="completed"))

    # 5b. Guild owner bypasses user ceiling & escalation checks and succeeds with 202
    _mock_role_studio(
        user_roles=[],
        owner_id=MOCK_USER_ID,
        extra_roles=[
            {"id": "4040", "name": "SeniorAdmin", "position": 15, "permissions": "0", "color": 0},
        ],
    )
    t_owner = _base_tree(
        [
            {"id": "@everyone", "name": "@everyone", "is_everyone": True, "permissions": []},
            {"id": "4040", "name": "OwnerExec", "position": 15, "permissions": ["administrator", "ban_members"]},
        ],
        include_secret=False,
    )
    r_owner = client.post(
        f"/api/guild/{MOCK_GUILD_ID}/server-builder/apply",
        json={"tree": t_owner, "safe_mode": False, "confirm_deletions": True},
        headers=headers,
    )
    assert r_owner.status_code == 202


def test_server_builder_js_has_no_unsafe_dom_sinks_and_no_default_i18n_filter():
    import shutil
    import subprocess

    js_path = ROOT / "dashboard" / "static" / "js" / "server_builder.js"
    js_src = js_path.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in js_src, f"Unsafe DOM sink '{sink}' found in server_builder.js"

    # Regression checks for #30 fixes: preset role merge, hex color parsing, null bind_module
    assert "mergedRoles" in js_src
    assert "parseRoleColor" in js_src
    assert "normalizeBindModule" in js_src

    node_bin = shutil.which("node")
    if node_bin:
        node_script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');

function sliceBetween(startMarker, endMarker) {
  const s = src.indexOf(startMarker);
  if (s === -1) throw new Error('Missing start marker: ' + startMarker);
  const e = src.indexOf(endMarker, s);
  if (e === -1) throw new Error('Missing end marker: ' + endMarker);
  return src.slice(s, e);
}

const extracted = [
  sliceBetween('const permissionColumns = [', 'const state = {'),
  sliceBetween('function node(', 'function notify('),
  sliceBetween('function entityKey(', 'function payloadBody('),
  sliceBetween('function allChannels(', 'function ensureSelection('),
  sliceBetween('function snapshot(', 'function isModified('),
  sliceBetween('function everyoneRoleId(', 'function isViewDenied('),
  sliceBetween('function sortedRolesList(', 'function roleOverwriteTargets('),
  sliceBetween('function renderPermissions(', 'function renderBanners('),
  sliceBetween('function stripRoleOverwrites(', 'function syncItem('),
  sliceBetween('function updateSelected(', 'function ensureLiveOption('),
  sliceBetween("els.undo.addEventListener('click',", 'els.reset.addEventListener('),
].join('\n');

function makeElement(tag) {
  const el = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    className: '',
    textContent: '',
    title: '',
    type: '',
    disabled: false,
    style: {},
    dataset: {},
    children: [],
    append(...nodes) {
      for (const n of nodes) {
        if (n && n.nodeType === 11) {
          this.children.push(...n.children);
        } else {
          this.children.push(n);
        }
      }
    },
    replaceChildren(...nodes) {
      this.children = [];
      this.append(...nodes);
    },
  };
  return el;
}

const permissionsBody = makeElement('tbody');
const sandbox = {
  clone: v => JSON.parse(JSON.stringify(v)),
  tr: (k, f = '') => f || k,
  notify: () => {},
  renderAll: () => {},
  schedulePreviewDiff: () => {},
  setActiveTab: tab => { sandbox.state.activeTab = tab; },
  ensureSelection: () => {},
  els: {
    undo: {
      disabled: true,
      addEventListener(eventName, handler) {
        if (eventName === 'click') this._clickHandler = handler;
      },
    },
    safeMode: { checked: true },
    permissionsBody,
  },
  document: {
    createElement: makeElement,
    createDocumentFragment: () => ({
      nodeType: 11,
      children: [],
      append(...nodes) {
        for (const n of nodes) {
          if (n && n.nodeType === 11) this.children.push(...n.children);
          else this.children.push(n);
        }
      },
    }),
    createTextNode: text => ({ nodeType: 3, textContent: String(text) }),
  },
  state: {
    activeTab: 'channels',
    live: { bot_top_role_pos: 5 },
    roles: [
      { id: '@everyone', name: '@everyone', color: '#000000', position: 0, is_everyone: true },
      { id: '900', name: 'LiveAdmin', color: '#e74c3c', position: 6, is_everyone: false },
      { id: '901', name: 'LiveHelper', color: '#1abc9c', position: 2, is_everyone: false },
    ],
    selected: 'ch_c',
    history: [],
    diff: { ops: [] },
    draft: {
      roles: [
        { temp_id: 'role_mod', id: null, name: 'Moderator', color: '#3498db', position: 4, hoist: true },
        { temp_id: 'role_officer', id: null, name: 'Officer', color: '#2ecc71', position: 3, hoist: true },
        { temp_id: 'role_tutor', id: null, name: 'Tutor', color: '#9b59b6', position: 1, hoist: false },
      ],
      bindings: {
        welcome: 'ch_a',
        verify: 'ch_b',
        tickets: 'none',
        giveaways: 'null',
        economy: 'ch_deleted',
        autoroles: 'ch_ghost',
      },
      categories: [
        {
          id: null,
          temp_id: 'cat_1',
          name: 'Community',
          type: 4,
          position: 0,
          overwrites: [],
          channels: [
            { id: null, temp_id: 'ch_a', name: 'welcome', type: 0, position: 0, bind_module: 'welcome', overwrites: [] },
            { id: null, temp_id: 'ch_b', name: 'verify', type: 0, position: 1, bind_module: 'verify', overwrites: [] },
            { id: null, temp_id: 'ch_c', name: 'general', type: 0, position: 2, bind_module: null, overwrites: [] },
            { id: null, temp_id: 'ch_deleted', name: 'old', type: 0, position: 3, _deleted: true, bind_module: 'economy', overwrites: [] },
          ],
        },
      ],
      uncategorized: [],
    },
  },
};

vm.runInNewContext(extracted, sandbox);

// 1. Existing basic helper checks
const color = sandbox.parseRoleColor('#3498db');
if (color.intVal !== 0x3498db || color.css !== '#3498db') throw new Error('bad color parse');
if (sandbox.normalizeBindModule('none') !== null) throw new Error('none should normalize to null');

// 2. compactTree() & cleanBindings(): roles preserved, sentinels/deleted stripped, multi-bindings kept
const compacted = sandbox.compactTree();
const roleKeys = compacted.roles.map(r => r.id || r.temp_id);
for (const expectedRole of ['@everyone', '900', '901', 'role_mod', 'role_officer', 'role_tutor']) {
  if (!roleKeys.includes(expectedRole)) throw new Error('Missing role after compactTree: ' + expectedRole);
}
if (compacted.bindings.welcome !== 'ch_a' || compacted.bindings.verify !== 'ch_b') {
  throw new Error('Multi-bindings welcome/verify lost: ' + JSON.stringify(compacted.bindings));
}
for (const strippedKey of ['tickets', 'giveaways', 'economy', 'autoroles']) {
  if (Object.prototype.hasOwnProperty.call(compacted.bindings, strippedKey)) {
    throw new Error('Stale/sentinel binding should have been stripped: ' + strippedKey);
  }
}

// 3. updateSelected('bind_module', ...): reassign conflicting binding & clear with 'none' while preserving independent bindings
sandbox.updateSelected('bind_module', 'welcome');
const chA = sandbox.findEntity('ch_a').item;
const chB = sandbox.findEntity('ch_b').item;
const chC = sandbox.findEntity('ch_c').item;
if (chA.bind_module !== null) throw new Error('Old welcome channel binding should be cleared');
if (chC.bind_module !== 'welcome') throw new Error('Selected channel should take welcome binding');
if (sandbox.state.draft.bindings.welcome !== 'ch_c') throw new Error('draft.bindings.welcome not updated to ch_c');
if (sandbox.state.draft.bindings.verify !== 'ch_b' || chB.bind_module !== 'verify') {
  throw new Error('Independent verify binding was unexpectedly altered');
}

sandbox.updateSelected('bind_module', 'none');
if (chC.bind_module !== null) throw new Error('bind_module="none" should clear chC.bind_module');
if (Object.prototype.hasOwnProperty.call(sandbox.state.draft.bindings, 'welcome')) {
  throw new Error('draft.bindings.welcome should be removed when cleared to none');
}
if (sandbox.state.draft.bindings.verify !== 'ch_b' || chB.bind_module !== 'verify') {
  throw new Error('Independent verify binding altered after none clear');
}

sandbox.state.selected = 'ch_b';
sandbox.updateSelected('bind_module', 'welcome');
if (chB.bind_module !== 'welcome' || sandbox.state.draft.bindings.welcome !== 'ch_b') {
  throw new Error('Switching chB to welcome failed');
}
if (Object.prototype.hasOwnProperty.call(sandbox.state.draft.bindings, 'verify')) {
  throw new Error('Previous verify key should be deleted when chB switches module');
}
sandbox.state.selected = 'ch_c';

// 4. renderPermissions(item, kind): mock DOM verifies @everyone, preset roles unlocked, existing >= bot_top_role_pos locked
sandbox.renderPermissions(chC, 'channel');
const rows = permissionsBody.children;
if (rows.length !== 6) throw new Error('Expected 6 role rows, got ' + rows.length);

function rowSummary(roleKey) {
  for (const row of rows) {
    const buttons = [];
    for (const td of row.children.slice(1)) {
      const group = td.children[0];
      buttons.push(...group.children);
    }
    if (buttons.some(btn => btn.dataset.role === roleKey)) {
      const th = row.children[0];
      const hasLock = th.children.some(child => child.className === 'sb-role-lock');
      const anyDisabled = buttons.some(btn => btn.disabled);
      const allDisabled = buttons.every(btn => btn.disabled);
      return { hasLock, anyDisabled, allDisabled, roleText: th.children.map(c => c.textContent || '').join('') };
    }
  }
  return null;
}

const evRow = rowSummary('@everyone');
if (!evRow || evRow.hasLock || evRow.anyDisabled) throw new Error('@everyone row invalid: ' + JSON.stringify(evRow));

for (const presetKey of ['role_mod', 'role_officer', 'role_tutor']) {
  const r = rowSummary(presetKey);
  if (!r || r.hasLock || r.anyDisabled) throw new Error('Preset role should render unlocked: ' + presetKey + ' ' + JSON.stringify(r));
}

const liveHelperRow = rowSummary('901');
if (!liveHelperRow || liveHelperRow.hasLock || liveHelperRow.anyDisabled) {
  throw new Error('Existing role below bot_top_role_pos should render unlocked: ' + JSON.stringify(liveHelperRow));
}

const liveAdminRow = rowSummary('900');
if (!liveAdminRow || !liveAdminRow.hasLock || !liveAdminRow.allDisabled) {
  throw new Error('Existing role >= bot_top_role_pos should render locked: ' + JSON.stringify(liveAdminRow));
}

// 5. normalizeRoleColorHex(0) & '#000000' -> '#99aab5'
if (sandbox.normalizeRoleColorHex(0) !== '#99aab5') throw new Error('normalizeRoleColorHex(0) must be #99aab5');
if (sandbox.normalizeRoleColorHex('#000000') !== '#99aab5') throw new Error('normalizeRoleColorHex(#000000) must be #99aab5');

// 6. updatePositions() leaves untouched live role positions unchanged
sandbox.state.draft.roles.push(
  { id: '900', name: 'LiveAdmin', color: '#e74c3c', position: 6, is_everyone: false },
  { id: '901', name: 'LiveHelper', color: '#1abc9c', position: 2, is_everyone: false }
);
sandbox.updatePositions();
const pos900 = sandbox.mergedRoles().find(r => r.id === '900').position;
const pos901 = sandbox.mergedRoles().find(r => r.id === '901').position;
if (pos900 !== 6 || pos901 !== 2) {
  throw new Error(`updatePositions() changed live role positions: 900=${pos900}, 901=${pos901}`);
}

// 7. Editing live role 901 in state.draft.roles overrides state.roles in mergedRoles() and compactTree().roles
const draft901 = sandbox.state.draft.roles.find(r => r.id === '901');
draft901.name = 'EditedHelper';
draft901.color = '#e67e22';
const merged901 = sandbox.mergedRoles().find(r => r.id === '901');
const compact901 = sandbox.compactTree().roles.find(r => r.id === '901');
if (!merged901 || merged901.name !== 'EditedHelper' || merged901.color !== '#e67e22') {
  throw new Error('Edited draft role 901 did not override state.roles in mergedRoles()');
}
if (!compact901 || compact901.name !== 'EditedHelper' || compact901.color !== '#e67e22') {
  throw new Error('Edited draft role 901 did not override state.roles in compactTree().roles');
}

// 8. Marking 901 _deleted = true omits it from compactTree().roles without state.roles re-adding it
sandbox.els.safeMode.checked = false;
sandbox.deleteOrRestore('901');
if (draft901._deleted !== true) throw new Error('deleteOrRestore("901") did not set _deleted = true');
if (sandbox.mergedRoles().some(r => r.id === '901')) {
  throw new Error('Deleted role 901 leaked back from state.roles into mergedRoles()');
}
if (sandbox.compactTree().roles.some(r => r.id === '901')) {
  throw new Error('Deleted role 901 leaked back from state.roles into compactTree().roles');
}

// 9. Deleting drafted role role_tutor cleans up dangling role_tutor overwrites on channels/categories and Undo restores both
const cat1 = sandbox.state.draft.categories[0];
cat1.overwrites.push({ id: 'role_tutor', type: 'role', allow: ['view_channel'], deny: [] });
chC.overwrites.push({ id: 'role_tutor', type: 'role', allow: ['send_messages'], deny: [] });
sandbox.deleteOrRestore('role_tutor');
if (sandbox.state.draft.roles.some(r => r.temp_id === 'role_tutor')) {
  throw new Error('Drafted role_tutor was not removed from state.draft.roles');
}
if (cat1.overwrites.some(ow => ow.id === 'role_tutor')) {
  throw new Error('Dangling role_tutor overwrite remained on category');
}
if (chC.overwrites.some(ow => ow.id === 'role_tutor')) {
  throw new Error('Dangling role_tutor overwrite remained on channel');
}
sandbox.els.undo._clickHandler();
const restoredCat = sandbox.state.draft.categories[0];
const restoredChC = sandbox.findEntity('ch_c').item;
if (!sandbox.state.draft.roles.some(r => r.temp_id === 'role_tutor')) {
  throw new Error('Undo did not restore drafted role_tutor');
}
if (!restoredCat.overwrites.some(ow => ow.id === 'role_tutor')) {
  throw new Error('Undo did not restore role_tutor overwrite on category');
}
if (!restoredChC.overwrites.some(ow => ow.id === 'role_tutor')) {
  throw new Error('Undo did not restore role_tutor overwrite on channel');
}
"""
        proc = subprocess.run([node_bin, "-e", node_script, str(js_path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node JS check failed: {proc.stderr or proc.stdout}"

    tpl_src = (ROOT / "dashboard" / "templates" / "server_builder.html").read_text(encoding="utf-8")
    base_src = (ROOT / "dashboard" / "templates" / "base_server.html").read_text(encoding="utf-8")
    assert not re.search(r"t\(\s*['\"]server_builder\.[^'\"]+['\"]\s*\)\s*\|\s*default", tpl_src)
    assert not re.search(r"t\(\s*['\"]nav\.server_builder['\"]\s*\)\s*\|\s*default", base_src)

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


def _import_cog_module():
    cogs_dir = str(ROOT / "bot" / "cogs")
    inserted = False
    if cogs_dir not in sys.path:
        sys.path.insert(0, cogs_dir)
        inserted = True
    try:
        import server_builder as sb_cog
    finally:
        if inserted and cogs_dir in sys.path:
            sys.path.remove(cogs_dir)
    return sb_cog


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


# ---------------------------------------------------------------------------
# 3. Offline Cog Worker (Fake Discord Guild/Channel/Role harness)
# ---------------------------------------------------------------------------

class FakeRole:
    def __init__(self, rid: int, name: str, position: int = 1, default: bool = False):
        self.id = rid
        self.name = name
        self.position = position
        self.color = discord.Color.default()
        self._default = default
        self.edit_calls = []

    def is_default(self):
        return self._default

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        if "position" in kwargs:
            self.position = kwargs["position"]


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

    async def bulk_channel_update(self, guild_id, payload, reason=None):
        self.bulk_calls.append((guild_id, payload, reason))


class FakeGuild:
    def __init__(self, gid: int = 999999999999999999, features=(), bitrate_limit=96000, bot_top_pos=50):
        self.id = gid
        self.name = "Fake Guild"
        self.icon = None
        self.features = tuple(features)
        self.bitrate_limit = bitrate_limit
        self.default_role = FakeRole(gid, "@everyone", position=0, default=True)
        self.me = types.SimpleNamespace(top_role=FakeRole(888, "ZerynBot", position=bot_top_pos))
        self.roles = [self.default_role]
        self.categories = []
        self.channels = []
        self._next_id = 1000
        self._state = types.SimpleNamespace(http=FakeHTTP())

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_channel(self, cid):
        for cat in self.categories:
            if cat.id == cid:
                return cat
        return next((c for c in self.channels if c.id == cid), None)

    def _alloc(self):
        self._next_id += 1
        return self._next_id

    async def create_role(self, **kwargs):
        r = FakeRole(self._alloc(), kwargs["name"], position=1)
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
  sliceBetween('function renderPermissions(', 'function renderBanners('),
  sliceBetween('function updateSelected(', 'function ensureLiveOption('),
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
  renderAll: () => {},
  schedulePreviewDiff: () => {},
  ensureSelection: () => {},
  els: {
    undo: { disabled: true },
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
"""
        proc = subprocess.run([node_bin, "-e", node_script, str(js_path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node JS check failed: {proc.stderr or proc.stdout}"

    tpl_src = (ROOT / "dashboard" / "templates" / "server_builder.html").read_text(encoding="utf-8")
    base_src = (ROOT / "dashboard" / "templates" / "base_server.html").read_text(encoding="utf-8")
    assert not re.search(r"t\(\s*['\"]server_builder\.[^'\"]+['\"]\s*\)\s*\|\s*default", tpl_src)
    assert not re.search(r"t\(\s*['\"]nav\.server_builder['\"]\s*\)\s*\|\s*default", base_src)

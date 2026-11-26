"""Server Builder Studio dashboard and JSON API routes."""

import copy
import json
import os
import sys
import threading

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import config
import database as db
from dashboard.api import _require_guild_access
from dashboard.auth import (
    _normalize_db_role,
    get_actor_guild_authority,
    get_guild_live_structure,
    invalidate_guild_channel_cache,
    invalidate_guild_roles_cache,
    invalidate_server_builder_tree_cache,
)
from dashboard.extensions import limiter
from dashboard.web_helpers import _server_ctx, guild_access_required

bp = Blueprint("server_builder", __name__)


def _engine():
    try:
        import server_builder_engine as sbe
    except (ImportError, ModuleNotFoundError):
        from bot import server_builder_engine as sbe
    return sbe


_ENGINE_CONSTS = _engine()
_PERMISSION_BITS = _ENGINE_CONSTS.PERMISSION_BITS
_PERMISSION_ALIASES = _ENGINE_CONSTS.PERMISSION_ALIASES

_ROLE_BIND_MODULES = frozenset({
    "autoroles_user",
    "verify_verified",
    "verify_pending",
    "automod_immune",
})
_TARGET_ROLE_KEYS = frozenset({
    "id",
    "temp_id",
    "name",
    "color",
    "position",
    "permissions",
    "hoist",
    "mentionable",
    "managed",
    "is_everyone",
    "bind_role_module",
    "_cache_readonly",
})

_LAST_BUSTED_JOB_MAX = 200
_last_busted_job_lock = threading.Lock()
_last_busted_job_by_guild: dict[str, tuple[int, float]] = {}


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_value(value, default):
    if isinstance(value, type(default)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
    return default


def _clean_id(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    token = str(value).strip()
    if not token or token.lower() in ("none", "null", "undefined"):
        return None
    return token


def _first_valid_id(raw) -> str | None:
    for item in _json_value(raw, []):
        cleaned = _clean_id(item)
        if cleaned:
            return cleaned
    return None


def _permission_names(value) -> list[str]:
    return _engine().normalize_role_permissions(value)


def _normalize_color_hex(value) -> str:
    return _engine().normalize_role_color(value)


def _normalize_overwrites(raw, guild_id: str) -> list[dict]:
    raw = _json_value(raw, [])
    result = []
    for overwrite in raw:
        if not isinstance(overwrite, dict):
            continue
        target_id = str(overwrite.get("id") or overwrite.get("target_id") or "").strip()
        if not target_id:
            continue
        if target_id == str(guild_id):
            target_id = "@everyone"
        raw_type = overwrite.get("type")
        ow_type = "member" if str(raw_type).strip().lower() in ("1", "member") else "role"
        allow_raw = overwrite.get("allow", overwrite.get("allow_bits", 0))
        deny_raw = overwrite.get("deny", overwrite.get("deny_bits", 0))
        result.append({
            "id": target_id,
            "type": ow_type,
            "allow": _permission_names(allow_raw),
            "deny": _permission_names(deny_raw),
        })
    return result


def _normalize_channel(raw: dict, guild_id: str, channel_to_binding: dict | None = None) -> dict:
    channel_type = _int(raw.get("type", raw.get("channel_type", 0)), 0)
    channel_id = str(raw.get("id") or raw.get("channel_id") or "")
    overwrites = _normalize_overwrites(
        raw.get("overwrites", raw.get("permission_overwrites", [])),
        guild_id,
    )
    default_bitrate = 64000 if channel_type == 2 else 0
    bitrate = _int(raw.get("bitrate"), default_bitrate)
    if channel_type == 2 and bitrate <= 0:
        bitrate = 64000
    bind_module = (channel_to_binding or {}).get(channel_id) if channel_id else None
    if bind_module is None:
        bind_module = raw.get("bind_module")
    return {
        "id": channel_id,
        "temp_id": str(raw.get("temp_id") or (f"live_{channel_id}" if channel_id else "")),
        "name": str(raw.get("name") or raw.get("channel_name") or ""),
        "type": channel_type,
        "position": _int(raw.get("position"), 0),
        "parent_id": str(raw.get("parent_id") or raw.get("category_id") or "") or None,
        "topic": str(raw.get("topic") or ""),
        "slowmode": _int(raw.get("slowmode", raw.get("rate_limit_per_user")), 0),
        "nsfw": bool(raw.get("nsfw", False)),
        "bitrate": bitrate,
        "user_limit": _int(raw.get("user_limit"), 0),
        "overwrites": overwrites,
        "bind_module": bind_module,
    }


def _normalize_roles(
    raw_roles,
    guild_id: str,
    *,
    role_to_binding: dict | None = None,
    live_source: str = "discord",
) -> list[dict]:
    engine = _engine()
    roles = []
    gid = str(guild_id)
    for raw in raw_roles or []:
        if not isinstance(raw, dict):
            continue
        role_id = str(raw.get("id") or raw.get("role_id") or "")
        name = str(raw.get("name") or raw.get("role_name") or "")
        is_everyone = bool(raw.get("is_everyone")) or role_id == gid or role_id == "@everyone" or name == "@everyone"
        has_perm_data = ("permissions" in raw and raw.get("permissions") is not None) or (
            "permission_bits" in raw and raw.get("permission_bits") is not None
        )
        is_cache_readonly = (live_source == "cache") or (not has_perm_data)
        permissions = raw.get("permissions", raw.get("permission_bits", "0"))
        if is_everyone:
            bind_role_module = None
        else:
            bind_role_module = (role_to_binding or {}).get(role_id) if role_id else None
            if bind_role_module is None:
                bind_role_module = engine.normalize_role_bind_module(raw.get("bind_role_module"))
        roles.append({
            "id": "@everyone" if is_everyone else role_id,
            "temp_id": None if is_everyone else (_clean_id(raw.get("temp_id")) or None),
            "name": "@everyone" if is_everyone else name,
            "color": engine.normalize_role_color(0 if is_everyone else raw.get("color", raw.get("color_hex", 0))),
            "position": 0 if is_everyone else _int(raw.get("position"), 0),
            "permissions": engine.normalize_role_permissions(permissions),
            "hoist": False if is_everyone else bool(raw.get("hoist", False)),
            "managed": False if is_everyone else bool(raw.get("managed", False)),
            "mentionable": False if is_everyone else bool(raw.get("mentionable", False)),
            "is_everyone": is_everyone,
            "bind_role_module": bind_role_module,
            "_cache_readonly": bool(is_cache_readonly),
        })
    roles.sort(
        key=lambda role: (
            role["position"],
            0 if role["is_everyone"] else 1,
            str(role.get("id") or ""),
        ),
        reverse=True,
    )
    return roles


def _channel_binding_map(bindings: dict | None) -> dict[str, str]:
    if not isinstance(bindings, dict):
        return {}
    mapping: dict[str, str] = {}
    for module_key in ("welcome", "verify", "bot_logs"):
        cid = bindings.get(module_key)
        if cid and str(cid) not in mapping:
            mapping[str(cid)] = module_key
    return mapping


def _role_binding_map(bindings: dict | None) -> dict[str, str]:
    if not isinstance(bindings, dict):
        return {}
    mapping: dict[str, str] = {}
    for module_key in ("autoroles_user", "verify_verified", "verify_pending", "automod_immune"):
        rid = _clean_id(bindings.get(module_key))
        if rid and rid not in mapping:
            mapping[rid] = module_key
    return mapping


def _build_tree(
    guild_id: str,
    raw_channels,
    raw_roles,
    bindings: dict | None = None,
    *,
    live_source: str = "discord",
) -> dict:
    engine = _engine()
    channel_to_binding = _channel_binding_map(bindings)
    role_to_binding = _role_binding_map(bindings)
    channels = [
        _normalize_channel(item, guild_id, channel_to_binding=channel_to_binding)
        for item in (raw_channels or [])
        if isinstance(item, dict)
    ]
    categories = []
    category_by_id = {}
    for channel in channels:
        if channel["type"] != 4:
            continue
        category = dict(channel)
        category["channels"] = []
        categories.append(category)
        if channel["id"]:
            category_by_id[channel["id"]] = category

    uncategorized = []
    for channel in channels:
        if channel["type"] == 4:
            continue
        parent = category_by_id.get(str(channel.get("parent_id") or ""))
        if parent is None:
            channel["permissions_synced"] = False
            channel["sync_permissions"] = False
            uncategorized.append(channel)
            continue
        synced = bool(engine.is_overwrites_synced(
            parent.get("overwrites", []),
            channel.get("overwrites", []),
        ))
        channel["permissions_synced"] = synced
        channel["sync_permissions"] = synced
        parent["channels"].append(channel)

    categories.sort(key=lambda item: (item["position"], item["id"]))
    uncategorized.sort(key=lambda item: (0 if item["type"] != 2 else 1, item["position"], item["id"]))
    for category in categories:
        category["channels"].sort(key=lambda item: (0 if item["type"] != 2 else 1, item["position"], item["id"]))
    return {
        "categories": categories,
        "uncategorized": uncategorized,
        "roles": _normalize_roles(
            raw_roles,
            guild_id,
            role_to_binding=role_to_binding,
            live_source=live_source,
        ),
    }


def _normalize_target_role(role: dict, gid: str) -> dict:
    engine = _engine()
    raw_id = str(role.get("id") or "").strip()
    is_ev = (
        bool(role.get("is_everyone"))
        or raw_id == gid
        or raw_id == "@everyone"
        or str(role.get("name") or "").strip() == "@everyone"
    )
    if is_ev:
        cleaned: dict = {
            "id": "@everyone",
            "name": "@everyone",
            "color": engine.normalize_role_color(0),
            "position": 0,
            "hoist": False,
            "mentionable": False,
            "managed": False,
            "is_everyone": True,
            "bind_role_module": None,
        }
        if "temp_id" in role:
            cleaned["temp_id"] = _clean_id(role.get("temp_id"))
        if "permissions" in role or "permission_bits" in role:
            cleaned["permissions"] = engine.normalize_role_permissions(
                role.get("permissions", role.get("permission_bits"))
            )
        if "_cache_readonly" in role:
            cleaned["_cache_readonly"] = bool(role.get("_cache_readonly", False))
        return cleaned

    cleaned = {}
    if "id" in role:
        cleaned["id"] = raw_id or None
    if "temp_id" in role:
        cleaned["temp_id"] = _clean_id(role.get("temp_id"))
    if "name" in role and role.get("name") is not None:
        cleaned["name"] = str(role.get("name") or "").strip()[:100]
    if "color" in role or "color_hex" in role:
        cleaned["color"] = engine.normalize_role_color(role.get("color", role.get("color_hex")))
    if "position" in role and role.get("position") is not None:
        cleaned["position"] = _int(role.get("position"), 0)
    if "permissions" in role or "permission_bits" in role:
        cleaned["permissions"] = engine.normalize_role_permissions(
            role.get("permissions", role.get("permission_bits"))
        )
    if "hoist" in role:
        cleaned["hoist"] = bool(role.get("hoist", False))
    if "mentionable" in role:
        cleaned["mentionable"] = bool(role.get("mentionable", False))
    if "managed" in role:
        cleaned["managed"] = bool(role.get("managed", False))
    if "is_everyone" in role:
        cleaned["is_everyone"] = False
    if "bind_role_module" in role:
        cleaned["bind_role_module"] = engine.normalize_role_bind_module(role.get("bind_role_module"))
    if "_cache_readonly" in role:
        cleaned["_cache_readonly"] = bool(role.get("_cache_readonly", False))
    return {k: v for k, v in cleaned.items() if k in _TARGET_ROLE_KEYS}


def _normalize_target_tree(tree: dict, guild_id: str) -> dict:
    normalized = copy.deepcopy(tree)
    gid = str(guild_id)

    def normalize_node_overwrites(node: dict) -> None:
        if "overwrites" in node or "permission_overwrites" in node:
            raw_ow = node.get("overwrites", node.get("permission_overwrites", []))
            node["overwrites"] = _normalize_overwrites(raw_ow, gid)
            node.pop("permission_overwrites", None)

    roles = normalized.get("roles")
    if isinstance(roles, list):
        normalized["roles"] = [
            _normalize_target_role(role, gid)
            for role in roles
            if isinstance(role, dict)
        ]

    for cat in normalized.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        normalize_node_overwrites(cat)
        for ch in cat.get("channels") or []:
            if isinstance(ch, dict):
                normalize_node_overwrites(ch)

    for ch in normalized.get("uncategorized") or []:
        if isinstance(ch, dict):
            normalize_node_overwrites(ch)

    return normalized


def _db_snapshot(guild_id: str) -> dict:
    categories = db.get_guild_categories(guild_id) or []
    text_channels = db.get_guild_channels(guild_id) or []
    voice_channels = db.get_guild_voice_channels(guild_id) or []
    raw_channels = []
    seen = set()
    for idx, row in enumerate(categories):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("id", item.get("category_id") or item.get("channel_id"))
        item.setdefault("name", item.get("category_name") or item.get("channel_name"))
        item.setdefault("position", idx)
        item["type"] = 4
        cid = str(item.get("id") or "")
        if cid:
            seen.add(cid)
        raw_channels.append(item)
    for idx, row in enumerate(list(text_channels) + list(voice_channels)):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        channel_id = str(item.get("id") or item.get("channel_id") or "")
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        item.setdefault("position", idx)
        raw_channels.append(item)
    return {
        "channels": raw_channels,
        "roles": [_normalize_db_role(r) for r in (db.get_guild_roles(guild_id) or []) if isinstance(r, dict)],
        "bot_permissions": {
            "administrator": False,
            "manage_channels": False,
            "manage_roles": False,
            "bitfield": "0",
        },
        "bot_top_role_pos": None,
        "bot_in_guild": False,
        "guild_features": [],
        "bitrate_limit": 96000,
    }


def _get_live_structure(guild_id: str, *, force_refresh: bool = False) -> dict | None:
    if force_refresh:
        try:
            return get_guild_live_structure(guild_id, force_refresh=True)
        except TypeError:
            invalidate_server_builder_tree_cache(guild_id)
            return get_guild_live_structure(guild_id)
    return get_guild_live_structure(guild_id)


def _snapshot(guild_id: str, allow_cache: bool = True, *, force_refresh: bool = False):
    live = _get_live_structure(guild_id, force_refresh=force_refresh)
    if live is not None:
        return live, "discord"
    if allow_cache:
        try:
            return _db_snapshot(guild_id), "cache"
        except Exception:
            pass
    return {
        "channels": [],
        "roles": [],
        "bot_permissions": {
            "administrator": False,
            "manage_channels": False,
            "manage_roles": False,
            "bitfield": "0",
        },
        "bot_top_role_pos": None,
        "bot_in_guild": False,
        "guild_features": [],
        "bitrate_limit": 96000,
    }, "cache"


def _maybe_bust_cache_on_recent_job(guild_id: str) -> bool:
    """Invalidate worker-local Discord caches once when a newly finished job is detected in SQLite."""
    gid = str(guild_id)
    try:
        recent = db.list_server_builder_jobs(gid, limit=1)
    except Exception:
        return False
    if not recent:
        return False
    job = recent[0]
    if job.get("status") not in ("completed", "cancelled", "failed"):
        return False
    job_id = _int(job.get("id"), 0)
    try:
        finished_at = float(job.get("finished_at") or 0.0)
    except (TypeError, ValueError):
        finished_at = 0.0
    if job_id <= 0 or finished_at <= 0.0:
        return False

    with _last_busted_job_lock:
        if _last_busted_job_by_guild.get(gid) == (job_id, finished_at):
            return False
        if len(_last_busted_job_by_guild) >= _LAST_BUSTED_JOB_MAX:
            _last_busted_job_by_guild.clear()
        _last_busted_job_by_guild[gid] = (job_id, finished_at)

    invalidate_guild_channel_cache(gid)
    invalidate_guild_roles_cache(gid)
    invalidate_server_builder_tree_cache(gid)
    return True


def _bindings(guild_id: str) -> dict:
    settings = db.get_guild_settings(guild_id) or {}
    verify = db.get_verify_settings(guild_id) or {}
    automod = db.get_automod_settings(guild_id) or {}
    logger = db.get_logger_settings(guild_id) or {}
    welcome_channel_id = settings.get("welcome_channel_id") or None
    verify_channel_id = verify.get("channel_id") or None
    automod_log_channel_id = automod.get("log_channel_id") or None
    logger_log_channel_id = logger.get("log_channel_id") or None
    return {
        "welcome_channel_id": welcome_channel_id,
        "verify_channel_id": verify_channel_id,
        "automod_log_channel_id": automod_log_channel_id,
        "logger_log_channel_id": logger_log_channel_id,
        "welcome": welcome_channel_id,
        "verify": verify_channel_id,
        "bot_logs": logger_log_channel_id or automod_log_channel_id,
        "autoroles_user": _first_valid_id(settings.get("autoroles_user")),
        "verify_verified": _clean_id(verify.get("verified_role_id")),
        "verify_pending": _clean_id(verify.get("pending_role_id")),
        "automod_immune": _first_valid_id(automod.get("immune_roles")),
    }


def _extract_target_role_bindings(target_tree: dict | None) -> dict[str, str]:
    if not isinstance(target_tree, dict):
        return {}
    engine = _engine()
    bound: dict[str, str] = {}
    for bdict in (target_tree.get("bindings"), target_tree.get("role_bindings")):
        if not isinstance(bdict, dict):
            continue
        for k, v in bdict.items():
            norm_k = engine.normalize_role_bind_module(k)
            val = _clean_id(v)
            if norm_k and val:
                bound[norm_k] = val
    for role in target_tree.get("roles") or []:
        if not isinstance(role, dict) or role.get("_deleted"):
            continue
        norm_k = engine.normalize_role_bind_module(role.get("bind_role_module"))
        if norm_k:
            ref = _clean_id(role.get("id")) or _clean_id(role.get("temp_id"))
            if ref:
                bound[norm_k] = ref
    return bound


def _protected_role_ids(guild_id: str, target_tree: dict | None = None) -> set[str]:
    protected: set[str] = set()
    settings = db.get_guild_settings(guild_id) or {}
    for rid in _json_value(settings.get("bot_admin_roles"), []):
        cleaned = _clean_id(rid)
        if cleaned:
            protected.add(cleaned)

    verify = db.get_verify_settings(guild_id) or {}
    if _int(verify.get("enabled"), 0) == 1:
        target_role_binds = _extract_target_role_bindings(target_tree)
        verified_role_id = _clean_id(verify.get("verified_role_id"))
        if verified_role_id:
            rebound = target_role_binds.get("verify_verified")
            if not rebound or rebound == verified_role_id:
                protected.add(verified_role_id)
        pending_role_id = _clean_id(verify.get("pending_role_id"))
        if pending_role_id:
            rebound = target_role_binds.get("verify_pending")
            if not rebound or rebound == pending_role_id:
                protected.add(pending_role_id)

    for panel in (db.get_ticket_panels(guild_id) or []):
        if not isinstance(panel, dict):
            continue
        support_role_id = _clean_id(panel.get("support_role_id"))
        if support_role_id:
            protected.add(support_role_id)

    return protected


def _api_guard(guild_id: str):
    err = _require_guild_access(str(guild_id))
    if err:
        return err
    if not str(guild_id).isdigit():
        return jsonify({"ok": False, "error": "invalid_guild_id"}), 400
    return None


def _validation_error(validation: dict):
    errors = validation.get("errors") or []
    return jsonify({
        "ok": False,
        "error": "invalid_tree",
        "errors": errors,
        "warnings": validation.get("warnings") or [],
        "message": "; ".join(str(e) for e in errors) or "Invalid server tree",
    }), 400


def _custom_template(item: dict) -> dict:
    result = dict(item)
    raw_tree = result["tree"] if "tree" in result else result.get("tree_json")
    result["tree"] = _json_value(raw_tree, {})
    return result


def _job_payload(job: dict | None) -> dict | None:
    if not isinstance(job, dict):
        return job
    raw_logs = job["step_logs"] if "step_logs" in job else job.get("step_logs_json")
    raw_opts = job["options"] if "options" in job else job.get("options_json")
    result = dict(job)
    # Keep HTTP polling payloads compact (<=256KB) by omitting heavy snapshot/plan blobs.
    for heavy_key in ("snapshot_before_json", "snapshot_before", "plan_json", "plan"):
        result.pop(heavy_key, None)
    result["step_logs"] = _json_value(raw_logs, [])
    result["options"] = _json_value(raw_opts, {})
    return result


def _diff_needs_roles(diff: dict) -> bool:
    engine = _engine()
    summary = diff.get("summary") or {}
    for key in (
        "create_roles",
        "update_roles",
        "delete_roles",
        "sync_permissions",
        "update_overwrites",
    ):
        if _int(summary.get(key), 0) > 0:
            return True
    for bool_key in ("reorder_roles", "bulk_reorder_roles"):
        if bool(summary.get(bool_key)):
            return True
    for operation in diff.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        op_name = str(
            operation.get("op")
            or operation.get("type")
            or operation.get("action")
            or operation.get("kind")
            or ""
        ).lower()
        if op_name in (
            "create_role",
            "update_role",
            "delete_role",
            "reorder_roles",
            "bulk_reorder_roles",
            "sync_permissions",
            "update_overwrites",
        ):
            return True
        if op_name in ("create_category", "create_channel") and operation.get("overwrites"):
            return True
        if op_name == "bind_modules":
            bindings = operation.get("bindings") or {}
            if isinstance(bindings, dict) and any(
                (engine.normalize_role_bind_module(k) or k) in _ROLE_BIND_MODULES
                for k in bindings
            ):
                return True
        if "role" in op_name or "overwrite" in op_name or "permission" in op_name:
            return True
    return False


def _enforce_actor_privilege_bounds(
    diff: dict,
    current_tree: dict,
    snapshot: dict,
    actor: dict,
    *,
    is_apply: bool = True,
    user_id: str | None = None,
):
    """Enforce P0 privilege-escalation, hierarchy, overwrite, and channel-access gates."""
    engine = _engine()
    warnings: list[str] = []

    def _deny(error_code: str, *, missing: list[str] | None = None, message: str = "", extra: dict | None = None):
        payload: dict = {"ok": False, "error": error_code}
        if missing is not None:
            payload["missing"] = missing
        if message:
            payload["message"] = message
        if extra:
            payload.update(extra)
        return jsonify(payload), 403

    # Gate 1: Role / overwrite / role-binding mutations require manage_roles (or admin/owner)
    if _diff_needs_roles(diff) and not (
        actor.get("is_owner") or actor.get("administrator") or actor.get("manage_roles")
    ):
        msg = "You lack the Manage Roles permission required for role or permission changes."
        if is_apply:
            return _deny("user_missing_permissions", missing=["manage_roles"], message=msg)
        warnings.append(f"user_missing_permissions: {msg}")

    roles_by_id: dict[str, dict] = {}
    for role in current_tree.get("roles") or []:
        if not isinstance(role, dict):
            continue
        rid = str(role.get("id") or "").strip()
        if rid:
            roles_by_id[rid] = role
        if role.get("is_everyone") or role.get("name") == "@everyone":
            roles_by_id["@everyone"] = role

    nodes_by_id: dict[str, dict] = {}
    for cat in current_tree.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cid = str(cat.get("id") or "").strip()
        if cid:
            nodes_by_id[cid] = cat
        for ch in cat.get("channels") or []:
            if not isinstance(ch, dict):
                continue
            chid = str(ch.get("id") or "").strip()
            if chid:
                nodes_by_id[chid] = ch
    for ch in current_tree.get("uncategorized") or []:
        if not isinstance(ch, dict):
            continue
        chid = str(ch.get("id") or "").strip()
        if chid:
            nodes_by_id[chid] = ch

    operations = diff.get("operations") or []
    is_owner = bool(actor.get("is_owner"))
    is_actor_admin = bool(actor.get("administrator"))
    user_top_role_pos = actor.get("user_top_role_pos")
    actor_bits = _int(actor.get("bitfield"), 0)

    bot_perms = snapshot.get("bot_permissions") or {}
    is_bot_admin = bool(bot_perms.get("administrator"))
    bot_bits = _int(bot_perms.get("bitfield"), 0)

    privileged_mask = 0
    for pname in engine.PRIVILEGED_OVERWRITE_NAMES:
        pbit = engine.PERMISSION_BIT_BY_NAME.get(pname)
        if pbit is not None:
            privileged_mask |= 1 << pbit

    def _ow_map(overwrites) -> dict[tuple[str, str], tuple[int, int]]:
        mapping: dict[tuple[str, str], tuple[int, int]] = {}
        for ow in overwrites or []:
            if not isinstance(ow, dict):
                continue
            tid = str(ow.get("id") if ow.get("id") is not None else ow.get("target_id") or "").strip()
            if not tid:
                continue
            raw_t = str(ow.get("type") or "role").strip().lower()
            ow_t = "member" if raw_t in ("1", "member") else "role"
            allow_b = engine.permissions_to_bitfield(ow.get("allow", ow.get("allow_bits", 0)))
            deny_b = engine.permissions_to_bitfield(ow.get("deny", ow.get("deny_bits", 0)))
            mapping[(ow_t, tid)] = (allow_b, deny_b)
        return mapping

    # Gate 2: Role hierarchy ceiling for all non-owners (including non-owner admins)
    if not is_owner and user_top_role_pos is not None:
        user_top_int = int(user_top_role_pos)
        for op in operations:
            if not isinstance(op, dict):
                continue
            op_name = str(op.get("op") or "").lower()
            if op_name == "update_role":
                rid = str(op.get("role_id") or "")
                if op.get("is_everyone") or rid == "@everyone":
                    continue
                curr_role = roles_by_id.get(rid)
                if curr_role is not None and _int(curr_role.get("position"), 0) >= user_top_int:
                    rname = str(curr_role.get("name") or rid)
                    msg = f"Role '@{rname}' is at or above your highest role."
                    if is_apply:
                        return _deny("user_role_hierarchy_denied", message=msg, extra={"role": rname})
                    warnings.append(f"user_role_hierarchy_denied: {msg}")
            elif op_name == "delete_role":
                rid = str(op.get("role_id") or "")
                curr_role = roles_by_id.get(rid)
                if curr_role is not None and _int(curr_role.get("position"), 0) >= user_top_int:
                    rname = str(curr_role.get("name") or rid)
                    msg = f"Role '@{rname}' is at or above your highest role."
                    if is_apply:
                        return _deny("user_role_hierarchy_denied", message=msg, extra={"role": rname})
                    warnings.append(f"user_role_hierarchy_denied: {msg}")
            elif op_name == "bulk_reorder_roles":
                for item in op.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    rid = str(item.get("id") or "").strip()
                    if not rid:
                        continue
                    curr_role = roles_by_id.get(rid)
                    if curr_role is not None and _int(curr_role.get("position"), 0) >= user_top_int:
                        rname = str(curr_role.get("name") or rid)
                        msg = f"Role '@{rname}' is at or above your highest role."
                        if is_apply:
                            return _deny("user_role_hierarchy_denied", message=msg, extra={"role": rname})
                        warnings.append(f"user_role_hierarchy_denied: {msg}")

    # Gate 3: Role permission ceiling (Bot & Actor), privileged overwrites, & private channel access
    for op in operations:
        if not isinstance(op, dict):
            continue
        op_name = str(op.get("op") or "").lower()

        if op_name in ("create_role", "update_role"):
            if op_name == "create_role":
                raw_perms = (
                    op.get("permissions_bitfield")
                    if op.get("permissions_bitfield") is not None
                    else op.get("permissions")
                )
                granted_bits = engine.permissions_to_bitfield(raw_perms)
                revoked_bits = 0
                has_perm_change = True
            else:
                changes = op.get("changes") or {}
                has_perm_change = isinstance(changes, dict) and (
                    "permissions" in changes or "permissions_bitfield" in changes
                )
                if has_perm_change:
                    rid = str(op.get("role_id") or "")
                    curr_role = roles_by_id.get(rid)
                    curr_bits = engine.permissions_to_bitfield(
                        curr_role.get("permissions", 0) if curr_role is not None else 0
                    )
                    raw_tgt = (
                        changes.get("permissions_bitfield")
                        if "permissions_bitfield" in changes
                        else changes.get("permissions")
                    )
                    tgt_bits = engine.permissions_to_bitfield(raw_tgt)
                    granted_bits = tgt_bits & ~curr_bits
                    revoked_bits = curr_bits & ~tgt_bits
                else:
                    granted_bits = 0
                    revoked_bits = 0

            if has_perm_change and (granted_bits or revoked_bits):
                changed_bits = granted_bits | revoked_bits
                if not is_bot_admin:
                    bot_exceeded = changed_bits & ~bot_bits
                    if bot_exceeded != 0:
                        missing_list = engine.normalize_role_permissions(bot_exceeded)
                        msg = f"ZerynBot lacks permissions to modify: {', '.join(missing_list)}."
                        if is_apply:
                            return _deny("bot_missing_permissions", missing=missing_list, message=msg)
                        warnings.append(f"bot_missing_permissions: {msg}")

                if not is_owner and not is_actor_admin:
                    actor_exceeded = changed_bits & ~actor_bits
                    if actor_exceeded != 0:
                        missing_list = engine.normalize_role_permissions(actor_exceeded)
                        msg = "Cannot grant or revoke permissions you do not personally possess."
                        if is_apply:
                            return _deny("privilege_escalation_denied", missing=missing_list, message=msg)
                        warnings.append(f"privilege_escalation_denied: {', '.join(missing_list)}")

        if op_name in ("create_category", "create_channel", "update_overwrites"):
            if op_name == "update_overwrites":
                existing_node = nodes_by_id.get(str(op.get("channel_id") or "").strip())
                prev_ow = _ow_map(existing_node.get("overwrites") if existing_node is not None else [])
            else:
                prev_ow = {}
            new_ow = _ow_map(op.get("overwrites"))
            newly_added_priv = 0
            for key, (allow_b, deny_b) in new_ow.items():
                prev_allow, prev_deny = prev_ow.get(key, (0, 0))
                newly_added_priv |= ((allow_b & ~prev_allow) | (deny_b & ~prev_deny)) & privileged_mask

            if newly_added_priv and not is_owner and not is_actor_admin:
                missing_priv = newly_added_priv & ~actor_bits
                if missing_priv != 0:
                    missing_list = engine.normalize_role_permissions(missing_priv)
                    msg = "Cannot modify privileged channel overwrites you do not possess."
                    if is_apply:
                        return _deny("privilege_escalation_denied", missing=missing_list, message=msg)
                    warnings.append(f"privilege_escalation_denied: {', '.join(missing_list)}")

        if op_name in ("update_overwrites", "sync_permissions", "update_channel", "delete_channel", "delete_category"):
            cid = str(op.get("channel_id") or "").strip()
            existing_node = nodes_by_id.get(cid)
            if existing_node is not None:
                perm_bits = engine.compute_channel_permissions(
                    current_tree.get("roles") or [],
                    actor.get("member_role_ids") or [],
                    existing_node.get("overwrites") or [],
                    is_owner=is_owner,
                    member_id=user_id,
                )
                view_bit = 1 << engine.PERMISSION_BIT_BY_NAME["view_channel"]
                if (perm_bits & view_bit) == 0:
                    ch_name = str(existing_node.get("name") or cid)
                    msg = f"You do not have view_channel access to '{ch_name}'."
                    if is_apply:
                        return _deny("channel_access_denied", message=msg, extra={"channel": ch_name})
                    warnings.append(f"channel_access_denied: {msg}")

    return None if is_apply else warnings


@bp.route("/dashboard/<guild_id>/server-builder")
@guild_access_required
def studio(guild_id: str):
    if not str(guild_id).isdigit():
        flash("Server ID không hợp lệ.", "error")
        return redirect(url_for("guild.home"))
    active_job = _job_payload(db.get_active_server_builder_job(guild_id))
    return render_template(
        "server_builder.html",
        **_server_ctx(guild_id, active_page="server_builder"),
        meta=db.get_guild_meta(guild_id) or {},
        active_job=active_job,
        bot_client_id=str(config.CLIENT_ID),
    )


@bp.route("/api/guild/<guild_id>/server-builder/tree")
def tree(guild_id: str):
    err = _api_guard(guild_id)
    if err:
        return err
    force_refresh = request.args.get("refresh") == "1"
    busted = _maybe_bust_cache_on_recent_job(guild_id)
    if force_refresh:
        invalidate_guild_channel_cache(guild_id)
        invalidate_guild_roles_cache(guild_id)
        invalidate_server_builder_tree_cache(guild_id)
    snapshot, live_source = _snapshot(guild_id, force_refresh=force_refresh or busted)
    bindings = _bindings(guild_id)
    user_id = str((session.get("user") or {}).get("id") or "")
    actor = get_actor_guild_authority(guild_id, user_id, snapshot, bypass_member_cache=False)
    if actor is None:
        actor = {
            "is_owner": False,
            "user_top_role_pos": 0,
            "administrator": False,
            "manage_guild": False,
            "manage_channels": False,
            "manage_roles": False,
            "bitfield": "0",
            "granted": [],
            "member_role_ids": [],
        }
    result = _build_tree(
        guild_id,
        snapshot.get("channels"),
        snapshot.get("roles"),
        bindings=bindings,
        live_source=live_source,
    )
    total_channels = len(result["categories"]) + sum(len(c["channels"]) for c in result["categories"]) + len(result["uncategorized"])
    result.update({
        "ok": True,
        "guild_id": str(guild_id),
        "live_source": live_source,
        "bindings": bindings,
        "is_guild_owner": bool(actor.get("is_owner")),
        "user_top_role_pos": actor.get("user_top_role_pos"),
        "user_permissions": actor,
        "bot_permissions": snapshot.get("bot_permissions") or {},
        "bot_top_role_pos": snapshot.get("bot_top_role_pos"),
        "bot_in_guild": bool(snapshot.get("bot_in_guild")),
        "guild_features": snapshot.get("guild_features") or [],
        "bitrate_limit": snapshot.get("bitrate_limit", 96000),
        "total_channels": total_channels,
        "active_job": _job_payload(db.get_active_server_builder_job(guild_id)),
    })
    return jsonify(result)


@bp.route("/api/guild/<guild_id>/server-builder/templates")
def templates(guild_id: str):
    err = _api_guard(guild_id)
    if err:
        return err
    custom = [_custom_template(item) for item in db.get_server_builder_templates(guild_id)]
    return jsonify({"ok": True, "system": _engine().get_system_presets(), "custom": custom})


@bp.route("/api/guild/<guild_id>/server-builder/templates", methods=["POST"])
@limiter.limit("10/minute")
def save_template(guild_id: str):
    err = _api_guard(guild_id)
    if err:
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    tree_data = data.get("tree")
    if not name or len(name) > 100 or len(description) > 500 or not isinstance(tree_data, dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    normalized_tree = _normalize_target_tree(tree_data, guild_id)
    validation = _engine().validate_tree_limits(normalized_tree)
    if not validation.get("ok"):
        return _validation_error(validation)
    try:
        template = db.save_server_builder_template(
            guild_id, name, description, normalized_tree, str((session.get("user") or {}).get("id") or "")
        )
    except db.TemplateLimitError as exc:
        return jsonify({"ok": False, "error": "template_limit", "message": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": "invalid_payload", "message": str(exc)}), 400
    return jsonify({"ok": True, "template": _custom_template(template)}), 201


@bp.route("/api/guild/<guild_id>/server-builder/templates/<int:template_id>", methods=["DELETE"])
def delete_template(guild_id: str, template_id: int):
    err = _api_guard(guild_id)
    if err:
        return err
    if not db.delete_server_builder_template(template_id, str(guild_id)):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/guild/<guild_id>/server-builder/preview-diff", methods=["POST"])
def preview_diff(guild_id: str):
    err = _api_guard(guild_id)
    if err:
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("tree"), dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    snapshot, live_source = _snapshot(guild_id)
    bindings = _bindings(guild_id)
    current_tree = _build_tree(
        guild_id,
        snapshot.get("channels"),
        snapshot.get("roles"),
        bindings=bindings,
        live_source=live_source,
    )
    current_tree["bindings"] = bindings
    target_tree = _normalize_target_tree(data["tree"], guild_id)
    user_id = str((session.get("user") or {}).get("id") or "")
    actor = (
        get_actor_guild_authority(guild_id, user_id, snapshot, bypass_member_cache=False)
        if live_source == "discord"
        else None
    )
    is_owner = bool(actor.get("is_owner")) if actor is not None else False
    user_top_role_pos = actor.get("user_top_role_pos") if actor is not None else None
    engine = _engine()
    validation = engine.validate_tree_limits(
        target_tree,
        snapshot.get("bot_top_role_pos"),
        is_guild_owner=is_owner,
        user_top_role_pos=user_top_role_pos,
        current_bindings=bindings,
    )
    if not validation.get("ok"):
        return _validation_error(validation)
    protected_roles = _protected_role_ids(guild_id, target_tree)
    diff = engine.compute_diff(
        current_tree,
        target_tree,
        safe_mode=bool(data.get("safe_mode", True)),
        confirm_deletions=bool(data.get("confirm_deletions", False)),
        bot_top_role_pos=snapshot.get("bot_top_role_pos"),
        is_guild_owner=is_owner,
        user_top_role_pos=user_top_role_pos,
        protected_role_ids=protected_roles,
        live_source=live_source,
    )
    if diff.get("errors"):
        return jsonify({"ok": False, "error": "invalid_tree", "errors": diff["errors"]}), 400
    priv_warnings: list[str] = []
    if actor is not None:
        priv_warnings = _enforce_actor_privilege_bounds(
            diff,
            current_tree,
            snapshot,
            actor,
            is_apply=False,
            user_id=user_id,
        ) or []
    warnings = list(dict.fromkeys(
        list(validation.get("warnings") or [])
        + list(diff.get("warnings") or [])
        + list(priv_warnings)
    ))
    return jsonify({"ok": True, "diff": diff, "live_source": live_source, "warnings": warnings})


@bp.route("/api/guild/<guild_id>/server-builder/apply", methods=["POST"])
@limiter.limit("5 per minute")
def apply(guild_id: str):
    err = _api_guard(guild_id)
    if err:
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("tree"), dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    snapshot = _get_live_structure(guild_id, force_refresh=True)
    if snapshot is None:
        return jsonify({
            "ok": False,
            "error": "discord_unavailable",
            "message": "Cannot verify live Discord guild structure and bot permissions right now.",
        }), 503
    user_id = str((session.get("user") or {}).get("id") or "")
    actor = get_actor_guild_authority(guild_id, user_id, snapshot, bypass_member_cache=True)
    if actor is None:
        return jsonify({
            "ok": False,
            "error": "user_missing_permissions",
            "message": "Cannot verify user permissions in guild.",
        }), 403

    engine = _engine()
    target_tree = _normalize_target_tree(data["tree"], guild_id)
    bindings = _bindings(guild_id)
    is_owner = bool(actor.get("is_owner"))
    user_top_role_pos = actor.get("user_top_role_pos")
    validation = engine.validate_tree_limits(
        target_tree,
        snapshot.get("bot_top_role_pos"),
        is_guild_owner=is_owner,
        user_top_role_pos=user_top_role_pos,
        current_bindings=bindings,
    )
    if not validation.get("ok"):
        val_errors = validation.get("errors") or []
        if any("user_role_hierarchy_denied" in str(e) or "user top role" in str(e) for e in val_errors):
            return jsonify({
                "ok": False,
                "error": "user_role_hierarchy_denied",
                "message": "; ".join(str(e) for e in val_errors),
            }), 403
        return _validation_error(validation)

    current_tree = _build_tree(
        guild_id,
        snapshot.get("channels"),
        snapshot.get("roles"),
        bindings=bindings,
        live_source="discord",
    )
    current_tree["bindings"] = bindings
    options = {
        "safe_mode": bool(data.get("safe_mode", True)),
        "confirm_deletions": bool(data.get("confirm_deletions", False)),
        "auto_bind_modules": bool(data.get("auto_bind_modules", True)),
        "send_guides": bool(data.get("send_guides", True)),
    }
    if not is_owner and user_top_role_pos is not None:
        options["actor_top_role_pos"] = int(user_top_role_pos)

    protected_roles = _protected_role_ids(guild_id, target_tree)
    diff = engine.compute_diff(
        current_tree,
        target_tree,
        safe_mode=options["safe_mode"],
        confirm_deletions=options["confirm_deletions"],
        bot_top_role_pos=snapshot.get("bot_top_role_pos"),
        is_guild_owner=is_owner,
        user_top_role_pos=user_top_role_pos,
        protected_role_ids=protected_roles,
        live_source="discord",
    )
    permissions = snapshot.get("bot_permissions") or {}
    administrator = bool(permissions.get("administrator"))
    missing = []
    if not (administrator or permissions.get("manage_channels")):
        missing.append("manage_channels")
    if _diff_needs_roles(diff) and not (administrator or permissions.get("manage_roles")):
        missing.append("manage_roles")
    if missing:
        return jsonify({"ok": False, "error": "bot_missing_permissions", "missing": missing}), 403

    if diff.get("errors"):
        diff_errors = diff["errors"]
        if any("user_role_hierarchy_denied" in str(e) for e in diff_errors):
            return jsonify({
                "ok": False,
                "error": "user_role_hierarchy_denied",
                "message": "; ".join(str(e) for e in diff_errors),
            }), 403
        return jsonify({"ok": False, "error": "invalid_tree", "errors": diff_errors}), 400

    priv_err = _enforce_actor_privilege_bounds(
        diff,
        current_tree,
        snapshot,
        actor,
        is_apply=True,
        user_id=user_id,
    )
    if priv_err is not None:
        return priv_err

    summary = diff.get("summary") or {}
    if summary.get("has_deletions") and not options["confirm_deletions"]:
        return jsonify({
            "ok": False,
            "error": "deletion_confirmation_required",
            "delete_targets": summary.get("delete_targets") or [],
        }), 400
    operations = diff.get("operations") or []
    plan = {
        "operations": operations,
        "summary": summary,
        "bindings": target_tree.get("bindings") or {},
    }
    try:
        job = db.create_server_builder_job(
            guild_id,
            user_id,
            plan,
            options,
            len(operations),
            float(diff.get("eta_seconds") or 0),
        )
    except db.ActiveJobExistsError as exc:
        active = getattr(exc, "job", None) or getattr(exc, "job_dict", None) or db.get_active_server_builder_job(guild_id)
        return jsonify({
            "ok": False,
            "error": "job_already_running",
            "active_job": _job_payload(active),
        }), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": "invalid_payload", "message": str(exc)}), 400
    invalidate_server_builder_tree_cache(guild_id)
    return jsonify({"ok": True, "job": _job_payload(job)}), 202


@bp.route("/api/guild/<guild_id>/server-builder/jobs/<int:job_id>")
def job_status(guild_id: str, job_id: int):
    err = _api_guard(guild_id)
    if err:
        return err
    job = db.get_server_builder_job(job_id, guild_id=str(guild_id))
    if not job:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if job.get("status") in ("completed", "cancelled", "failed"):
        invalidate_guild_channel_cache(guild_id)
        invalidate_guild_roles_cache(guild_id)
        invalidate_server_builder_tree_cache(guild_id)
    return jsonify({"ok": True, "job": _job_payload(job)})


@bp.route("/api/guild/<guild_id>/server-builder/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_job(guild_id: str, job_id: int):
    err = _api_guard(guild_id)
    if err:
        return err
    if not db.request_cancel_server_builder_job(job_id, str(guild_id)):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True})

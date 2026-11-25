"""Server Builder Studio dashboard and JSON API routes."""

import copy
import json
import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import config
import database as db
from dashboard.api import _require_guild_access
from dashboard.auth import (
    get_guild_live_structure,
    invalidate_guild_channel_cache,
    invalidate_guild_roles_cache,
    invalidate_server_builder_tree_cache,
)
from dashboard.extensions import limiter
from dashboard.web_helpers import _server_ctx, guild_access_required

bp = Blueprint("server_builder", __name__)

_PERMISSION_BITS = {
    0: "create_instant_invite",
    1: "kick_members",
    2: "ban_members",
    3: "administrator",
    4: "manage_channels",
    5: "manage_guild",
    6: "add_reactions",
    7: "view_audit_log",
    8: "priority_speaker",
    9: "stream",
    10: "view_channel",
    11: "send_messages",
    12: "send_tts_messages",
    13: "manage_messages",
    14: "embed_links",
    15: "attach_files",
    16: "read_message_history",
    17: "mention_everyone",
    18: "use_external_emojis",
    19: "view_guild_insights",
    20: "connect",
    21: "speak",
    22: "mute_members",
    23: "deafen_members",
    24: "move_members",
    25: "use_vad",
    26: "change_nickname",
    27: "manage_nicknames",
    28: "manage_roles",
    29: "manage_webhooks",
    30: "manage_guild_expressions",
    31: "use_application_commands",
    32: "request_to_speak",
    33: "manage_events",
    34: "manage_threads",
    35: "create_public_threads",
    36: "create_private_threads",
    37: "use_external_stickers",
    38: "send_messages_in_threads",
    39: "use_embedded_activities",
    40: "moderate_members",
    41: "view_creator_monetization_analytics",
    42: "use_soundboard",
    43: "create_guild_expressions",
    44: "create_events",
    45: "use_external_sounds",
    46: "send_voice_messages",
    49: "send_polls",
    50: "use_external_apps",
}

_PERMISSION_ALIASES = {
    "read_messages": "view_channel",
}


def _engine():
    try:
        import server_builder_engine as sbe
    except (ImportError, ModuleNotFoundError):
        from bot import server_builder_engine as sbe
    return sbe


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


def _permission_names(value) -> list[str]:
    if isinstance(value, list):
        names: list[str] = []
        seen: set[str] = set()
        for item in value:
            raw_name = str(item or "").strip()
            if not raw_name:
                continue
            name = _PERMISSION_ALIASES.get(raw_name, raw_name)
            if name not in seen:
                seen.add(name)
                names.append(name)
        return names
    bits = _int(value, 0)
    if bits <= 0:
        return []
    return [name for bit, name in _PERMISSION_BITS.items() if bits & (1 << bit)]


def _normalize_color_hex(value) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("#") and len(stripped) in (4, 7):
            return stripped.lower() if stripped.lower() != "#000000" else "#99aab5"
    color_int = _int(value, 0)
    return f"#{color_int:06x}" if color_int > 0 else "#99aab5"


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


def _normalize_roles(raw_roles, guild_id: str) -> list[dict]:
    roles = []
    for raw in raw_roles or []:
        if not isinstance(raw, dict):
            continue
        role_id = str(raw.get("id") or raw.get("role_id") or "")
        name = str(raw.get("name") or raw.get("role_name") or "")
        is_everyone = bool(raw.get("is_everyone")) or role_id == str(guild_id) or name == "@everyone"
        permissions = raw.get("permissions", raw.get("permission_bits", "0"))
        roles.append({
            "id": "@everyone" if is_everyone else role_id,
            "name": "@everyone" if is_everyone else name,
            "color": _normalize_color_hex(raw.get("color", raw.get("color_hex", 0))),
            "position": _int(raw.get("position"), 0),
            "permissions": _permission_names(permissions),
            "hoist": bool(raw.get("hoist", False)),
            "managed": bool(raw.get("managed", False)),
            "mentionable": bool(raw.get("mentionable", False)),
            "is_everyone": is_everyone,
        })
    roles.sort(key=lambda role: role["position"], reverse=True)
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


def _build_tree(guild_id: str, raw_channels, raw_roles, bindings: dict | None = None) -> dict:
    engine = _engine()
    channel_to_binding = _channel_binding_map(bindings)
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
        "roles": _normalize_roles(raw_roles, guild_id),
    }


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
        for role in roles:
            if not isinstance(role, dict):
                continue
            if (
                str(role.get("id") or "") == gid
                or role.get("name") == "@everyone"
                or role.get("is_everyone")
            ):
                role["id"] = "@everyone"
                role["is_everyone"] = True

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
        "roles": db.get_guild_roles(guild_id) or [],
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


def _snapshot(guild_id: str, allow_cache: bool = True):
    live = get_guild_live_structure(guild_id)
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
    }


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
    summary = diff.get("summary") or {}
    for key in ("create_roles", "sync_permissions", "update_overwrites"):
        if _int(summary.get(key), 0) > 0:
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
        if op_name in ("create_role", "sync_permissions", "update_overwrites"):
            return True
        if op_name in ("create_category", "create_channel") and operation.get("overwrites"):
            return True
        if "role" in op_name or "overwrite" in op_name or "permission" in op_name:
            return True
    return False


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
    if request.args.get("refresh") == "1":
        invalidate_server_builder_tree_cache(guild_id)
    snapshot, live_source = _snapshot(guild_id)
    bindings = _bindings(guild_id)
    result = _build_tree(guild_id, snapshot.get("channels"), snapshot.get("roles"), bindings=bindings)
    total_channels = len(result["categories"]) + sum(len(c["channels"]) for c in result["categories"]) + len(result["uncategorized"])
    result.update({
        "ok": True,
        "guild_id": str(guild_id),
        "live_source": live_source,
        "bindings": bindings,
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
    current_tree = _build_tree(guild_id, snapshot.get("channels"), snapshot.get("roles"))
    current_tree["bindings"] = _bindings(guild_id)
    target_tree = _normalize_target_tree(data["tree"], guild_id)
    validation = _engine().validate_tree_limits(target_tree, snapshot.get("bot_top_role_pos"))
    if not validation.get("ok"):
        return _validation_error(validation)
    diff = _engine().compute_diff(
        current_tree,
        target_tree,
        safe_mode=bool(data.get("safe_mode", True)),
        confirm_deletions=bool(data.get("confirm_deletions", False)),
        bot_top_role_pos=snapshot.get("bot_top_role_pos"),
    )
    if diff.get("errors"):
        return jsonify({"ok": False, "error": "invalid_tree", "errors": diff["errors"]}), 400
    warnings = list(dict.fromkeys(list(validation.get("warnings") or []) + list(diff.get("warnings") or [])))
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
    snapshot = get_guild_live_structure(guild_id)
    if snapshot is None:
        return jsonify({
            "ok": False,
            "error": "discord_unavailable",
            "message": "Cannot verify live Discord guild structure and bot permissions right now.",
        }), 503
    engine = _engine()
    target_tree = _normalize_target_tree(data["tree"], guild_id)
    validation = engine.validate_tree_limits(target_tree, snapshot.get("bot_top_role_pos"))
    if not validation.get("ok"):
        return _validation_error(validation)
    current_tree = _build_tree(guild_id, snapshot.get("channels"), snapshot.get("roles"))
    current_tree["bindings"] = _bindings(guild_id)
    options = {
        "safe_mode": bool(data.get("safe_mode", True)),
        "confirm_deletions": bool(data.get("confirm_deletions", False)),
        "auto_bind_modules": bool(data.get("auto_bind_modules", True)),
        "send_guides": bool(data.get("send_guides", True)),
    }
    diff = engine.compute_diff(
        current_tree,
        target_tree,
        safe_mode=options["safe_mode"],
        confirm_deletions=options["confirm_deletions"],
        bot_top_role_pos=snapshot.get("bot_top_role_pos"),
    )
    if diff.get("errors"):
        return jsonify({"ok": False, "error": "invalid_tree", "errors": diff["errors"]}), 400
    permissions = snapshot.get("bot_permissions") or {}
    administrator = bool(permissions.get("administrator"))
    missing = []
    if not (administrator or permissions.get("manage_channels")):
        missing.append("manage_channels")
    if _diff_needs_roles(diff) and not (administrator or permissions.get("manage_roles")):
        missing.append("manage_roles")
    if missing:
        return jsonify({"ok": False, "error": "bot_missing_permissions", "missing": missing}), 403
    summary = diff.get("summary") or {}
    if summary.get("has_deletions") and not options["confirm_deletions"]:
        return jsonify({
            "ok": False,
            "error": "deletion_confirmation_required",
            "delete_targets": summary.get("delete_targets") or [],
        }), 400
    user_id = str((session.get("user") or {}).get("id") or "")
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

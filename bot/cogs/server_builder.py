"""Background executor for persisted Server Builder jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands, tasks

import database as db
from database import (
    async_cache_channels,
    async_cache_roles,
    async_get_guild_settings,
    async_get_verify_settings,
    async_upsert_verify_settings,
    get_automod_settings,
    get_guild_settings,
    get_logger_settings,
    get_ticket_panels,
    set_logger_settings,
    upsert_automod_settings,
    upsert_guild,
)

try:
    from database import (
        async_claim_next_server_builder_job,
        async_fail_stale_server_builder_jobs,
        async_is_server_builder_cancel_requested,
        async_update_server_builder_job,
    )
except ImportError:
    async_claim_next_server_builder_job = None
    async_fail_stale_server_builder_jobs = None
    async_is_server_builder_cancel_requested = None
    async_update_server_builder_job = None

try:
    from server_builder_engine import (
        normalize_role_bind_module,
        normalize_role_color,
        permissions_to_bitfield,
        recalibrate_eta,
    )
except (ImportError, ModuleNotFoundError):
    try:
        from bot.server_builder_engine import (
            normalize_role_bind_module,
            normalize_role_color,
            permissions_to_bitfield,
            recalibrate_eta,
        )
    except (ImportError, ModuleNotFoundError):

        def normalize_role_color(value: Any) -> str:
            """Fallback canonical role color helper."""
            if value is None or isinstance(value, bool):
                return "#99aab5"
            if isinstance(value, int):
                return "#99aab5" if value <= 0 or (value & 0xFFFFFF) == 0 else f"#{value & 0xFFFFFF:06x}"
            text = str(value).strip()
            if not text:
                return "#99aab5"
            if text.isdigit():
                num = int(text)
                return "#99aab5" if num <= 0 or (num & 0xFFFFFF) == 0 else f"#{num & 0xFFFFFF:06x}"
            raw = text[1:] if text.startswith("#") else text
            if len(raw) == 3 and all(c in "0123456789abcdefABCDEF" for c in raw):
                expanded = "".join(c * 2 for c in raw).lower()
                return "#99aab5" if expanded == "000000" else f"#{expanded}"
            if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
                lowered = raw.lower()
                return "#99aab5" if lowered == "000000" else f"#{lowered}"
            return "#99aab5"

        def normalize_role_bind_module(value: Any) -> str | None:
            """Fallback canonical role module binding helper."""
            if value is None or isinstance(value, bool):
                return None
            token = str(value).strip().lower()
            aliases = {
                "autoroles_user": "autoroles_user",
                "autorole_user": "autoroles_user",
                "verify_verified": "verify_verified",
                "verify_verified_role": "verify_verified",
                "verify_pending": "verify_pending",
                "verify_pending_role": "verify_pending",
                "automod_immune": "automod_immune",
                "automod_immune_role": "automod_immune",
            }
            return aliases.get(token)

        def permissions_to_bitfield(value: Any) -> int:
            """Fallback bitfield converter."""
            if value is None or isinstance(value, bool) or value == 0 or value == "":
                return 0
            if isinstance(value, int):
                return max(0, value)
            if isinstance(value, str) and value.strip().isdigit():
                return max(0, int(value.strip()))
            return 0

        def recalibrate_eta(
            completed_steps: int,
            elapsed_seconds: float,
            remaining_baseline_cost: float,
            prev_avg: float | None = None,
            rate_limit_until: float = 0.0,
            now: float | None = None,
        ) -> tuple[float, float]:
            """Fallback EMA ETA helper until server_builder_engine is merged."""
            now_ts = time.time() if now is None else float(now)
            rl_wait = max(0.0, float(rate_limit_until or 0.0) - now_ts)
            remaining_cost = max(0.0, float(remaining_baseline_cost or 0.0))
            completed = max(0, int(completed_steps or 0))
            baseline = float(prev_avg) if prev_avg is not None and float(prev_avg) > 0 else 1.0
            if completed > 0:
                actual = max(0.0, float(elapsed_seconds or 0.0)) / completed
                ema_avg = 0.7 * actual + 0.3 * baseline
            else:
                ema_avg = baseline
            eta = remaining_cost * ema_avg + rl_wait
            return round(max(0.0, eta), 2), round(max(0.0, ema_avg), 4)


from i18n import tr

try:
    from emojis import embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import embed_title


logger = logging.getLogger("BotV2.ServerBuilder")

RENAME_WINDOW_SECONDS = 600.0
RENAME_WINDOW_LIMIT = 2
MAX_STEP_LOGS = 100
PROGRESS_FLUSH_INTERVAL = 0.4
EXPECTED_DELETE_TTL = 30.0
_ROLE_MUTATION_OPS = frozenset(
    {"create_role", "update_role", "bulk_reorder_roles", "delete_role"}
)
_DISCORD_PY_PERM_ATTR_MAP = {
    "use_vad": "use_voice_activation",
    "manage_guild_expressions": "manage_expressions",
    "create_guild_expressions": "create_expressions",
    "read_messages": "view_channel",
    "manage_permissions": "manage_roles",
    "external_emojis": "use_external_emojis",
    "external_stickers": "use_external_stickers",
    "create_polls": "send_polls",
}


class _JobCancelled(Exception):
    """Internal control-flow exception raised when job cancellation is requested."""


class _HashableTargetProxy:
    """Preserve snowflake attributes for unhashable offline-test fakes."""

    __slots__ = ("_target",)

    def __init__(self, target: Any):
        self._target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    def __hash__(self) -> int:
        return hash((type(self._target), str(getattr(self._target, "id", ""))))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _HashableTargetProxy):
            return self._target is other._target
        return self._target is other


def _hashable_target(target: Any) -> Any:
    try:
        hash(target)
    except TypeError:
        return _HashableTargetProxy(target)
    return target


def _get_db_helper(name: str, module_val: Any) -> Any:
    """Resolve DB helpers added by concurrent branches or monkeypatched in tests."""
    return module_val if module_val is not None else getattr(db, name, None)


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, type(default)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
    return default


def _channel_type_int(channel: Any) -> int:
    ctype = getattr(channel, "type", 0)
    if hasattr(ctype, "value"):
        return int(ctype.value)
    try:
        return int(ctype)
    except (TypeError, ValueError):
        return 0


def _serialize_channels(guild: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": str(channel.id),
            "name": channel.name,
            "type": _channel_type_int(channel),
        }
        for channel in getattr(guild, "channels", [])
    ]


def _role_color_hex(role: Any) -> str:
    color = getattr(role, "color", None)
    if color is None:
        return "#000000"
    if hasattr(color, "value"):
        return f"#{int(getattr(color, 'value', 0) or 0):06x}"
    if isinstance(color, int) and not isinstance(color, bool):
        return f"#{max(0, color) & 0xFFFFFF:06x}"
    if isinstance(color, str):
        cleaned = color.strip().lstrip("#")
        if len(cleaned) == 6:
            try:
                return f"#{int(cleaned, 16):06x}"
            except ValueError:
                pass
    return "#000000"


def _role_permissions_str(role: Any) -> str:
    perms = getattr(role, "permissions", None)
    if perms is None:
        return "0"
    if hasattr(perms, "value"):
        return str(int(getattr(perms, "value", 0) or 0))
    if isinstance(perms, int) and not isinstance(perms, bool):
        return str(max(0, perms))
    return str(permissions_to_bitfield(perms))


def _serialize_roles(guild: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": str(role.id),
            "name": role.name,
            "color_hex": _role_color_hex(role),
            "position": int(getattr(role, "position", 0) or 0),
            "permissions": _role_permissions_str(role),
            "hoist": bool(getattr(role, "hoist", False)),
            "mentionable": bool(getattr(role, "mentionable", False)),
            "managed": bool(getattr(role, "managed", False)),
            "is_everyone": _is_default_role(guild, role),
        }
        for role in getattr(guild, "roles", [])
    ]


def _serialize_overwrites(channel: Any, guild: Any) -> list[dict[str, Any]]:
    raw = getattr(channel, "overwrites", None) or {}
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for target, overwrite in raw.items():
        if overwrite is None:
            continue
        allow: list[str] = []
        deny: list[str] = []
        try:
            for perm_name, perm_val in overwrite:
                if perm_val is True:
                    allow.append(str(perm_name))
                elif perm_val is False:
                    deny.append(str(perm_name))
        except TypeError:
            continue
        if not allow and not deny:
            continue
        is_role = isinstance(target, discord.Role) or hasattr(target, "position")
        is_default = _is_default_role(guild, target)
        tid = "@everyone" if is_default else str(getattr(target, "id", ""))
        if not tid:
            continue
        out.append(
            {
                "id": tid,
                "type": "role" if is_role else "member",
                "allow": sorted(allow),
                "deny": sorted(deny),
            }
        )
    return out


def _snapshot(guild: Any) -> dict[str, Any]:
    categories = []
    for cat in sorted(getattr(guild, "categories", []), key=lambda c: int(getattr(c, "position", 0) or 0)):
        categories.append(
            {
                "id": str(cat.id),
                "name": cat.name,
                "position": int(getattr(cat, "position", 0) or 0),
                "overwrites": _serialize_overwrites(cat, guild),
            }
        )

    channels = []
    for ch in sorted(getattr(guild, "channels", []), key=lambda c: int(getattr(c, "position", 0) or 0)):
        ctype = _channel_type_int(ch)
        if ctype == 4 or isinstance(ch, discord.CategoryChannel):
            continue
        parent_id = getattr(ch, "category_id", None)
        if parent_id is None and getattr(ch, "category", None) is not None:
            parent_id = getattr(ch.category, "id", None)
        channels.append(
            {
                "id": str(ch.id),
                "name": ch.name,
                "type": ctype,
                "parent_id": str(parent_id) if parent_id is not None else None,
                "position": int(getattr(ch, "position", 0) or 0),
                "topic": str(getattr(ch, "topic", "") or ""),
                "slowmode": int(getattr(ch, "slowmode_delay", 0) or 0),
                "nsfw": bool(getattr(ch, "nsfw", False)),
                "bitrate": int(getattr(ch, "bitrate", 64000) or 64000),
                "user_limit": int(getattr(ch, "user_limit", 0) or 0),
                "overwrites": _serialize_overwrites(ch, guild),
            }
        )

    return {
        "guild_id": str(guild.id),
        "captured_at": time.time(),
        "roles": _serialize_roles(guild),
        "categories": categories,
        "channels": channels,
    }


def _as_id(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return text


def _color(value: Any) -> discord.Color:
    if isinstance(value, discord.Color):
        return value
    norm = normalize_role_color(value)
    if norm == "#99aab5":
        return discord.Color.default()
    return discord.Color(int(norm.lstrip("#"), 16))


def _permissions(value: Any) -> discord.Permissions:
    if isinstance(value, discord.Permissions):
        return value
    return discord.Permissions(permissions_to_bitfield(value))


def _unwrap_change_value(value: Any) -> Any:
    if isinstance(value, dict) and "new" in value:
        return value["new"]
    return value


def _extract_role_permissions(changes: dict[str, Any]) -> discord.Permissions | None:
    if "permissions" not in changes and "permissions_bitfield" not in changes:
        return None
    raw_bf = _unwrap_change_value(changes.get("permissions_bitfield"))
    raw_perm = raw_bf if ("permissions_bitfield" in changes and raw_bf is not None) else _unwrap_change_value(changes.get("permissions"))
    return _permissions(raw_perm)


def _parse_role_id_list(raw_value: Any) -> list[str]:
    items = _json_value(raw_value, []) if isinstance(raw_value, str) else (raw_value if isinstance(raw_value, list) else [])
    return [str(x).strip() for x in items if str(x).strip()]


def _update_primary_role_list(
    raw_value: Any, *, new_role_id: str | None = None
) -> list[str]:
    existing = _parse_role_id_list(raw_value)
    if new_role_id is None:
        return existing[1:] if existing else []
    if existing and existing[0] == new_role_id:
        return existing
    if existing:
        return [new_role_id] + [x for x in existing[1:] if x != new_role_id]
    return [new_role_id]


def _is_default_role(guild: Any, role: Any) -> bool:
    if role is None:
        return False
    default_role = getattr(guild, "default_role", None)
    if default_role is not None and role is default_role:
        return True
    if str(getattr(role, "id", "")) == str(getattr(guild, "id", "")):
        return True
    is_def = getattr(role, "is_default", None)
    if callable(is_def):
        try:
            return bool(is_def())
        except Exception:
            return False
    return False


class ServerBuilder(commands.Cog, name="ServerBuilder"):
    """Background worker executing queued Server Builder jobs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stale_recovered = False
        self._guild_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._rename_history: defaultdict[str, deque[float]] = defaultdict(deque)
        self.worker_loop.start()

    def cog_unload(self) -> None:
        self.worker_loop.cancel()

    async def _db_update(self, job_id: Any, **fields: Any) -> None:
        helper = _get_db_helper(
            "async_update_server_builder_job", async_update_server_builder_job
        )
        if helper is not None:
            await helper(job_id, **fields)

    async def _cancel_requested(self, job_id: Any) -> bool:
        helper = _get_db_helper(
            "async_is_server_builder_cancel_requested",
            async_is_server_builder_cancel_requested,
        )
        return bool(await helper(job_id)) if helper is not None else False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._stale_recovered:
            return
        self._stale_recovered = True
        helper = _get_db_helper(
            "async_fail_stale_server_builder_jobs", async_fail_stale_server_builder_jobs
        )
        if helper is not None:
            try:
                recovered = await helper()
                if recovered:
                    logger.info("[ServerBuilder] Marked %d stale job(s) failed on startup", recovered)
            except Exception as exc:
                logger.warning("[ServerBuilder] Stale job recovery failed: %s", exc)

    @tasks.loop(seconds=2.0)
    async def worker_loop(self) -> None:
        try:
            claim = _get_db_helper(
                "async_claim_next_server_builder_job", async_claim_next_server_builder_job
            )
            if claim is None:
                return
            job = await claim()
            if not job:
                return
            guild_id = str(job.get("guild_id") or "")
            async with self._guild_locks[guild_id]:
                await self._execute_job(job)
        except Exception:
            logger.exception("[ServerBuilder] Unhandled error in worker_loop")

    @worker_loop.before_loop
    async def before_worker_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _rest_call(
        self,
        job_id: Any,
        call: Callable[..., Awaitable[Any]],
        *args: Any,
        step_label: str = "",
        logs: list[dict[str, Any]] | None = None,
        remaining_cost: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        try:
            return await call(*args, **kwargs)
        except Exception as exc:
            rate_limited = isinstance(exc, getattr(discord, "RateLimited", ()))
            rate_limited = rate_limited or (
                isinstance(exc, discord.HTTPException)
                and getattr(exc, "status", None) == 429
            )
            if not rate_limited:
                raise

            raw_retry = getattr(exc, "retry_after", None)
            if raw_retry is None:
                headers = getattr(getattr(exc, "response", None), "headers", None) or {}
                raw_retry = headers.get("Retry-After", 10.0)
            try:
                retry_after = float(raw_retry)
            except (TypeError, ValueError):
                retry_after = 10.0
            retry_after = max(0.5, min(retry_after, 900.0))

            until = time.time() + retry_after
            if logs is not None:
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Discord rate limit hit ({retry_after:.1f}s) during: {step_label or 'REST call'}",
                    }
                )
            update_fields: dict[str, Any] = {
                "status": "paused_rl",
                "rate_limit_until": until,
                "eta_seconds": round(max(0.0, float(remaining_cost) + retry_after), 2),
            }
            if step_label:
                update_fields["current_step_label"] = step_label
            if logs is not None:
                update_fields["step_logs_json"] = json.dumps(logs[-MAX_STEP_LOGS:], ensure_ascii=False)
            await self._db_update(job_id, **update_fields)

            while True:
                if await self._cancel_requested(job_id):
                    raise _JobCancelled
                remaining = until - time.time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(1.0, remaining))

            if await self._cancel_requested(job_id):
                raise _JobCancelled

            await self._db_update(job_id, status="running", rate_limit_until=0)
            return await call(*args, **kwargs)

    def _resolve_id(self, value: Any, id_map: dict[str, str]) -> Any:
        if value is None:
            return None
        return id_map.get(str(value), value)

    def _bot_top_position(self, guild: Any) -> int | None:
        me = getattr(guild, "me", None)
        top_role = getattr(me, "top_role", None) if me is not None else None
        pos = getattr(top_role, "position", None) if top_role is not None else None
        return int(pos) if pos is not None else None

    def _get_expected_deletes(self) -> dict[tuple[str, str, str], float] | None:
        sb_expected = getattr(self.bot, "_sb_expected_deletes", None)
        if not isinstance(sb_expected, dict):
            sb_expected = {}
            try:
                setattr(self.bot, "_sb_expected_deletes", sb_expected)
            except Exception:
                return None
        return sb_expected

    def _register_expected_delete(self, guild_id: Any, kind: str, target_id: Any) -> None:
        sb_expected = self._get_expected_deletes()
        if sb_expected is None:
            return
        mono_now = time.monotonic()
        if len(sb_expected) > 1000:
            for key in [k for k, exp in list(sb_expected.items()) if exp <= mono_now]:
                sb_expected.pop(key, None)
        sb_expected[(str(guild_id), str(kind), str(target_id))] = mono_now + EXPECTED_DELETE_TTL

    def _clear_expected_delete(self, guild_id: Any, kind: str, target_id: Any) -> None:
        sb_expected = getattr(self.bot, "_sb_expected_deletes", None)
        if isinstance(sb_expected, dict):
            sb_expected.pop((str(guild_id), str(kind), str(target_id)), None)

    def _get_role(self, guild: Any, value: Any, id_map: dict[str, str]) -> Any:
        resolved = self._resolve_id(value, id_map)
        if resolved is None:
            return None
        if str(resolved) == "@everyone" or str(resolved) == str(getattr(guild, "id", "")):
            default_role = getattr(guild, "default_role", None)
            if default_role is not None:
                return default_role
            for role in getattr(guild, "roles", []):
                if _is_default_role(guild, role):
                    return role
            if str(resolved) == "@everyone":
                return None
        try:
            role_id = int(resolved)
        except (TypeError, ValueError):
            return None
        getter = getattr(guild, "get_role", None)
        if getter:
            role = getter(role_id)
            if role is not None:
                return role
        return next(
            (role for role in getattr(guild, "roles", []) if int(role.id) == role_id),
            None,
        )

    def _owned_role(
        self,
        guild: Any,
        value: Any,
        id_map: dict[str, str],
        *,
        actor_top_pos: int | None = None,
    ) -> Any:
        role = self._get_role(guild, value, id_map)
        if role is None:
            return None
        if _is_default_role(guild, role) or getattr(role, "managed", False):
            return None
        roles_in_guild = getattr(guild, "roles", ()) or ()
        if roles_in_guild and not any(
            r is role or str(getattr(r, "id", "")) == str(getattr(role, "id", ""))
            for r in roles_in_guild
        ):
            return None
        owner = getattr(role, "guild", None)
        if owner is not None and str(owner.id) != str(guild.id):
            return None
        top_position = self._bot_top_position(guild)
        role_pos = int(getattr(role, "position", 0) or 0)
        if top_position is not None and role_pos >= top_position:
            return None
        if actor_top_pos is not None and role_pos >= actor_top_pos:
            return None
        return role

    async def _protected_role_ids(self, guild_id: str) -> set[str]:
        """Collect live DB role IDs actively bound to admin, verify, or ticket modules."""
        protected: set[str] = set()
        try:
            gs = await asyncio.to_thread(get_guild_settings, guild_id)
            raw_admin = (gs or {}).get("bot_admin_roles")
            admin_list = (
                _json_value(raw_admin, [])
                if isinstance(raw_admin, str)
                else (raw_admin if isinstance(raw_admin, list) else [])
            )
            for rid in admin_list:
                token = str(rid or "").strip()
                if token:
                    protected.add(token)
        except Exception:
            logger.warning(
                "[ServerBuilder] Failed reading bot_admin_roles for %s",
                guild_id,
                exc_info=True,
            )

        try:
            vs = await async_get_verify_settings(guild_id)
            if int((vs or {}).get("enabled", 0) or 0) == 1:
                for key in ("verified_role_id", "pending_role_id"):
                    token = str((vs or {}).get(key) or "").strip()
                    if token:
                        protected.add(token)
        except Exception:
            logger.warning(
                "[ServerBuilder] Failed reading verify_settings for %s",
                guild_id,
                exc_info=True,
            )

        try:
            panels = await asyncio.to_thread(get_ticket_panels, guild_id)
            for panel in panels or []:
                if not isinstance(panel, dict):
                    continue
                raw_sup = str(panel.get("support_role_id") or "").strip()
                if not raw_sup:
                    continue
                if raw_sup.startswith("["):
                    for item in _json_value(raw_sup, []):
                        token = str(item or "").strip()
                        if token:
                            protected.add(token)
                else:
                    for part in raw_sup.split(","):
                        token = part.strip()
                        if token:
                            protected.add(token)
        except Exception:
            logger.warning(
                "[ServerBuilder] Failed reading ticket_panels for %s",
                guild_id,
                exc_info=True,
            )

        return protected

    def _actor_role_gate(
        self,
        guild: Any,
        actor_user_id: str,
        options: dict[str, Any],
    ) -> tuple[bool, int | None]:
        """Gate 4 TOCTOU check: verify live Gateway actor permissions and top_role ceiling."""
        raw_opt_top = options.get("actor_top_role_pos")
        opt_top: int | None = None
        if raw_opt_top is not None and not isinstance(raw_opt_top, bool):
            try:
                opt_top = int(raw_opt_top)
            except (TypeError, ValueError):
                opt_top = None

        guild_owner_id = getattr(guild, "owner_id", None)
        if (
            actor_user_id.isdigit()
            and guild_owner_id is not None
            and str(guild_owner_id) == actor_user_id
        ):
            return False, None

        actor_revoked_roles = False
        live_actor_top_pos: int | None = None
        if (
            actor_user_id.isdigit()
            and (guild_owner_id is None or str(guild_owner_id) != actor_user_id)
            and hasattr(guild, "get_member")
        ):
            try:
                actor_member = guild.get_member(int(actor_user_id))
            except (TypeError, ValueError):
                actor_member = None
            if actor_member is not None:
                perms = getattr(actor_member, "guild_permissions", None)
                if perms is not None and not (
                    bool(getattr(perms, "administrator", False))
                    or bool(getattr(perms, "manage_roles", False))
                ):
                    actor_revoked_roles = True
                top_role = getattr(actor_member, "top_role", None)
                raw_live_pos = getattr(top_role, "position", None) if top_role is not None else None
                if raw_live_pos is not None and not isinstance(raw_live_pos, bool):
                    try:
                        live_actor_top_pos = int(raw_live_pos)
                    except (TypeError, ValueError):
                        live_actor_top_pos = None

        if opt_top is not None and live_actor_top_pos is not None:
            effective_top = min(opt_top, live_actor_top_pos)
        else:
            effective_top = live_actor_top_pos if live_actor_top_pos is not None else opt_top
        return actor_revoked_roles, effective_top

    def _get_channel(self, guild: Any, value: Any, id_map: dict[str, str]) -> Any:
        resolved = self._resolve_id(value, id_map)
        if resolved is None:
            return None
        try:
            channel_id = int(resolved)
        except (TypeError, ValueError):
            return None
        getter = getattr(guild, "get_channel", None)
        if getter:
            channel = getter(channel_id)
            if channel is not None:
                return channel
        return next(
            (
                channel
                for channel in getattr(guild, "channels", [])
                if int(channel.id) == channel_id
            ),
            None,
        )

    def _owned_channel(self, guild: Any, value: Any, id_map: dict[str, str]) -> Any:
        channel = self._get_channel(guild, value, id_map)
        if channel is None:
            return None
        owner = getattr(channel, "guild", None)
        if owner is not None and str(owner.id) != str(guild.id):
            return None
        return channel

    def _overwrite_target(
        self, guild: Any, entry: dict[str, Any], id_map: dict[str, str]
    ) -> Any:
        target_id = self._resolve_id(entry.get("id"), id_map)
        if target_id is None:
            return None
        if str(target_id) == "@everyone" or str(target_id) == str(getattr(guild, "id", "")):
            return getattr(guild, "default_role", None)
        if str(entry.get("type") or "role").lower() == "member":
            try:
                return guild.get_member(int(target_id))
            except (AttributeError, TypeError, ValueError):
                return None
        return self._get_role(guild, target_id, id_map)

    def _build_overwrites(
        self,
        guild: Any,
        entries: Any,
        id_map: dict[str, str],
        logs: list[dict[str, Any]],
        *,
        skip_high_roles: bool = True,
        preserve_from: Any = None,
    ) -> tuple[dict[Any, discord.PermissionOverwrite], int, int]:
        overwrites: dict[Any, discord.PermissionOverwrite] = {}
        top_position = self._bot_top_position(guild)
        valid_names = getattr(discord.PermissionOverwrite, "VALID_NAMES", None)
        applied_count = 0
        skipped_count = 0

        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            target = self._overwrite_target(guild, entry, id_map)
            if target is None:
                skipped_count += 1
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Skipped overwrite for missing target {entry.get('id')}",
                    }
                )
                continue

            is_role = str(entry.get("type") or "role").lower() == "role"
            if (
                skip_high_roles
                and is_role
                and not _is_default_role(guild, target)
                and top_position is not None
                and int(getattr(target, "position", -1)) >= top_position
            ):
                skipped_count += 1
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Skipped overwrite for role {getattr(target, 'name', target.id)} (>= bot top role)",
                    }
                )
                continue

            ow_kwargs: dict[str, bool] = {}
            for name in entry.get("allow", []) or []:
                raw_perm = str(name).strip()
                perm_name = _DISCORD_PY_PERM_ATTR_MAP.get(raw_perm, raw_perm)
                if valid_names is None or perm_name in valid_names:
                    ow_kwargs[perm_name] = True
                else:
                    logs.append({"level": "warning", "message": f"Unknown permission {raw_perm}"})
            for name in entry.get("deny", []) or []:
                raw_perm = str(name).strip()
                perm_name = _DISCORD_PY_PERM_ATTR_MAP.get(raw_perm, raw_perm)
                if valid_names is None or perm_name in valid_names:
                    ow_kwargs[perm_name] = False
                else:
                    logs.append({"level": "warning", "message": f"Unknown permission {raw_perm}"})

            if ow_kwargs:
                overwrites[_hashable_target(target)] = discord.PermissionOverwrite(**ow_kwargs)
                applied_count += 1

        if preserve_from is not None and top_position is not None:
            existing = getattr(preserve_from, "overwrites", {}) or {}
            for target, overwrite in existing.items():
                if (
                    not _is_default_role(guild, target)
                    and hasattr(target, "position")
                    and int(getattr(target, "position", -1)) >= top_position
                    and target not in overwrites
                ):
                    overwrites[target] = overwrite
                    logs.append(
                        {
                            "level": "warning",
                            "message": f"Preserved higher-role overwrite {getattr(target, 'name', target.id)}",
                        }
                    )

        return overwrites, applied_count, skipped_count

    def _apply_verify_gate(
        self,
        overwrites: dict[Any, discord.PermissionOverwrite],
        pending_role: Any,
    ) -> None:
        target = _hashable_target(pending_role)
        current = overwrites.get(target)
        if current is None:
            overwrites[target] = discord.PermissionOverwrite(view_channel=False)
        else:
            current.view_channel = False

    def _channel_type(self, operation: dict[str, Any]) -> int:
        value = operation.get("type", operation.get("channel_type", 0))
        names = {
            "text": 0,
            "voice": 2,
            "category": 4,
            "announcement": 5,
            "news": 5,
            "stage": 13,
            "forum": 15,
        }
        if isinstance(value, str) and not value.isdigit():
            return names.get(value.lower(), 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def _create_channel(
        self,
        job_id: Any,
        guild: Any,
        operation: dict[str, Any],
        id_map: dict[str, str],
        overwrites: dict[Any, discord.PermissionOverwrite],
        reason: str,
        logs: list[dict[str, Any]],
        step_label: str,
        remaining_cost: float,
    ) -> Any:
        category_ref = operation.get("category_temp_id") or operation.get("category_id")
        category = self._get_channel(guild, category_ref, id_map)
        if category_ref is not None and category is None:
            raise LookupError(f"Category {category_ref} was not found")
        channel_type = self._channel_type(operation)
        features = {str(item).upper() for item in (getattr(guild, "features", ()) or ())}
        if channel_type == 5 and "COMMUNITY" not in features:
            channel_type = 0
            logs.append(
                {
                    "level": "warning",
                    "message": (
                        f"Guild lacks COMMUNITY feature; falling back announcement channel "
                        f"'{operation.get('name', 'channel')}' to text channel"
                    ),
                }
            )

        common: dict[str, Any] = {
            "name": str(operation.get("name") or "channel")[:100],
            "reason": reason,
        }
        if category is not None:
            common["category"] = category
        if overwrites:
            common["overwrites"] = overwrites
        if operation.get("position") is not None:
            common["position"] = int(operation["position"])

        if channel_type == 2:
            limit = int(getattr(guild, "bitrate_limit", 96000) or 96000)
            raw_bitrate = int(operation.get("bitrate") or 64000)
            common["bitrate"] = max(8000, min(raw_bitrate, limit))
            common["user_limit"] = max(0, min(99, int(operation.get("user_limit") or 0)))
            if operation.get("nsfw") is not None:
                common["nsfw"] = bool(operation["nsfw"])
            return await self._rest_call(
                job_id,
                guild.create_voice_channel,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                **common,
            )

        if channel_type == 13 and hasattr(guild, "create_stage_channel"):
            limit = int(getattr(guild, "bitrate_limit", 96000) or 96000)
            raw_bitrate = int(operation.get("bitrate") or 64000)
            common["bitrate"] = max(8000, min(raw_bitrate, limit))
            common["user_limit"] = max(0, min(99, int(operation.get("user_limit") or 0)))
            return await self._rest_call(
                job_id,
                guild.create_stage_channel,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                **common,
            )

        if channel_type == 15 and hasattr(guild, "create_forum"):
            topic = str(operation.get("topic") or "").strip()
            if topic:
                common["topic"] = topic[:1024]
            common["nsfw"] = bool(operation.get("nsfw", False))
            common["slowmode_delay"] = max(0, min(21600, int(operation.get("slowmode") or 0)))
            return await self._rest_call(
                job_id,
                guild.create_forum,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                **common,
            )

        topic = str(operation.get("topic") or "").strip()
        if topic:
            common["topic"] = topic[:1024]
        common["slowmode_delay"] = max(0, min(21600, int(operation.get("slowmode") or 0)))
        common["nsfw"] = bool(operation.get("nsfw", False))
        common["news"] = channel_type == 5
        return await self._rest_call(
            job_id,
            guild.create_text_channel,
            step_label=step_label,
            logs=logs,
            remaining_cost=remaining_cost,
            **common,
        )

    async def _run_operation(
        self,
        job_id: Any,
        guild: Any,
        operation: dict[str, Any],
        options: dict[str, Any],
        id_map: dict[str, str],
        discovered_bindings: dict[str, str],
        reason: str,
        logs: list[dict[str, Any]],
        pending_role: Any,
        verify_channel_id: str | None,
        verify_refs: set[str],
        step_label: str,
        remaining_cost: float,
        *,
        has_bulk_role_reorder: bool = False,
        actor_top_pos: int | None = None,
    ) -> None:
        op = operation.get("op")

        if op == "create_role":
            position = operation.get("target_position", operation.get("position"))
            top_position = self._bot_top_position(guild)
            perm_src = (
                operation.get("permissions_bitfield")
                if operation.get("permissions_bitfield") is not None
                else operation.get("permissions")
            )

            role = await self._rest_call(
                job_id,
                guild.create_role,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                name=str(operation.get("name") or "new-role")[:100],
                colour=_color(operation.get("color")),
                permissions=_permissions(perm_src),
                hoist=bool(operation.get("hoist", False)),
                mentionable=bool(operation.get("mentionable", False)),
                reason=reason,
            )
            if operation.get("temp_id") is not None:
                id_map[str(operation["temp_id"])] = str(role.id)
            raw_bind_mod = operation.get("bind_role_module")
            if raw_bind_mod:
                norm_bind_mod = normalize_role_bind_module(raw_bind_mod)
                bind_key = norm_bind_mod or str(raw_bind_mod).strip()
                if bind_key and bind_key.lower() not in {"none", "null", "undefined"}:
                    discovered_bindings[bind_key] = str(role.id)

            if not operation.get("defer_position") and not has_bulk_role_reorder:
                if position is not None and int(position) > 0:
                    desired_pos = int(position)
                    ceilings = [c for c in (top_position, actor_top_pos) if c is not None]
                    ceiling = min(ceilings) if ceilings else None
                    if ceiling is not None and ceiling <= 1:
                        if desired_pos >= ceiling:
                            logs.append(
                                {
                                    "level": "warning",
                                    "message": (
                                        f"Created role '{role.name}' at default position; "
                                        f"cannot reposition above hierarchy ceiling ({ceiling})"
                                    ),
                                }
                            )
                    else:
                        target_pos = (
                            min(desired_pos, ceiling - 1)
                            if ceiling is not None
                            else desired_pos
                        )
                        if target_pos != desired_pos:
                            logs.append(
                                {
                                    "level": "warning",
                                    "message": (
                                        f"Clamped role '{role.name}' position from {desired_pos} "
                                        f"to {target_pos} (below hierarchy ceiling {ceiling})"
                                    ),
                                }
                            )
                        if target_pos > 0:
                            try:
                                await self._rest_call(
                                    job_id,
                                    role.edit,
                                    step_label=step_label,
                                    logs=logs,
                                    remaining_cost=remaining_cost,
                                    position=target_pos,
                                    reason=reason,
                                )
                            except (discord.Forbidden, discord.HTTPException) as exc:
                                logs.append(
                                    {
                                        "level": "warning",
                                        "message": f"Created role '{role.name}' but could not set position {target_pos}: {exc}",
                                    }
                                )
            return

        if op == "update_role":
            role = self._get_role(guild, operation.get("role_id"), id_map)
            if role is None:
                raise LookupError(f"Role {operation.get('role_id')} for update was not found")
            if getattr(role, "managed", False):
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Skipped managed role '{getattr(role, 'name', role.id)}'",
                    }
                )
                return

            changes = dict(operation.get("changes") or {})
            parsed_perms = _extract_role_permissions(changes)
            if _is_default_role(guild, role):
                if parsed_perms is not None:
                    await self._rest_call(
                        job_id,
                        role.edit,
                        step_label=step_label,
                        logs=logs,
                        remaining_cost=remaining_cost,
                        permissions=parsed_perms,
                        reason=reason,
                    )
                return

            role_pos = int(getattr(role, "position", 0) or 0)
            if actor_top_pos is not None and role_pos >= actor_top_pos:
                raise PermissionError(
                    f"Role '{getattr(role, 'name', role.id)}' position ({role_pos}) >= actor top role ({actor_top_pos})"
                )

            top_position = self._bot_top_position(guild)
            if top_position is not None and role_pos >= top_position:
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Skipped update for role '{getattr(role, 'name', role.id)}' "
                            f"(position {role_pos} >= bot top role {top_position})"
                        ),
                    }
                )
                return

            edit_kwargs: dict[str, Any] = {}
            if "name" in changes:
                new_name = str(_unwrap_change_value(changes["name"]) or "").strip()[:100]
                if new_name:
                    edit_kwargs["name"] = new_name
            if "color" in changes or "colour" in changes or "color_hex" in changes:
                color_key = (
                    "color"
                    if "color" in changes
                    else ("colour" if "colour" in changes else "color_hex")
                )
                edit_kwargs["colour"] = _color(_unwrap_change_value(changes[color_key]))
            if "hoist" in changes:
                edit_kwargs["hoist"] = bool(_unwrap_change_value(changes["hoist"]))
            if "mentionable" in changes:
                edit_kwargs["mentionable"] = bool(_unwrap_change_value(changes["mentionable"]))
            if parsed_perms is not None:
                edit_kwargs["permissions"] = parsed_perms

            if edit_kwargs:
                await self._rest_call(
                    job_id,
                    role.edit,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    reason=reason,
                    **edit_kwargs,
                )
            return

        if op == "bulk_reorder_roles":
            top_position = self._bot_top_position(guild)
            if top_position is not None and top_position <= 1:
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Skipped bulk role reorder: bot top role position ({top_position}) "
                            f"allows no movable slots"
                        ),
                    }
                )
                return
            if actor_top_pos is not None and actor_top_pos <= 1:
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Skipped bulk role reorder: actor top role position ({actor_top_pos}) "
                            f"allows no movable slots"
                        ),
                    }
                )
                return

            ceilings: list[int] = []
            if top_position is not None:
                ceilings.append(top_position - 1)
            if actor_top_pos is not None and actor_top_pos >= 1:
                ceilings.append(actor_top_pos - 1)
            max_pos = min(ceilings) if ceilings else None
            if max_pos is not None and max_pos < 1:
                logs.append(
                    {
                        "level": "warning",
                        "message": "Skipped bulk role reorder: no valid position below hierarchy ceiling",
                    }
                )
                return

            resolved_entries: list[tuple[int, int, Any]] = []
            seen_role_ids: set[str] = set()
            for idx, item in enumerate(operation.get("items", []) or []):
                if not isinstance(item, dict):
                    continue
                ref = item.get("temp_id") if item.get("temp_id") is not None else item.get("id")
                role = self._get_role(guild, ref, id_map)
                if role is None:
                    logs.append(
                        {
                            "level": "warning",
                            "message": f"Skipped missing role {ref} in bulk_reorder_roles",
                        }
                    )
                    continue
                rid = str(getattr(role, "id", ""))
                if rid in seen_role_ids:
                    continue
                if _is_default_role(guild, role) or getattr(role, "managed", False):
                    continue
                role_pos = int(getattr(role, "position", 0) or 0)
                if top_position is not None and role_pos >= top_position:
                    logs.append(
                        {
                            "level": "warning",
                            "message": (
                                f"Skipped role '{getattr(role, 'name', rid)}' "
                                f"(>= bot top role {top_position}) in reorder"
                            ),
                        }
                    )
                    continue
                if actor_top_pos is not None and role_pos >= actor_top_pos:
                    logs.append(
                        {
                            "level": "warning",
                            "message": (
                                f"Skipped role '{getattr(role, 'name', rid)}' "
                                f"(>= actor top role {actor_top_pos}) in reorder"
                            ),
                        }
                    )
                    continue
                try:
                    raw_pos = int(item.get("position", 1))
                except (TypeError, ValueError):
                    raw_pos = 1
                clamped_pos = max(1, min(raw_pos, max_pos)) if max_pos is not None else max(1, raw_pos)
                seen_role_ids.add(rid)
                resolved_entries.append((clamped_pos, idx, role))

            if not resolved_entries:
                return

            resolved_entries.sort(key=lambda entry: (entry[0], entry[1]))
            assigned_positions: list[int] = [entry[0] for entry in resolved_entries]
            if len(set(assigned_positions)) < len(assigned_positions):
                next_cap = assigned_positions[-1]
                for i in range(len(assigned_positions) - 1, -1, -1):
                    pos = max(1, min(assigned_positions[i], next_cap))
                    assigned_positions[i] = pos
                    next_cap = max(1, pos - 1)

            positions_dict: dict[Any, int] = {
                _hashable_target(role): pos
                for (_, _, role), pos in zip(resolved_entries, assigned_positions)
            }

            if hasattr(guild, "edit_role_positions"):
                await self._rest_call(
                    job_id,
                    guild.edit_role_positions,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    positions=positions_dict,
                    reason=reason,
                )
            else:
                http = getattr(getattr(guild, "_state", None), "http", None)
                if http is not None and hasattr(http, "move_role_position"):
                    payload = [
                        {"id": _as_id(r.id), "position": pos}
                        for r, pos in positions_dict.items()
                    ]
                    await self._rest_call(
                        job_id,
                        http.move_role_position,
                        guild.id,
                        payload,
                        step_label=step_label,
                        logs=logs,
                        remaining_cost=remaining_cost,
                        reason=reason,
                    )
                else:
                    logs.append(
                        {
                            "level": "warning",
                            "message": (
                                "Guild object exposes neither edit_role_positions nor "
                                "http.move_role_position; falling back to sequential role.edit"
                            ),
                        }
                    )
                    for role_proxy, pos in positions_dict.items():
                        if hasattr(role_proxy, "edit"):
                            await self._rest_call(
                                job_id,
                                role_proxy.edit,
                                step_label=step_label,
                                logs=logs,
                                remaining_cost=remaining_cost,
                                position=pos,
                                reason=reason,
                            )
            return

        if op in {"create_category", "create_channel"}:
            overwrites, _, _ = self._build_overwrites(
                guild, operation.get("overwrites", []), id_map, logs, skip_high_roles=True
            )
            temp_id = str(operation.get("temp_id") or "")
            op_id = str(operation.get("id") or "")
            is_verify_channel = (op == "create_channel") and (
                operation.get("bind_module") == "verify"
                or (bool(temp_id) and temp_id in verify_refs)
                or (
                    bool(verify_channel_id)
                    and ((temp_id == verify_channel_id) or (op_id == verify_channel_id))
                )
            )
            if pending_role is not None and not is_verify_channel:
                self._apply_verify_gate(overwrites, pending_role)

            if op == "create_category":
                kwargs: dict[str, Any] = {
                    "name": str(operation.get("name") or "Category")[:100],
                    "reason": reason,
                }
                if overwrites:
                    kwargs["overwrites"] = overwrites
                if operation.get("position") is not None:
                    kwargs["position"] = int(operation["position"])
                created = await self._rest_call(
                    job_id,
                    guild.create_category,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    **kwargs,
                )
            else:
                created = await self._create_channel(
                    job_id,
                    guild,
                    operation,
                    id_map,
                    overwrites,
                    reason,
                    logs,
                    step_label,
                    remaining_cost,
                )
                if (
                    pending_role is not None
                    and is_verify_channel
                    and not overwrites
                ):
                    parent_cat = getattr(created, "category", None)
                    parent_ows = getattr(parent_cat, "overwrites", {}) or {}
                    parent_pending_ow = parent_ows.get(_hashable_target(pending_role))
                    if parent_pending_ow is not None and getattr(parent_pending_ow, "view_channel", None) is False:
                        await self._rest_call(
                            job_id,
                            created.set_permissions,
                            pending_role,
                            overwrite=discord.PermissionOverwrite(view_channel=True),
                            step_label=step_label,
                            logs=logs,
                            remaining_cost=remaining_cost,
                            reason=reason,
                        )
                if operation.get("bind_module"):
                    discovered_bindings[str(operation["bind_module"])] = str(created.id)

            if temp_id:
                id_map[temp_id] = str(created.id)
            return

        if op == "sync_permissions":
            channel = self._get_channel(guild, operation.get("channel_id"), id_map)
            if channel is None:
                raise LookupError("Channel for permission sync was not found")

            category_ref = operation.get("category_temp_id") or operation.get("category_id")
            category = self._get_channel(guild, category_ref, id_map)
            if category_ref is None or category is None:
                raise LookupError(f"Category {category_ref} for permission sync was not found")
            top_position = self._bot_top_position(guild)
            for role in (getattr(category, "overwrites", {}) or {}):
                if (
                    not _is_default_role(guild, role)
                    and top_position is not None
                    and int(getattr(role, "position", -1)) >= top_position
                ):
                    logs.append(
                        {
                            "level": "warning",
                            "message": f"Permission sync references higher role {getattr(role, 'name', getattr(role, 'id', ''))}",
                        }
                    )

            edit_kwargs: dict[str, Any] = {"sync_permissions": True, "reason": reason}
            if category is not None and str(getattr(channel, "category_id", "") or "") != str(category.id):
                edit_kwargs["category"] = category
            await self._rest_call(
                job_id,
                channel.edit,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                **edit_kwargs,
            )
            return

        if op == "update_overwrites":
            channel = self._get_channel(guild, operation.get("channel_id"), id_map)
            if channel is None:
                raise LookupError("Channel for overwrite update was not found")

            raw_entries = operation.get("overwrites", []) or []
            overwrites, applied_count, skipped_count = self._build_overwrites(
                guild,
                raw_entries,
                id_map,
                logs,
                skip_high_roles=True,
                preserve_from=channel,
            )
            if len(raw_entries) > 0 and applied_count == 0 and skipped_count > 0:
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Skipped overwrite edit on '{getattr(channel, 'name', channel.id)}': all targets exceed bot role hierarchy",
                    }
                )
                return

            await self._rest_call(
                job_id,
                channel.edit,
                step_label=step_label,
                logs=logs,
                remaining_cost=remaining_cost,
                overwrites=overwrites,
                reason=reason,
            )
            return

        if op == "update_channel":
            channel = self._get_channel(guild, operation.get("channel_id"), id_map)
            if channel is None:
                raise LookupError("Channel for update was not found")

            changes = dict(operation.get("changes") or {})
            edit: dict[str, Any] = {}
            for key, raw_val in changes.items():
                value = _unwrap_change_value(raw_val)
                mapped = "slowmode_delay" if key == "slowmode" else key
                if mapped in {
                    "name",
                    "topic",
                    "slowmode_delay",
                    "nsfw",
                    "bitrate",
                    "user_limit",
                    "position",
                }:
                    edit[mapped] = value

            old_name = operation.get("old_name")
            new_name = operation.get("new_name")
            if "name" not in edit and new_name is not None and new_name != old_name:
                edit["name"] = new_name

            if "type" in changes:
                new_type = int(_unwrap_change_value(changes["type"]))
                features = {str(item).upper() for item in (getattr(guild, "features", ()) or ())}
                if new_type == 5 and "COMMUNITY" not in features:
                    logs.append(
                        {
                            "level": "warning",
                            "message": f"Skipped type=5 conversion on '{getattr(channel, 'name', channel.id)}': guild lacks COMMUNITY feature",
                        }
                    )
                elif new_type in (0, 5):
                    edit["type"] = discord.ChannelType.news if new_type == 5 else discord.ChannelType.text

            if "category_temp_id" in changes or "category_id" in changes:
                cat_ref = _unwrap_change_value(
                    changes.get("category_temp_id")
                    if changes.get("category_temp_id") is not None
                    else changes.get("category_id")
                )
                if cat_ref is None:
                    edit["category"] = None
                else:
                    cat_obj = self._get_channel(guild, cat_ref, id_map)
                    if cat_obj is None:
                        raise LookupError(f"Category {cat_ref} for channel update was not found")
                    edit["category"] = cat_obj

            if "bitrate" in edit and edit["bitrate"] is not None:
                limit = int(getattr(guild, "bitrate_limit", 96000) or 96000)
                edit["bitrate"] = max(8000, min(int(edit["bitrate"]), limit))
            if "user_limit" in edit and edit["user_limit"] is not None:
                edit["user_limit"] = max(0, min(99, int(edit["user_limit"])))
            if "slowmode_delay" in edit and edit["slowmode_delay"] is not None:
                edit["slowmode_delay"] = max(0, min(21600, int(edit["slowmode_delay"])))

            ch_key = str(channel.id)
            history = self._rename_history[ch_key]
            now = time.time()
            while history and (now - history[0]) >= RENAME_WINDOW_SECONDS:
                history.popleft()

            has_limited_edit = ("name" in edit) or ("topic" in edit)
            if has_limited_edit and len(history) >= RENAME_WINDOW_LIMIT:
                edit.pop("name", None)
                edit.pop("topic", None)
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Skipped/deferred without retry (2-in-10m / 2-edits-per-10m limit) "
                            f"name/topic update on '{getattr(channel, 'name', ch_key)}'"
                        ),
                    }
                )
                has_limited_edit = False

            if edit:
                await self._rest_call(
                    job_id,
                    channel.edit,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    reason=reason,
                    **edit,
                )
                if has_limited_edit:
                    history.append(time.time())
            return

        if op == "bulk_reorder":
            payload: list[dict[str, Any]] = []
            for item in operation.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                temp_id = item.get("temp_id")
                if temp_id is not None and str(temp_id) not in id_map:
                    raise LookupError(f"Channel temp ID {temp_id} was not resolved")
                channel_id = self._resolve_id(temp_id or item.get("id"), id_map)
                if channel_id is None:
                    continue
                row: dict[str, Any] = {
                    "id": _as_id(channel_id),
                    "position": int(item.get("position", 0)),
                }
                item_type = int(item.get("type") if item.get("type") is not None else 0)
                if item_type != 4 and ("parent_id" in item or "parent_temp_id" in item):
                    parent_temp_id = item.get("parent_temp_id")
                    if parent_temp_id is not None and str(parent_temp_id) not in id_map:
                        raise LookupError(f"Category temp ID {parent_temp_id} was not resolved")
                    raw_parent = parent_temp_id or item.get("parent_id")
                    parent = self._resolve_id(raw_parent, id_map)
                    row["parent_id"] = _as_id(parent)
                payload.append(row)

            if payload:
                http = getattr(getattr(guild, "_state", None), "http", None)
                if http is not None and hasattr(http, "bulk_channel_update"):
                    await self._rest_call(
                        job_id,
                        http.bulk_channel_update,
                        guild.id,
                        payload,
                        step_label=step_label,
                        logs=logs,
                        remaining_cost=remaining_cost,
                        reason=reason,
                    )
                elif hasattr(guild, "bulk_channel_update"):
                    await self._rest_call(
                        job_id,
                        guild.bulk_channel_update,
                        payload,
                        step_label=step_label,
                        logs=logs,
                        remaining_cost=remaining_cost,
                        reason=reason,
                    )
                else:
                    raise RuntimeError("Guild HTTP client does not expose bulk_channel_update")
            return

        if op == "delete_role":
            if options.get("safe_mode", True) is not False:
                logs.append({"level": "warning", "message": "Role deletion skipped by safe mode"})
                return
            if options.get("confirm_deletions", False) is not True:
                logs.append({"level": "warning", "message": "Role deletion skipped without confirmation"})
                return
            role = self._get_role(guild, operation.get("role_id"), id_map)
            if role is None:
                return
            role_name = getattr(role, "name", role.id)
            if _is_default_role(guild, role):
                logs.append({"level": "warning", "message": "Refused to delete @everyone role"})
                return
            if bool(getattr(role, "managed", False)):
                logs.append({"level": "warning", "message": f"Refused to delete managed role '{role_name}'"})
                return
            role_pos = int(getattr(role, "position", 0) or 0)
            if actor_top_pos is not None and role_pos >= actor_top_pos:
                raise PermissionError(
                    f"Role '{role_name}' position ({role_pos}) >= actor top role ({actor_top_pos})"
                )
            top_position = self._bot_top_position(guild)
            if top_position is not None and role_pos >= top_position:
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Refused to delete role '{role_name}' "
                            f"(position {role_pos} >= bot top role {top_position})"
                        ),
                    }
                )
                return
            protected_ids = await self._protected_role_ids(str(guild.id))
            if str(role.id) in protected_ids:
                logs.append(
                    {
                        "level": "warning",
                        "message": (
                            f"Refused to delete protected role '{role_name}' "
                            f"(bound to active ZerynBot module)"
                        ),
                    }
                )
                return

            deleted_ok = False
            self._register_expected_delete(guild.id, "role_delete", role.id)
            try:
                await self._rest_call(
                    job_id,
                    role.delete,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    reason=reason,
                )
                deleted_ok = True
            finally:
                if not deleted_ok:
                    self._clear_expected_delete(guild.id, "role_delete", role.id)
            return

        if op in {"delete_channel", "delete_category"}:
            if options.get("safe_mode", True) is not False:
                logs.append({"level": "warning", "message": "Deletion skipped by safe mode"})
                return
            if options.get("confirm_deletions", False) is not True:
                logs.append({"level": "warning", "message": "Deletion skipped without confirmation"})
                return
            channel = self._get_channel(guild, operation.get("channel_id"), id_map)
            if channel is not None:
                deleted_ok = False
                self._register_expected_delete(guild.id, "channel_delete", channel.id)
                try:
                    await self._rest_call(
                        job_id,
                        channel.delete,
                        step_label=step_label,
                        logs=logs,
                        remaining_cost=remaining_cost,
                        reason=reason,
                    )
                    deleted_ok = True
                finally:
                    if not deleted_ok:
                        self._clear_expected_delete(guild.id, "channel_delete", channel.id)
            return

        if op != "bind_modules":
            logs.append({"level": "warning", "message": f"Unknown operation {op}"})

    async def _bind_modules(
        self,
        job_id: Any,
        guild: Any,
        bindings: dict[str, Any],
        options: dict[str, Any],
        id_map: dict[str, str],
        logs: list[dict[str, Any]],
        step_label: str,
        remaining_cost: float,
        *,
        actor_top_pos: int | None = None,
    ) -> None:
        auto_bind = bool(options.get("auto_bind_modules", True))
        send_guides = bool(options.get("send_guides", True))
        if not auto_bind and not send_guides:
            return

        guild_id = str(guild.id)
        resolved: dict[str, Any] = {}
        resolved_roles: dict[str, Any] = {}
        role_unbinds: set[str] = set()
        for key, value in bindings.items():
            norm_role_key = normalize_role_bind_module(key)
            if norm_role_key is not None:
                if value is None or str(value).strip().lower() in {"", "none", "null", "undefined"}:
                    role_unbinds.add(norm_role_key)
                    resolved_roles.pop(norm_role_key, None)
                    continue
                role = self._owned_role(guild, value, id_map, actor_top_pos=actor_top_pos)
                if role is None:
                    logs.append(
                        {"level": "warning", "message": f"Binding role target invalid or not found for {norm_role_key}"}
                    )
                    continue
                resolved_roles[norm_role_key] = role
                role_unbinds.discard(norm_role_key)
                continue

            if not value or str(value).strip().lower() in {"none", "null", "undefined"}:
                continue
            channel = self._owned_channel(guild, value, id_map)
            if channel is None:
                logs.append(
                    {"level": "warning", "message": f"Binding target not found for {key}"}
                )
                continue
            resolved[key] = channel

        if auto_bind:
            guild_fields: dict[str, Any] = {}
            if "welcome" in resolved:
                guild_fields["welcome_channel_id"] = str(resolved["welcome"].id)
            if "autoroles_user" in resolved_roles or "autoroles_user" in role_unbinds:
                curr_gs = await asyncio.to_thread(get_guild_settings, guild_id)
                new_ar_id = (
                    str(resolved_roles["autoroles_user"].id)
                    if "autoroles_user" in resolved_roles
                    else None
                )
                updated_ar = _update_primary_role_list(
                    (curr_gs or {}).get("autoroles_user"), new_role_id=new_ar_id
                )
                guild_fields["autoroles_user"] = json.dumps(updated_ar)
                if new_ar_id is not None:
                    guild_fields["autoroles_enabled"] = 1
                elif not updated_ar and not _parse_role_id_list((curr_gs or {}).get("autoroles_bot")):
                    guild_fields["autoroles_enabled"] = 0
            if guild_fields:
                await asyncio.to_thread(upsert_guild, guild_id, **guild_fields)

            verify_fields: dict[str, Any] = {}
            if "verify" in resolved:
                verify_fields["channel_id"] = str(resolved["verify"].id)
            if "verify_verified" in resolved_roles:
                verify_fields["verified_role_id"] = str(resolved_roles["verify_verified"].id)
            elif "verify_verified" in role_unbinds:
                verify_fields["verified_role_id"] = None
            if "verify_pending" in resolved_roles:
                verify_fields["pending_role_id"] = str(resolved_roles["verify_pending"].id)
            elif "verify_pending" in role_unbinds:
                verify_fields["pending_role_id"] = None
            if verify_fields:
                await async_upsert_verify_settings(guild_id, **verify_fields)

            automod_fields: dict[str, Any] = {}
            if "bot_logs" in resolved:
                channel_id = str(resolved["bot_logs"].id)
                automod_fields["log_channel_id"] = channel_id
                logger_settings = await asyncio.to_thread(get_logger_settings, guild_id)
                logger_settings = dict(logger_settings or {})
                logger_settings["log_channel_id"] = channel_id
                await asyncio.to_thread(set_logger_settings, guild_id, logger_settings)
            if "automod_immune" in resolved_roles or "automod_immune" in role_unbinds:
                curr_am = await asyncio.to_thread(get_automod_settings, guild_id)
                new_imm_id = (
                    str(resolved_roles["automod_immune"].id)
                    if "automod_immune" in resolved_roles
                    else None
                )
                automod_fields["immune_roles"] = _update_primary_role_list(
                    (curr_am or {}).get("immune_roles"), new_role_id=new_imm_id
                )
            if automod_fields:
                await asyncio.to_thread(upsert_automod_settings, guild_id, **automod_fields)

        if send_guides and "music" in resolved:
            gs = await async_get_guild_settings(guild_id)
            embed = discord.Embed(
                title=embed_title("zb_cat_music", tr(gs, "server_builder.music_guide_title")),
                description=tr(gs, "server_builder.music_guide_desc"),
                color=0x5865F2,
            )
            if getattr(guild, "name", None):
                icon_url = getattr(getattr(guild, "icon", None), "url", None)
                embed.set_footer(text=guild.name, icon_url=icon_url)
            try:
                await self._rest_call(
                    job_id,
                    resolved["music"].send,
                    step_label=step_label,
                    logs=logs,
                    remaining_cost=remaining_cost,
                    embed=embed,
                )
            except _JobCancelled:
                raise
            except (discord.Forbidden, discord.HTTPException) as exc:
                logs.append(
                    {
                        "level": "warning",
                        "message": f"Could not send music guide embed: {exc}",
                    }
                )

    @staticmethod
    def _find_plan_role_binding(
        plan_bindings: Any, operations: list[dict[str, Any]], module_key: str
    ) -> str | None:
        if isinstance(plan_bindings, dict):
            for k, v in plan_bindings.items():
                if normalize_role_bind_module(k) == module_key and v is not None:
                    token = str(v).strip()
                    if token and token.lower() not in {"none", "null", "undefined"}:
                        return token
        for op_item in operations:
            if op_item.get("op") != "bind_modules":
                continue
            op_bindings = op_item.get("bindings")
            if not isinstance(op_bindings, dict):
                continue
            for k, v in op_bindings.items():
                if normalize_role_bind_module(k) == module_key and v is not None:
                    token = str(v).strip()
                    if token and token.lower() not in {"none", "null", "undefined"}:
                        return token
        return None

    async def _execute_job(self, job: dict[str, Any]) -> None:
        job_id = job.get("id")
        job_code = job.get("job_code", job_id)
        guild_id = str(job.get("guild_id") or "")
        actor_user_id = str(job.get("actor_user_id") or "").strip()
        guild = None
        logs = list(_json_value(job.get("step_logs", job.get("step_logs_json")), []))
        plan = _json_value(job.get("plan", job.get("plan_json")), {})
        options = _json_value(job.get("options", job.get("options_json")), {})

        raw_ops = [item for item in (plan.get("operations") or []) if isinstance(item, dict)]
        operations = [item for item in raw_ops if item.get("op") != "bind_modules"] + [
            item for item in raw_ops if item.get("op") == "bind_modules"
        ]
        has_bulk_role_reorder = any(item.get("op") == "bulk_reorder_roles" for item in operations)

        completed = int(job.get("completed_steps") or 0)
        failed = int(job.get("failed_steps") or 0)
        started = time.time()
        average: float | None = None
        id_map: dict[str, str] = {}
        discovered_bindings: dict[str, str] = {}
        reason = f"ZerynBot Server Builder (Job #{job_code})"
        terminal_status = "failed"
        error_message: str | None = None

        sb_active = getattr(self.bot, "_sb_active_guilds", None)
        if not isinstance(sb_active, set):
            sb_active = set()
            try:
                setattr(self.bot, "_sb_active_guilds", sb_active)
            except Exception:
                sb_active = None
        self._get_expected_deletes()

        try:
            getter = getattr(self.bot, "get_guild", None)
            guild = getter(int(guild_id)) if getter and guild_id.isdigit() else None
            if guild is None:
                raise LookupError(f"Guild {guild_id} is unavailable")

            if sb_active is not None:
                sb_active.add(guild_id)

            await self._db_update(
                job_id,
                status="running",
                snapshot_before_json=json.dumps(_snapshot(guild), ensure_ascii=False),
                current_step_label="Capturing snapshot",
                error_message=None,
            )
            last_progress_flush = time.monotonic()

            verify_settings = await async_get_verify_settings(guild_id)
            pending_role = None
            verify_channel_id = None
            verify_enabled = int((verify_settings or {}).get("enabled", 0) or 0) == 1
            verify_hide_channels = int((verify_settings or {}).get("hide_channels", 0) or 0) == 1
            if verify_enabled:
                verify_channel_id = str((verify_settings or {}).get("channel_id") or "").strip() or None
                if verify_hide_channels:
                    pending_role = self._get_role(
                        guild, (verify_settings or {}).get("pending_role_id"), id_map
                    )

            verify_refs: set[str] = set()
            plan_bindings = plan.get("bindings")
            if isinstance(plan_bindings, dict) and plan_bindings.get("verify"):
                verify_refs.add(str(plan_bindings["verify"]))
            for operation in operations:
                if operation.get("op") == "bind_modules":
                    bindings = operation.get("bindings") or {}
                    if isinstance(bindings, dict) and bindings.get("verify") is not None:
                        verify_refs.add(str(bindings["verify"]))

            actor_revoked_roles, effective_actor_top = self._actor_role_gate(
                guild, actor_user_id, options
            )
            total_ops = len(operations)
            total_expected = max(total_ops, int(job.get("total_steps") or total_ops))

            for index, operation in enumerate(operations):
                if await self._cancel_requested(job_id):
                    raise _JobCancelled

                op_name = operation.get("op")
                if (
                    pending_role is None
                    and verify_enabled
                    and verify_hide_channels
                    and op_name not in _ROLE_MUTATION_OPS
                ):
                    pending_ref = discovered_bindings.get("verify_pending") or self._find_plan_role_binding(
                        plan_bindings, operations, "verify_pending"
                    )
                    if pending_ref:
                        candidate = self._owned_role(
                            guild, pending_ref, id_map, actor_top_pos=effective_actor_top
                        )
                        if candidate is not None:
                            pending_role = candidate

                label = str(operation.get("label") or op_name or "Step")
                remaining_cost = sum(
                    float(item.get("cost_seconds") or 0.0)
                    for item in operations[index + 1 :]
                )
                prev_failed = failed
                try:
                    if op_name in _ROLE_MUTATION_OPS:
                        actor_revoked_roles, effective_actor_top = self._actor_role_gate(
                            guild, actor_user_id, options
                        )
                        if actor_revoked_roles:
                            raise PermissionError(
                                "Actor no longer holds manage_roles or administrator permission"
                            )

                    if op_name == "bind_modules":
                        merged_bindings: dict[str, Any] = {}
                        if isinstance(plan_bindings, dict):
                            merged_bindings.update(plan_bindings)
                        merged_bindings.update(discovered_bindings)
                        if isinstance(operation.get("bindings"), dict):
                            merged_bindings.update(operation["bindings"])
                        await self._bind_modules(
                            job_id,
                            guild,
                            merged_bindings,
                            options,
                            id_map,
                            logs,
                            label,
                            remaining_cost,
                            actor_top_pos=effective_actor_top,
                        )
                    else:
                        await self._run_operation(
                            job_id,
                            guild,
                            operation,
                            options,
                            id_map,
                            discovered_bindings,
                            reason,
                            logs,
                            pending_role,
                            verify_channel_id,
                            verify_refs,
                            label,
                            remaining_cost,
                            has_bulk_role_reorder=has_bulk_role_reorder,
                            actor_top_pos=effective_actor_top,
                        )
                    logs.append({"level": "info", "message": label})
                except _JobCancelled:
                    raise
                except Exception as exc:
                    failed += 1
                    logs.append(
                        {
                            "level": "error",
                            "message": f"{label}: {type(exc).__name__}: {exc}",
                        }
                    )
                    logger.exception("[ServerBuilder] Job %s step failed", job_code)

                completed += 1
                eta, average = recalibrate_eta(
                    completed,
                    time.time() - started,
                    remaining_cost,
                    prev_avg=average,
                    rate_limit_until=0.0,
                    now=time.time(),
                )
                cancelled = await self._cancel_requested(job_id)
                now_mono = time.monotonic()
                if (
                    index == total_ops - 1
                    or completed >= total_expected
                    or failed > prev_failed
                    or (now_mono - last_progress_flush) >= PROGRESS_FLUSH_INTERVAL
                ):
                    await self._db_update(
                        job_id,
                        completed_steps=completed,
                        failed_steps=failed,
                        current_step_label=label,
                        eta_seconds=max(0.0, float(eta)),
                        step_logs_json=json.dumps(logs[-MAX_STEP_LOGS:], ensure_ascii=False),
                    )
                    last_progress_flush = now_mono
                if cancelled:
                    raise _JobCancelled

            if not any(op.get("op") == "bind_modules" for op in operations):
                fallback_bindings: dict[str, Any] = {}
                if isinstance(plan_bindings, dict):
                    fallback_bindings.update(plan_bindings)
                fallback_bindings.update(discovered_bindings)
                if fallback_bindings:
                    await self._bind_modules(
                        job_id,
                        guild,
                        fallback_bindings,
                        options,
                        id_map,
                        logs,
                        "Bind ZerynBot modules",
                        0.0,
                        actor_top_pos=effective_actor_top,
                    )

            if failed:
                terminal_status = "failed"
                error_message = f"{failed} operation(s) failed"
            else:
                terminal_status = "completed"
        except _JobCancelled:
            terminal_status = "cancelled"
            logs.append({"level": "warning", "message": "Job cancelled"})
        except Exception as exc:
            terminal_status = "failed"
            error_message = f"{type(exc).__name__}: {exc}"
            logs.append({"level": "error", "message": error_message})
            logger.exception("[ServerBuilder] Job %s failed", job_code)
        finally:
            if sb_active is not None:
                sb_active.discard(guild_id)
            if guild is not None:
                try:
                    await async_cache_channels(guild_id, _serialize_channels(guild))
                    await async_cache_roles(guild_id, _serialize_roles(guild))
                except Exception:
                    logger.exception("[ServerBuilder] Cache refresh failed for %s", guild_id)
            try:
                await self._db_update(
                    job_id,
                    status=terminal_status,
                    completed_steps=completed,
                    failed_steps=failed,
                    current_step_label=terminal_status,
                    eta_seconds=0,
                    rate_limit_until=0,
                    step_logs_json=json.dumps(logs[-MAX_STEP_LOGS:], ensure_ascii=False),
                    error_message=error_message,
                    finished_at=time.time(),
                )
            except Exception:
                logger.exception("[ServerBuilder] Could not finalize job %s", job_code)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerBuilder(bot))

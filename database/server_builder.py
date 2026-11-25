"""
server_builder.py — Persistence layer for Server Builder Studio jobs & custom templates.

Uses exclusively `.conn._connect_sync`, `.conn._connect_async`, and `.conn._row_to_dict`
so `database.set_db_path()` isolates tests and CLI tools cleanly.
"""

import json
import logging
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional

import aiosqlite

from .conn import _connect_async, _connect_sync, _row_to_dict

logger = logging.getLogger("ZerynBot.Database")

MAX_CUSTOM_TEMPLATES_PER_GUILD = 10
MAX_TEMPLATE_NAME_LEN = 100
MAX_TEMPLATE_DESC_LEN = 300
MAX_PLAN_JSON_BYTES = 2 * 1024 * 1024
MAX_TEMPLATE_JSON_BYTES = 512 * 1024

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused_rl")
_VALID_JOB_STATUSES = frozenset({
    "queued",
    "running",
    "paused_rl",
    "completed",
    "cancelled",
    "failed",
})
_UPDATABLE_JOB_COLUMNS = frozenset({
    "status",
    "plan_json",
    "options_json",
    "snapshot_before_json",
    "total_steps",
    "completed_steps",
    "failed_steps",
    "current_step_label",
    "eta_seconds",
    "rate_limit_until",
    "cancel_requested",
    "step_logs_json",
    "error_message",
    "started_at",
    "finished_at",
})
_JSON_JOB_COLUMNS = frozenset({
    "plan_json",
    "options_json",
    "snapshot_before_json",
    "step_logs_json",
})


class ActiveJobExistsError(Exception):
    """Raised when attempting to enqueue a Server Builder job while one is active for the guild."""

    def __init__(
        self,
        job_dict: Dict[str, Any],
        message: str = "An active Server Builder job already exists for this guild",
    ):
        self.job = job_dict
        self.job_dict = job_dict
        super().__init__(message)


class TemplateLimitError(Exception):
    """Raised when a guild reaches the custom Server Builder template limit."""

    def __init__(
        self,
        message: str = f"Maximum {MAX_CUSTOM_TEMPLATES_PER_GUILD} custom templates allowed per guild",
        limit: int = MAX_CUSTOM_TEMPLATES_PER_GUILD,
    ):
        self.limit = limit
        super().__init__(message)


def _safe_json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _hydrate_job(row: Any) -> Dict[str, Any]:
    d = _row_to_dict(row)
    d["plan"] = _safe_json_loads(d.get("plan_json"), {})
    d["options"] = _safe_json_loads(d.get("options_json"), {})
    d["snapshot_before"] = (
        _safe_json_loads(d.get("snapshot_before_json"), None)
        if d.get("snapshot_before_json")
        else None
    )
    d["step_logs"] = _safe_json_loads(d.get("step_logs_json"), [])
    d["cancel_requested"] = int(d.get("cancel_requested") or 0)
    return d


def _hydrate_template(row: Any) -> Dict[str, Any]:
    d = _row_to_dict(row)
    d["tree"] = _safe_json_loads(d.get("tree_json"), {})
    return d


def _generate_job_code(now: float) -> str:
    date_part = time.strftime("%Y%m%d", time.gmtime(now))
    suffix = secrets.token_hex(2).upper()
    return f"SB-{date_part}-{suffix}"


def _begin_immediate_sync(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")


async def _begin_immediate_async(db: aiosqlite.Connection) -> None:
    if db.in_transaction:
        await db.commit()
    await db.execute("BEGIN IMMEDIATE")


def create_server_builder_job(
    guild_id: str,
    actor_user_id: str,
    plan: Any,
    options: Any,
    total_steps: int,
    eta_seconds: float,
) -> Dict[str, Any]:
    """Atomically enqueue a Server Builder job if the guild has no active job."""
    guild_id_str = str(guild_id or "").strip()
    actor_str = str(actor_user_id or "").strip()
    if not guild_id_str or not actor_str:
        raise ValueError("guild_id and actor_user_id are required")

    if isinstance(plan, str):
        parsed_plan = json.loads(plan)
        if not isinstance(parsed_plan, (dict, list)):
            raise ValueError("plan must be a JSON object or array")
        plan_json = json.dumps(parsed_plan, ensure_ascii=False)
    else:
        plan_json = json.dumps(plan if plan is not None else {}, ensure_ascii=False)

    if isinstance(options, str):
        parsed_opts = json.loads(options)
        if not isinstance(parsed_opts, dict):
            raise ValueError("options must be a JSON object")
        options_json = json.dumps(parsed_opts, ensure_ascii=False)
    else:
        options_json = json.dumps(options if options is not None else {}, ensure_ascii=False)

    if len(plan_json.encode("utf-8")) > MAX_PLAN_JSON_BYTES or len(options_json.encode("utf-8")) > MAX_TEMPLATE_JSON_BYTES:
        raise ValueError("Server Builder job payload exceeds maximum allowed size")

    steps_val = max(0, int(total_steps or 0))
    eta_val = max(0.0, float(eta_seconds or 0.0))
    now = time.time()

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        _begin_immediate_sync(conn)
        try:
            existing = conn.execute(
                """
                SELECT * FROM server_builder_jobs
                WHERE guild_id = ? AND status IN ('queued', 'running', 'paused_rl')
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id_str,),
            ).fetchone()
            if existing is not None:
                conn.rollback()
                raise ActiveJobExistsError(_hydrate_job(existing))

            new_id = None
            for _ in range(5):
                job_code = _generate_job_code(now)
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO server_builder_jobs (
                            job_code, guild_id, actor_user_id, status,
                            plan_json, options_json, total_steps, eta_seconds, created_at
                        ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                        """,
                        (
                            job_code,
                            guild_id_str,
                            actor_str,
                            plan_json,
                            options_json,
                            steps_val,
                            eta_val,
                            now,
                        ),
                    )
                    new_id = cur.lastrowid
                    break
                except sqlite3.IntegrityError as exc:
                    if "job_code" not in str(exc).lower():
                        raise
            if new_id is None:
                raise RuntimeError("Failed to generate unique Server Builder job_code")

            row = conn.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ?",
                (new_id,),
            ).fetchone()
            conn.commit()
            return _hydrate_job(row)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def get_server_builder_job(job_id: int, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch a single Server Builder job, optionally scoped to guild_id for IDOR safety."""
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return None

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        if guild_id is not None:
            row = conn.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ? AND guild_id = ?",
                (jid, str(guild_id)),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ?",
                (jid,),
            ).fetchone()
    return _hydrate_job(row) if row is not None else None


def get_active_server_builder_job(guild_id: str) -> Optional[Dict[str, Any]]:
    """Return the active (queued, running, or paused_rl) job for a guild if any."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str:
        return None

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM server_builder_jobs
            WHERE guild_id = ? AND status IN ('queued', 'running', 'paused_rl')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id_str,),
        ).fetchone()
    return _hydrate_job(row) if row is not None else None


def list_server_builder_jobs(guild_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """List recent Server Builder jobs for a guild newest first."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str:
        return []
    safe_limit = max(1, min(100, int(limit or 10)))

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM server_builder_jobs
            WHERE guild_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (guild_id_str, safe_limit),
        ).fetchall()
    return [_hydrate_job(r) for r in rows]


def request_cancel_server_builder_job(job_id: int, guild_id: str) -> bool:
    """Request cancellation of a Server Builder job owned by guild_id."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str:
        return False
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return False

    now = time.time()
    with _connect_sync() as conn:
        _begin_immediate_sync(conn)
        try:
            row = conn.execute(
                "SELECT status FROM server_builder_jobs WHERE id = ? AND guild_id = ?",
                (jid, guild_id_str),
            ).fetchone()
            if row is None:
                conn.rollback()
                return False

            status = row[0]
            if status == "queued":
                cur = conn.execute(
                    """
                    UPDATE server_builder_jobs
                    SET cancel_requested = 1, status = 'cancelled', finished_at = ?
                    WHERE id = ? AND guild_id = ? AND status = 'queued'
                    """,
                    (now, jid, guild_id_str),
                )
                conn.commit()
                return cur.rowcount == 1
            if status in ("running", "paused_rl"):
                cur = conn.execute(
                    """
                    UPDATE server_builder_jobs
                    SET cancel_requested = 1
                    WHERE id = ? AND guild_id = ? AND status IN ('running', 'paused_rl')
                    """,
                    (jid, guild_id_str),
                )
                conn.commit()
                return cur.rowcount == 1

            conn.rollback()
            return False
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def get_server_builder_templates(guild_id: str) -> List[Dict[str, Any]]:
    """Return custom Server Builder templates saved for a guild."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str:
        return []

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM server_builder_templates
            WHERE guild_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (guild_id_str,),
        ).fetchall()
    return [_hydrate_template(r) for r in rows]


def save_server_builder_template(
    guild_id: str,
    name: str,
    description: str,
    tree: Any,
    created_by: Optional[str],
) -> Dict[str, Any]:
    """Save a guild-scoped custom Server Builder template (max 10 per guild)."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str:
        raise ValueError("Valid guild_id is required")

    clean_name = (name or "").strip()[:MAX_TEMPLATE_NAME_LEN]
    if not clean_name:
        raise ValueError("Template name is required")
    clean_desc = str(description or "").strip()[:MAX_TEMPLATE_DESC_LEN]

    if isinstance(tree, str):
        parsed = json.loads(tree)
        if not isinstance(parsed, dict):
            raise ValueError("Template tree must be a JSON object")
        tree_json = json.dumps(parsed, ensure_ascii=False)
    elif isinstance(tree, dict):
        tree_json = json.dumps(tree, ensure_ascii=False)
    else:
        raise ValueError("Template tree must be a dict or JSON object string")

    if len(tree_json.encode("utf-8")) > MAX_TEMPLATE_JSON_BYTES:
        raise ValueError("Template tree exceeds maximum allowed size")

    actor = str(created_by).strip()[:64] if created_by is not None else None

    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        _begin_immediate_sync(conn)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM server_builder_templates WHERE guild_id = ?",
                (guild_id_str,),
            ).fetchone()[0]
            if count >= MAX_CUSTOM_TEMPLATES_PER_GUILD:
                conn.rollback()
                raise TemplateLimitError()

            cur = conn.execute(
                """
                INSERT INTO server_builder_templates (guild_id, name, description, tree_json, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id_str, clean_name, clean_desc, tree_json, actor),
            )
            row = conn.execute(
                "SELECT * FROM server_builder_templates WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return _hydrate_template(row)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def delete_server_builder_template(template_id: int, guild_id: str) -> bool:
    """Delete a custom template strictly scoped by id and guild_id (never GLOBAL)."""
    guild_id_str = str(guild_id or "").strip()
    if not guild_id_str or guild_id_str.upper() == "GLOBAL":
        return False
    try:
        tid = int(template_id)
    except (TypeError, ValueError):
        return False

    with _connect_sync() as conn:
        cur = conn.execute(
            "DELETE FROM server_builder_templates WHERE id = ? AND guild_id = ?",
            (tid, guild_id_str),
        )
        conn.commit()
        return cur.rowcount == 1


async def async_claim_next_server_builder_job() -> Optional[Dict[str, Any]]:
    """Atomically claim the oldest queued job whose guild has no running/paused_rl job."""
    now = time.time()
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        await _begin_immediate_async(db)
        try:
            async with db.execute(
                """
                SELECT j.id
                FROM server_builder_jobs j
                WHERE j.status = 'queued'
                  AND j.cancel_requested = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM server_builder_jobs active
                      WHERE active.guild_id = j.guild_id
                        AND active.status IN ('running', 'paused_rl')
                  )
                ORDER BY j.created_at ASC, j.id ASC
                LIMIT 1
                """
            ) as cur:
                candidate = await cur.fetchone()

            if candidate is None:
                await db.rollback()
                return None

            job_id = candidate[0]
            upd = await db.execute(
                """
                UPDATE server_builder_jobs
                SET status = 'running', started_at = ?
                WHERE id = ? AND status = 'queued' AND cancel_requested = 0
                """,
                (now, job_id),
            )
            if upd.rowcount != 1:
                await db.rollback()
                return None

            async with db.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ?",
                (job_id,),
            ) as row_cur:
                row = await row_cur.fetchone()

            await db.commit()
            return _hydrate_job(row) if row is not None else None
        except Exception:
            if db.in_transaction:
                await db.rollback()
            raise


async def async_update_server_builder_job(
    job_id: int,
    *,
    expected_statuses: Optional[Any] = None,
    **fields: Any,
) -> bool:
    """Update whitelisted columns on a Server Builder job safely."""
    if not fields:
        return False

    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return False

    unknown = sorted(col for col in fields if col not in _UPDATABLE_JOB_COLUMNS)
    if unknown:
        raise ValueError(f"Disallowed server_builder_jobs columns: {unknown}")

    status_filter: Optional[List[str]] = None
    if expected_statuses is not None:
        if isinstance(expected_statuses, str):
            status_filter = [expected_statuses]
        else:
            status_filter = list(expected_statuses)
        bad_expected = [s for s in status_filter if s not in _VALID_JOB_STATUSES]
        if bad_expected:
            raise ValueError(f"Invalid expected_statuses: {bad_expected}")
        if not status_filter:
            return False

    sanitized: Dict[str, Any] = {}
    for col, val in fields.items():
        if col == "status":
            if val not in _VALID_JOB_STATUSES:
                raise ValueError(f"Invalid Server Builder job status: {val!r}")
            sanitized[col] = val
        elif col in _JSON_JOB_COLUMNS:
            if val is None and col == "snapshot_before_json":
                sanitized[col] = None
            elif isinstance(val, (dict, list)):
                sanitized[col] = json.dumps(val, ensure_ascii=False)
            else:
                parsed = json.loads(str(val))
                sanitized[col] = json.dumps(parsed, ensure_ascii=False)
        elif col in ("total_steps", "completed_steps", "failed_steps"):
            sanitized[col] = max(0, int(val or 0))
        elif col == "cancel_requested":
            sanitized[col] = int(bool(val))
        elif col in ("eta_seconds", "rate_limit_until"):
            sanitized[col] = max(0.0, float(val or 0.0))
        elif col in ("started_at", "finished_at"):
            sanitized[col] = float(val) if val is not None else None
        else:
            sanitized[col] = val

    set_clause = ", ".join(f"{col} = ?" for col in sanitized.keys())
    params: List[Any] = [*sanitized.values(), jid]
    where_clause = "id = ?"
    if status_filter is not None:
        placeholders = ", ".join("?" for _ in status_filter)
        where_clause += f" AND status IN ({placeholders})"
        params.extend(status_filter)

    async with _connect_async() as db:
        cur = await db.execute(
            f"UPDATE server_builder_jobs SET {set_clause} WHERE {where_clause}",
            params,
        )
        await db.commit()
        return cur.rowcount == 1


async def async_get_server_builder_job(
    job_id: int,
    guild_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Async fetch of a single Server Builder job by id (optionally scoped to guild_id)."""
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return None

    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        if guild_id is not None:
            async with db.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ? AND guild_id = ?",
                (jid, str(guild_id)),
            ) as cur:
                row = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT * FROM server_builder_jobs WHERE id = ?",
                (jid,),
            ) as cur:
                row = await cur.fetchone()
    return _hydrate_job(row) if row is not None else None


async def async_is_server_builder_cancel_requested(job_id: int) -> bool:
    """Check whether cancellation has been requested for a Server Builder job."""
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return False

    async with _connect_async() as db:
        async with db.execute(
            "SELECT cancel_requested, status FROM server_builder_jobs WHERE id = ?",
            (jid,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    return bool(row[0]) or row[1] == "cancelled"


async def async_fail_stale_server_builder_jobs(
    reason: str = "Bot restarted during execution",
) -> int:
    """Mark any in-flight jobs left running/paused_rl across restarts as failed."""
    now = time.time()
    async with _connect_async() as db:
        cur = await db.execute(
            """
            UPDATE server_builder_jobs
            SET status = 'failed', error_message = ?, finished_at = ?
            WHERE status IN ('running', 'paused_rl')
            """,
            (reason, now),
        )
        await db.commit()
        return cur.rowcount

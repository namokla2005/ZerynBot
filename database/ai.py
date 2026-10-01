"""
ai.py — Cấu hình AI chat và log hoạt động AI (telemetry cho dashboard).

Tách từ `database.py` (Giai đoạn 3.3).
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional
import threading

import aiosqlite

from cache import cache

from .conn import _connect_async, _connect_sync, _row_to_dict, get_db_connection, get_db_path

logger = logging.getLogger("ZerynBot.Database")

_last_known_models_stats: Dict[str, Any] = {
    "model1": {
        "name": "Model 1: Bot AI Chat Assistant",
        "provider": "auto",
        "model": "qwen/qwen3.8-27b",
        "status": "READY",
        "last_active": "Sẵn sàng",
        "last_latency_ms": 0,
        "total_calls": 0,
        "success_rate": 100.0,
        "success_count": 0,
        "fail_count": 0,
    },
    "model2": {
        "name": "Model 2: Dual Model MCP Critic",
        "provider": "openrouter",
        "model": "google/gemma-4-31b-it:free",
        "fallback_model": "qwen/qwen3.8-27b",
        "fallback": "qwen/qwen3.8-27b",
        "status": "READY",
        "role": "Independent Reviewer & Security Critic",
        "last_active": "Sẵn sàng",
        "last_verdict": "READY_TO_COMMIT",
        "total_audits": 0,
        "clean_commits": 0,
    }
}

_models_stats_lock = threading.Lock()

def get_ai_settings(guild_id: str) -> dict:
    """Sync — Get AI settings for dashboard."""
    with _connect_sync() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return {
                "guild_id": guild_id, "enabled": 0, "ai_channel_id": "",
                "personality_preset": "friendly", "custom_prompt": "",
                "allow_ask": 1, "allow_summarize": 1, "rate_limit": 5,
                "api_key": ""
            }
        return _row_to_dict(row)

def update_ai_settings(guild_id: str, enabled: int, ai_channel_id: str, personality_preset: str = "friendly", custom_prompt: str = "", allow_ask: int = 1, allow_summarize: int = 1, rate_limit: int = 5, api_key: str = "") -> None:
    """Sync — Update AI settings."""
    with _connect_sync() as conn:
        conn.execute("""
            INSERT INTO ai_settings (guild_id, enabled, ai_channel_id, personality_preset, custom_prompt, allow_ask, allow_summarize, rate_limit, api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                enabled=excluded.enabled,
                ai_channel_id=excluded.ai_channel_id,
                personality_preset=excluded.personality_preset,
                custom_prompt=excluded.custom_prompt,
                allow_ask=excluded.allow_ask,
                allow_summarize=excluded.allow_summarize,
                rate_limit=excluded.rate_limit,
                api_key=excluded.api_key
        """, (guild_id, enabled, ai_channel_id, personality_preset, custom_prompt, allow_ask, allow_summarize, rate_limit, api_key))
        conn.commit()

async def async_get_ai_settings(guild_id: str) -> dict:
    async with _connect_async() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {
                    "guild_id": guild_id, "enabled": 0, "ai_channel_id": "",
                    "personality_preset": "friendly", "custom_prompt": "",
                    "allow_ask": 1, "allow_summarize": 1, "rate_limit": 5,
                    "api_key": ""
                }
            return dict(row)

def log_ai_activities_batch(items: List[Dict[str, Any]]) -> None:
    """Ghi nhận nhiều log AI trong 1 transaction duy nhất (executemany), có retry ngắn tự động chống SQLite lock."""
    if not items:
        return
    rows = [
        (
            str(it.get("source") or "model1")[:15],
            str(it.get("model") or "unknown")[:60],
            str(it.get("provider") or "auto")[:30],
            max(0, int(it.get("latency_ms") or 0)),
            str(it.get("status") or "OK")[:10].upper(),
            str(it.get("message") or "")[:300]
        )
        for it in items
    ]
    for attempt in range(3):
        try:
            with get_db_connection() as c:
                cur = c.cursor()
                try:
                    cur.executemany(
                        "INSERT INTO ai_activity_logs (source, model, provider, latency_ms, status, message) VALUES (?, ?, ?, ?, ?, ?)",
                        rows
                    )
                    c.commit()
                    return
                finally:
                    cur.close()
        except sqlite3.OperationalError as e:
            if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < 2:
                time.sleep(0.05 * (attempt + 1))
                continue
            logger.warning(f"[AiActivity] Database busy/locked on insert batch: {e}")
            break
        except Exception as e:
            logger.warning(f"Lỗi khi log_ai_activities_batch: {e}")
            break

def log_ai_activity(source: str, model: str, provider: str, latency_ms: int, status: str, message: str) -> None:
    """Ghi nhận 1 log AI vào SQLite (sync). Siêu nhẹ (< 0.2ms), thuần túy INSERT không lock bảng."""
    log_ai_activities_batch([{
        "source": source,
        "model": model,
        "provider": provider,
        "latency_ms": latency_ms,
        "status": status,
        "message": message
    }])

async def async_log_ai_activity(source: str, model: str, provider: str, latency_ms: int, status: str, message: str) -> None:
    """Ghi nhận log AI vào SQLite bất đồng bộ qua threadpool executor, hoàn toàn độc lập với ai_logger."""
    try:
        import asyncio
        await asyncio.to_thread(log_ai_activity, source, model, provider, latency_ms, status, message)
    except Exception as e:
        logger.warning(f"Lỗi khi async_log_ai_activity: {e}")

def get_ai_activity_snapshot(since_id: int = 0) -> Dict[str, Any]:
    """Lấy snapshot logs và telemetry thống kê của cả Model 1 và Model 2 từ SQLite WAL, đóng kết nối tường minh."""
    try:
        since_val = int(float(since_id)) if since_id is not None else 0
        if since_val < 0:
            since_val = 0
    except (ValueError, TypeError, OverflowError):
        since_val = 0

    rows = []
    agg_rows = []
    max_id = since_val

    # 1. Thực hiện các truy vấn DB và đóng kết nối NGAY LẬP TỨC (không giữ lock DB khi xử lý RAM)
    db_success = False
    for attempt in range(3):
        try:
            with get_db_connection() as conn:
                cur = None
                try:
                    if since_val <= 0:
                        cur = conn.execute("""
                            SELECT id, source, model, provider, latency_ms, status, message, created_at 
                            FROM ai_activity_logs 
                            ORDER BY id DESC LIMIT 30
                        """)
                        rows = cur.fetchall()
                        rows = list(reversed(rows))
                    else:
                        cur = conn.execute("""
                            SELECT id, source, model, provider, latency_ms, status, message, created_at 
                            FROM ai_activity_logs 
                            WHERE id > ? 
                            ORDER BY id ASC LIMIT 50
                        """, (since_val,))
                        rows = cur.fetchall()
                finally:
                    if cur:
                        try:
                            cur.close()
                        except Exception:
                            pass

                # Chỉ truy vấn thống kê tổng hợp nếu có dữ liệu mới hoặc load ban đầu
                if since_val <= 0 or rows:
                    agg_cur = None
                    try:
                        agg_cur = conn.execute("""
                            SELECT 
                                source,
                                COUNT(*) as total,
                                SUM(CASE WHEN status IN ('OK', 'SUCCESS', 'AUDIT') THEN 1 ELSE 0 END) as succ,
                                SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) as fail
                            FROM (
                                SELECT source, status FROM ai_activity_logs ORDER BY id DESC LIMIT 500
                            )
                            GROUP BY source
                        """)
                        agg_rows = agg_cur.fetchall()
                    finally:
                        if agg_cur:
                            try:
                                agg_cur.close()
                            except Exception:
                                pass
            db_success = True
            break
        except sqlite3.OperationalError as e:
            if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < 2:
                time.sleep(0.05 * (attempt + 1))
                continue
            logger.warning(f"Lỗi SQLite busy/locked khi get_ai_activity_snapshot: {e}")
            break
        except Exception as e:
            logger.error(f"Lỗi truy vấn DB khi get_ai_activity_snapshot: {e}")
            break

    # Kết nối SQLite ĐÃ ĐƯỢC ĐÓNG 100% Ở ĐÂY. Hoàn toàn không còn lock DB nào tồn tại.

    # 2. Xử lý logic thuần túy trong RAM (hoàn toàn an toàn, miễn nhiễm deadlock)
    with _models_stats_lock:
        if not db_success and not rows:
            return {
                "ok": False,
                "max_id": since_val,
                "models": {
                    "model1": dict(_last_known_models_stats["model1"]),
                    "model2": dict(_last_known_models_stats["model2"])
                },
                "logs": []
            }
        # Nếu delta poll không có log mới: trả về ngay stats cache và max_id chính xác bằng since_val
        if since_val > 0 and not rows:
            return {
                "ok": True,
                "max_id": since_val,
                "models": {
                    "model1": dict(_last_known_models_stats["model1"]),
                    "model2": dict(_last_known_models_stats["model2"])
                },
                "logs": []
            }

        m1_stats = dict(_last_known_models_stats["model1"])
        m2_stats = dict(_last_known_models_stats["model2"])

        logs = []
        for r in rows:
            rid = r["id"]
            if rid > max_id:
                max_id = rid
            created = str(r["created_at"] or "")
            time_part = created.split(" ")[1] if " " in created else created
            logs.append({
                "id": rid,
                "ts": time_part,
                "timestamp": time_part,
                "iso": created,
                "src": r["source"],
                "source": r["source"],
                "model": r["model"],
                "prov": r["provider"],
                "provider": r["provider"],
                "lat": r["latency_ms"],
                "latency_ms": r["latency_ms"],
                "stat": r["status"],
                "status": r["status"],
                "msg": r["message"],
                "message": r["message"],
                "error_code": None
            })

        for ar in agg_rows:
            src = ar["source"]
            tot = ar["total"] or 0
            succ = ar["succ"] or 0
            fail = ar["fail"] or 0
            if src == "model1" and tot > 0:
                m1_stats["total_calls"] = tot
                m1_stats["success_count"] = succ
                m1_stats["fail_count"] = fail
                m1_stats["success_rate"] = round((succ / tot) * 100, 1)
            elif src == "model2" and tot > 0:
                m2_stats["total_audits"] = tot
                m2_stats["clean_commits"] = succ

        seen_src = set()
        for lr in reversed(rows):
            src = lr["source"]
            if src in seen_src:
                continue
            seen_src.add(src)
            created = str(lr["created_at"] or "")
            time_val = created.split(" ")[1] if " " in created else created
            if src == "model1":
                m1_stats["model"] = lr["model"]
                m1_stats["provider"] = lr["provider"]
                m1_stats["last_latency_ms"] = lr["latency_ms"]
                m1_stats["last_active"] = time_val
                if lr["status"] == "ERROR":
                    m1_stats["status"] = "ERROR"
                elif lr["status"] in ("WARN", "FALLBACK"):
                    m1_stats["status"] = "FALLBACK"
                else:
                    m1_stats["status"] = "READY"
            elif src == "model2":
                m2_stats["model"] = lr["model"]
                m2_stats["last_active"] = time_val
                msg = lr["message"] or ""
                if "APPROVED" in msg or "SẴN SÀNG" in msg:
                    m2_stats["last_verdict"] = "READY_TO_COMMIT"
                elif "CRITIQUE" in msg:
                    m2_stats["last_verdict"] = "CRITIQUE_ACTIVE"

        _last_known_models_stats["model1"] = dict(m1_stats)
        _last_known_models_stats["model2"] = dict(m2_stats)

        return {
            "ok": True,
            "max_id": max_id,
            "models": {
                "model1": m1_stats,
                "model2": m2_stats
            },
            "logs": logs
        }

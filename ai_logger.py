# -*- coding: utf-8 -*-
"""
ai_logger.py — Centralized, Thread-Safe, Non-Blocking AI Activity Logger for ZerynBot V2.
Tracks real-time operations of both Model 1 (Bot AI Chat) and Model 2 (Dual Model MCP Critic).
Designed for ARM64/Termux (Helio G85, 6GB RAM) with zero SQLite contention and minimal RAM (< 10KB).
"""

import os
import re
import time
import queue
import logging
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from collections import deque
import threading
from typing import Dict, Any, List, Optional

# Secret Scrubbing Regexes (Linear, ReDoS-safe)
_SECRET_PATTERNS = [
    (re.compile(r"gsk_[a-zA-Z0-9]{20,}"), "gsk_***REDACTED***"),
    (re.compile(r"sk-or-v1-[a-zA-Z0-9]{30,}"), "sk-or-***REDACTED***"),
    (re.compile(r"AIzaSy[a-zA-Z0-9_\-]{30,}"), "AIzaSy***REDACTED***"),
    (re.compile(r"AQ\.[a-zA-Z0-9_\-]{20,}"), "AQ.***REDACTED***"),
    (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "ghp_***REDACTED***"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE), "Bearer ***REDACTED***"),
]

def scrub_text(text: str) -> str:
    """Scrub tokens and API keys from text safely."""
    if not text:
        return ""
    out = str(text)
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


class AiActivityLogger:
    """Singleton in-memory + asynchronous disk logger for AI events."""
    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super(AiActivityLogger, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.RLock()
        self._counter = 0
        self._buffer = deque(maxlen=50)

        # Model telemetry caches
        self._model1_stats = {
            "name": "Model 1: Bot AI Chat Engine",
            "provider": "groq",
            "model": "qwen/qwen3.8-27b",
            "status": "ready",
            "last_active": "Sẵn sàng",
            "last_latency_ms": 0,
            "total_calls": 0,
            "success_rate": 100.0,
            "success_count": 0,
            "fail_count": 0,
        }

        self._model2_stats = {
            "name": "Model 2: Dual Model MCP Critic",
            "provider": "openrouter",
            "model": "google/gemma-4-31b-it:free",
            "fallback_model": "qwen/qwen3.8-27b",
            "status": "ready",
            "role": "Independent Reviewer & Security Critic",
            "last_active": "Sẵn sàng",
            "last_verdict": "READY_TO_COMMIT",
            "total_audits": 0,
        }

        # Setup non-blocking logging with QueueHandler + QueueListener
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        log_file = os.path.join(data_dir, "ai_activity.log")

        try:
            self._log_queue = queue.Queue(maxsize=1000)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=2 * 1024 * 1024,  # 2MB
                backupCount=2,
                encoding="utf-8"
            )
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(formatter)
            self._listener = QueueListener(self._log_queue, file_handler, respect_handler_level=True)
            self._listener.start()

            self._logger = logging.getLogger("ZerynAIActivity")
            self._logger.setLevel(logging.INFO)
            self._logger.handlers.clear()
            self._logger.addHandler(QueueHandler(self._log_queue))
            self._logger.propagate = False
        except Exception:
            self._logger = None
            self._listener = None

        self._initialized = True

    def log_event(
        self,
        source: str,  # 'model1' | 'model2'
        model: str,
        provider: str,
        latency_ms: int,
        status: str,  # 'OK' | 'WARN' | 'ERROR' | 'AUDIT'
        message: str,
        meta: dict = None
    ):
        """Record an AI event into RAM buffer and non-blocking file log."""
        safe_msg = scrub_text(message)[:120].strip()
        safe_model = scrub_text(model)[:50].strip()
        safe_prov = scrub_text(provider)[:30].strip()
        now = time.strftime("%H:%M:%S")
        iso_now = time.strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            self._counter += 1
            entry_id = self._counter
            entry = {
                "id": entry_id,
                "ts": now,
                "iso": iso_now,
                "src": "model2" if source == "model2" else "model1",
                "model": safe_model or "Unknown",
                "prov": safe_prov or "auto",
                "lat": max(0, int(latency_ms)),
                "stat": str(status).upper()[:10],
                "msg": safe_msg
            }
            self._buffer.append(entry)

            # Update live stats
            if entry["src"] == "model1":
                self._model1_stats["provider"] = safe_prov or self._model1_stats["provider"]
                self._model1_stats["model"] = safe_model or self._model1_stats["model"]
                self._model1_stats["last_active"] = now
                self._model1_stats["last_latency_ms"] = entry["lat"]
                self._model1_stats["total_calls"] += 1
                if entry["stat"] in ("OK", "SUCCESS"):
                    self._model1_stats["success_count"] += 1
                    self._model1_stats["status"] = "ready"
                elif entry["stat"] in ("WARN", "FALLBACK"):
                    self._model1_stats["status"] = "fallback"
                else:
                    self._model1_stats["fail_count"] += 1
                    self._model1_stats["status"] = "error"
                tot = self._model1_stats["total_calls"]
                if tot > 0:
                    self._model1_stats["success_rate"] = round((self._model1_stats["success_count"] / tot) * 100, 1)

            elif entry["src"] == "model2":
                self._model2_stats["provider"] = safe_prov or self._model2_stats["provider"]
                self._model2_stats["model"] = safe_model or self._model2_stats["model"]
                self._model2_stats["last_active"] = now
                self._model2_stats["total_audits"] += 1
                self._model2_stats["status"] = "ready"
                if "APPROVED" in safe_msg or "SẴN SÀNG" in safe_msg:
                    self._model2_stats["last_verdict"] = "READY_TO_COMMIT"
                elif "REJECTED" in safe_msg or "FIX" in safe_msg:
                    self._model2_stats["last_verdict"] = "FIX_REQUIRED"
                elif "CRITIQUE" in safe_msg:
                    self._model2_stats["last_verdict"] = "CRITIQUE_ACTIVE"

        # Non-blocking file logging via QueueHandler
        if self._logger:
            try:
                log_line = f"[{entry['src'].upper()}] [{entry['stat']}] {entry['model']} ({entry['prov']}, {entry['lat']}ms): {entry['msg']}"
                if entry["stat"] == "ERROR":
                    self._logger.error(log_line)
                elif entry["stat"] == "WARN":
                    self._logger.warning(log_line)
                else:
                    self._logger.info(log_line)
            except Exception:
                pass

    def get_snapshot(self, since_id: int = 0) -> Dict[str, Any]:
        """Fetch current telemetry and delta logs since since_id."""
        try:
            val_since = int(since_id)
        except (ValueError, TypeError):
            val_since = 0

        with self._lock:
            cur_max = self._counter
            # Safe validation: if client passes future since_id, reset to 0
            if val_since < 0 or val_since > cur_max:
                val_since = 0

            # Delta filtering
            new_logs = []
            for item in self._buffer:
                if item["id"] > val_since:
                    new_logs.append(item)

            # If client requests initial load (since_id == 0), return up to 25 latest
            if val_since == 0 and len(new_logs) > 25:
                new_logs = new_logs[-25:]

            return {
                "ok": True,
                "max_id": cur_max,
                "models": {
                    "model1": dict(self._model1_stats),
                    "model2": dict(self._model2_stats)
                },
                "logs": new_logs
            }

    def update_model_config(self, source: str, model: str = None, provider: str = None):
        """Update model or provider name when admin saves settings."""
        with self._lock:
            if source == "model1":
                if model:
                    self._model1_stats["model"] = scrub_text(model)
                if provider:
                    self._model1_stats["provider"] = scrub_text(provider)
            elif source == "model2":
                if model:
                    self._model2_stats["model"] = scrub_text(model)
                if provider:
                    self._model2_stats["provider"] = scrub_text(provider)


# Global singleton instance
ai_logger = AiActivityLogger()
ai_logger.get_feed = ai_logger.get_snapshot

def log_ai_activity(source: str, model: str, provider: str, latency_ms: int, status: str, message: str, meta: dict = None):
    """Module-level convenience wrapper for logging an AI event."""
    return ai_logger.log_event(source=source, model=model, provider=provider, latency_ms=latency_ms, status=status, message=message, meta=meta)

def get_ai_activity_feed(since_id: int = 0):
    """Module-level convenience wrapper to get the latest activity feed."""
    return ai_logger.get_snapshot(since_id=since_id)

# -*- coding: utf-8 -*-
"""
Core AI Provider Manager for ZerynBot V2
Manages Multi-Provider (Google Gemini, Groq Cloud, OpenRouter) and Multi-Key Pools.
Provides thread-safe in-memory Circuit Breaker, Round-Robin rotation, and cross-provider failover.
Engineered for ARM64/Termux (Helio G85, 6GB RAM) with zero SQLite WAL write contention on rate limits.
"""

import os
import re
import time
import json
import random
import logging
import threading
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Tuple, Optional, Any

import requests
import aiohttp

logger = logging.getLogger("ZerynAI")

try:
    from ai_logger import ai_logger
except ImportError:
    ai_logger = None

# ─── Security: Hardcoded Whitelist (Zero SSRF) ──────────────────────────────────
ALLOWED_HOSTS = frozenset({
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "openrouter.ai"
})

# ─── Ngân sách thời gian cho đường sync (Flask support chat) ──────────────────
# Support chat chạy trong ThreadPoolExecutor(max_workers=2); nếu không chặn,
# một request có thể giữ 1/2 worker hàng phút (3 provider × 4 key × timeout 15s).
SYNC_TOTAL_BUDGET = 20.0      # giây — tổng thời gian tối đa cho 1 lần gọi AI sync
SYNC_MAX_KEY_ATTEMPTS = 2     # số key tối đa thử trên mỗi provider ở đường sync

_SSRF_HELPER = None


def is_safe_image_url(url: str) -> bool:
    """
    Chặn SSRF cho URL ảnh do người dùng nhập.

    Dùng lại ``dashboard.auth.is_safe_http_url`` (một nguồn logic duy nhất) và
    fail-closed nếu không import được helper.
    """
    global _SSRF_HELPER
    if not url or not isinstance(url, str):
        return False
    if _SSRF_HELPER is None:
        try:
            from dashboard.auth import is_safe_http_url as _helper
            _SSRF_HELPER = _helper
        except Exception:
            _SSRF_HELPER = False  # không kiểm tra được → từ chối (an toàn)
    if _SSRF_HELPER is False:
        return False
    try:
        return bool(_SSRF_HELPER(url))
    except Exception:
        return False

# ─── Supported Default Models ───────────────────────────────────────────────────
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview"
]

GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound"
]

OPENROUTER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3.5-lightning:free",
]


def mask_key(key: str) -> str:
    """Mask key for safe display in logs and UI (e.g. AQ.Ab8...4cDQ or gsk_abc...1234)."""
    k = (key or "").strip()
    if len(k) <= 10:
        return "****"
    return f"{k[:7]}...{k[-4:]}"


def parse_key_pool(raw: str, max_keys: int = 50) -> List[str]:
    """Parse newline or comma or semicolon separated keys, strip, sanitize and deduplicate."""
    if not raw or not isinstance(raw, str):
        return []
    # Limit raw input length to prevent DOS
    raw = raw[:10000]
    tokens = re.split(r"[\r\n,;]+", raw)
    keys = []
    seen = set()
    for tok in tokens:
        k = tok.strip().strip("'\"")
        # Sanitize: only alphanumeric, hyphen, underscore, dot
        k = re.sub(r"[^a-zA-Z0-9_\.-]", "", k)
        if len(k) >= 8 and len(k) <= 256 and k not in seen:
            seen.add(k)
            keys.append(k)
            if len(keys) >= max_keys:
                break
    return keys


def classify_key(key: str) -> str:
    """
    Classify key provider:
    - Starts with 'gsk_' -> groq
    - Starts with 'sk-or-' -> openrouter
    - Everything else (including 'AIzaSy...' and 'AQ....') -> gemini
    """
    k = (key or "").strip()
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-or-"):
        return "openrouter"
    return "gemini"


# ─── Safety Metadata Sanitizer ────────────────────────────────────────────────
_SAFETY_PATTERNS_MGR = [
    re.compile(r'[\r\n]*[ \t]*User Safety:[ \t]*\w+[ \t]*', re.IGNORECASE),
    re.compile(r'[\r\n]*[ \t]*Assistant Safety:[ \t]*\w+[ \t]*', re.IGNORECASE),
    re.compile(r'[\r\n]*[ \t]*\[Safety[:\s][^\]]*\][ \t]*', re.IGNORECASE),
    re.compile(r'<safety_ratings>[\s\S]*?</safety_ratings>', re.IGNORECASE),
]


def _sanitize_mgr(text: str) -> str:
    """Strip safety metadata injected by some OpenRouter models (e.g. Nvidia Nemotron)."""
    if not text:
        return text
    for p in _SAFETY_PATTERNS_MGR:
        text = p.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class AIProviderManager:
    """
    Singleton AI Manager maintaining:
    - In-memory circuit breaker cooldowns
    - Round-robin pointers
    - Thread-safety with threading.Lock
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._state_lock = threading.Lock()
        # Cooldown tracker: {key: (cooldown_until_timestamp, backoff_seconds)}
        self._cooldowns: Dict[str, Tuple[float, float]] = {}
        # Round-robin index: {provider: int}
        self._rr_idx: Dict[str, int] = {"gemini": 0, "groq": 0, "openrouter": 0}

    # ─── Circuit Breaker & Health ───────────────────────────────────────────────

    def is_in_cooldown(self, key: str) -> bool:
        """Check if key is currently in rate limit cooldown."""
        with self._state_lock:
            info = self._cooldowns.get(key)
            if not info:
                return False
            until, _ = info
            if time.time() < until:
                return True
            # Cooldown expired, clean up
            self._cooldowns.pop(key, None)
            return False

    def mark_cooldown(self, key: str, base_cooldown: float = 60.0):
        """Mark a key as rate-limited with exponential backoff up to 300s."""
        now = time.time()
        with self._state_lock:
            # Purge expired cooldowns to prevent memory leak
            expired = [k for k, v in self._cooldowns.items() if now >= v[0]]
            for k in expired:
                self._cooldowns.pop(k, None)

            info = self._cooldowns.get(key)
            if info:
                until, prev_backoff = info
                # Only increase if current cooldown has passed or within 5s
                if now >= until - 5.0:
                    new_backoff = min(prev_backoff * 1.5, 300.0)
                    self._cooldowns[key] = (now + new_backoff, new_backoff)
                    logger.warning(f"[AIManager] Key {mask_key(key)} hit rate limit again! Cooldown extended to {new_backoff:.0f}s")
            else:
                self._cooldowns[key] = (now + base_cooldown, base_cooldown)
                logger.warning(f"[AIManager] Key {mask_key(key)} hit rate limit! Cooldown for {base_cooldown:.0f}s")

    def reset_cooldown(self, key: str):
        """Reset cooldown when key succeeds."""
        with self._state_lock:
            self._cooldowns.pop(key, None)

    def get_next_available_key(self, provider: str, keys: List[str]) -> Optional[str]:
        """
        Get the next available key for a provider using round-robin.
        Skips keys currently in cooldown. If all are in cooldown, returns the one that expires soonest.
        """
        if not keys:
            return None
        with self._state_lock:
            start_idx = self._rr_idx.get(provider, 0) % len(keys)
            # Try finding one not in cooldown
            for offset in range(len(keys)):
                idx = (start_idx + offset) % len(keys)
                k = keys[idx]
                info = self._cooldowns.get(k)
                if not info or time.time() >= info[0]:
                    self._rr_idx[provider] = (idx + 1) % len(keys)
                    return k

            # All keys are in cooldown: pick the one expiring soonest
            soonest_key = min(keys, key=lambda k: self._cooldowns.get(k, (0, 0))[0])
            self._rr_idx[provider] = (keys.index(soonest_key) + 1) % len(keys)
            return soonest_key

    # ─── Configuration Loader ──────────────────────────────────────────────────

    def load_pools(self) -> Dict[str, Any]:
        """
        Load configured key pools and routing options from database & config.
        Safe to call from any thread or process.
        """
        try:
            import database as db
            import config

            gemini_raw = db.get_global_setting("gemini_api_keys", "")
            groq_raw = db.get_global_setting("groq_api_keys", "")
            openrouter_raw = db.get_global_setting("openrouter_api_keys", "")
            routing_mode = db.get_global_setting("global_ai_provider", "auto").strip().lower()
            model = db.get_global_setting("global_ai_model", "gemini-3.6-flash").strip()
            legacy_key = db.get_global_setting("gemini_api_key", "") or config.GEMINI_API_KEY
        except Exception as e:
            logger.error(f"[AIManager] Error loading pools from DB: {e}")
            gemini_raw, groq_raw, openrouter_raw = "", "", ""
            routing_mode = "auto"
            model = "gemini-3.6-flash"
            legacy_key = ""

        gemini_keys = parse_key_pool(gemini_raw)
        groq_keys = parse_key_pool(groq_raw)
        openrouter_keys = parse_key_pool(openrouter_raw)

        # Legacy fallback if pools are empty
        if legacy_key:
            ck = classify_key(legacy_key)
            if ck == "groq" and legacy_key not in groq_keys:
                groq_keys.insert(0, legacy_key)
            elif ck == "openrouter" and legacy_key not in openrouter_keys:
                openrouter_keys.insert(0, legacy_key)
            elif ck == "gemini" and legacy_key not in gemini_keys:
                gemini_keys.insert(0, legacy_key)

        return {
            "gemini_keys": gemini_keys,
            "groq_keys": groq_keys,
            "openrouter_keys": openrouter_keys,
            "routing_mode": routing_mode,  # 'auto', 'gemini', 'groq', 'openrouter'
            "model": model
        }

    def _get_provider_chain(self, routing: str, model: str) -> List[str]:
        """
        Determines the failover order of AI providers.

        KEY RULE: Google AI Studio (Gemini) is ALWAYS the LAST fallback in 'auto' mode,
        regardless of which model is selected as preferred. Gemini is slow on Termux ARM64
        (response time ~60s+). It is only placed first when routing is EXPLICITLY forced
        to 'gemini' by the admin.

        Fallback order in auto mode: Groq (fast ~0.2s) → OpenRouter → Gemini (last resort)
        """
        # 1. Forced routing mode (admin explicitly picks a provider)
        if routing == "gemini":
            return ["gemini", "groq", "openrouter"]
        if routing == "groq":
            return ["groq", "openrouter", "gemini"]
        if routing == "openrouter":
            return ["openrouter", "groq", "gemini"]

        # 2. Auto routing mode: Google Gemini is ALWAYS last, regardless of preferred model.
        #    Detect preferred provider from model name only to determine Groq vs OpenRouter order.
        m = (model or "").strip().lower()

        if "gemma" in m or m.startswith("openrouter/") or m.startswith("nvidia/"):
            # OpenRouter model selected → OpenRouter first, Groq second, Gemini LAST
            return ["openrouter", "groq", "gemini"]
        elif (
            m in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "groq/compound", "groq/compound-mini")
            or m.startswith("qwen")
            or m.startswith("groq/")
            or m.startswith("openai/")
        ):
            # Groq model selected → Groq first, OpenRouter second, Gemini LAST
            return ["groq", "openrouter", "gemini"]
        else:
            # Default (including gemini-* model selected as preferred): Groq → OpenRouter → Gemini LAST
            # Even if user selects a Gemini model as "preferred", the system still tries
            # Groq/OpenRouter first for speed. Gemini is only used as a last-resort fallback.
            return ["groq", "openrouter", "gemini"]

    # ─── Synchronous Execution (Flask / Web Support Chat) ──────────────────────

    def _call_gemini_sync(self, key: str, prompt: str, system_instruction: str = "", model: str = "gemini-3.6-flash", timeout: int = 12) -> Tuple[bool, str]:
        """Synchronous Google Gemini call with SSRF defense."""
        target_models = [model] if model and model.startswith("gemini-") else []
        for m in GEMINI_MODELS:
            if m not in target_models:
                target_models.append(m)

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": key
        }
        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if system_instruction:
            body["system_instruction"] = {"parts": [{"text": system_instruction}]}

        last_error = ""
        for m in target_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            # Whitelist check
            parsed = urlparse(url)
            if parsed.hostname not in ALLOWED_HOSTS:
                return False, "SSRF Blocked"

            try:
                resp = requests.post(url, headers=headers, json=body, timeout=timeout, allow_redirects=False)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            self.reset_cooldown(key)
                            return True, parts[0].get("text", "").strip()
                elif resp.status_code == 429:
                    self.mark_cooldown(key, base_cooldown=60.0)
                    return False, "RATE_LIMIT_429"
                else:
                    last_error = f"HTTP {resp.status_code}"
            except requests.exceptions.Timeout:
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "Gemini API Error"

    def _call_groq_sync(self, key: str, prompt: str, system_instruction: str = "", model: str = "qwen/qwen3.8-27b", timeout: int = 12) -> Tuple[bool, str]:
        """Synchronous Groq Cloud call with SSRF defense."""
        target_models = [model] if model and not model.startswith("gemini-") else []
        for m in GROQ_MODELS:
            if m not in target_models:
                target_models.append(m)

        url = "https://api.groq.com/openai/v1/chat/completions"
        parsed = urlparse(url)
        if parsed.hostname not in ALLOWED_HOSTS:
            return False, "SSRF Blocked"

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        last_error = ""
        for m in target_models:
            body = {
                "model": m,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 1200
            }
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=timeout, allow_redirects=False)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        self.reset_cooldown(key)
                        return True, choices[0].get("message", {}).get("content", "").strip()
                elif resp.status_code == 429:
                    self.mark_cooldown(key, base_cooldown=60.0)
                    return False, "RATE_LIMIT_429"
                else:
                    last_error = f"HTTP {resp.status_code}"
            except requests.exceptions.Timeout:
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "Groq API Error"

    def _call_openrouter_sync(self, key: str, prompt: str, system_instruction: str = "", model: str = "openrouter/free", timeout: int = 15) -> Tuple[bool, str]:
        """Synchronous OpenRouter call with SSRF defense."""
        url = "https://openrouter.ai/api/v1/chat/completions"
        parsed = urlparse(url)
        if parsed.hostname not in ALLOWED_HOSTS:
            return False, "SSRF Blocked"

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://zerynbot.id.vn",
            "X-Title": "ZerynBot"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        last_error = ""
        for m in OPENROUTER_MODELS:
            body = {"model": m, "messages": messages, "max_tokens": 1200}
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=timeout, allow_redirects=False)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        self.reset_cooldown(key)
                        return True, choices[0].get("message", {}).get("content", "").strip()
                elif resp.status_code == 429:
                    self.mark_cooldown(key, base_cooldown=60.0)
                    return False, "RATE_LIMIT_429"
                else:
                    last_error = f"HTTP {resp.status_code}"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "OpenRouter API Error"

    def call_ai_sync(self, prompt: str, system_instruction: str = "") -> Tuple[bool, str]:
        """
        Main synchronous entry point with multi-key rotation and multi-provider failover.
        Returns: (success_bool, response_or_error_string)
        """
        cfg = self.load_pools()
        routing = cfg["routing_mode"]
        model = cfg["model"]

        gemini_pool = list(cfg["gemini_keys"])
        groq_pool = list(cfg["groq_keys"])
        openrouter_pool = list(cfg["openrouter_keys"])

        # Determine order of provider attempts (Google Gemini is always last fallback)
        provider_chain = self._get_provider_chain(routing, model)

        pools_map = {
            "gemini": gemini_pool,
            "groq": groq_pool,
            "openrouter": openrouter_pool
        }

        # Ngân sách thời gian: đường sync chạy trong ThreadPoolExecutor của Flask
        # support chat (chỉ 2 worker) nên tuyệt đối không được giữ thread hàng phút.
        deadline = time.monotonic() + SYNC_TOTAL_BUDGET
        t0 = time.monotonic()

        # Try providers in chain
        for provider in provider_chain:
            if time.monotonic() >= deadline:
                logger.info(
                    "[AIManager] Hết ngân sách %.0fs cho đường sync — dừng thử provider.",
                    SYNC_TOTAL_BUDGET,
                )
                break
            p_keys = pools_map.get(provider, [])
            if not p_keys:
                continue

            # Giới hạn số key thử trên mỗi provider (sync).
            attempts = min(len(p_keys), SYNC_MAX_KEY_ATTEMPTS)
            for _ in range(attempts):
                if time.monotonic() >= deadline:
                    break
                active_key = self.get_next_available_key(provider, p_keys)
                if not active_key:
                    break

                # Slight jitter to prevent thundering herd
                time.sleep(random.uniform(0.005, 0.02))

                if provider == "gemini":
                    ok, res = self._call_gemini_sync(active_key, prompt, system_instruction, model=model)
                elif provider == "groq":
                    ok, res = self._call_groq_sync(active_key, prompt, system_instruction, model=model)
                elif provider == "openrouter":
                    ok, res = self._call_openrouter_sync(active_key, prompt, system_instruction, model=model)
                else:
                    ok, res = False, "Unknown provider"

                if ok:
                    lat_ms = int((time.monotonic() - t0) * 1000)
                    if ai_logger:
                        ai_logger.log_event(
                            source="model1",
                            model=model,
                            provider=provider,
                            latency_ms=lat_ms,
                            status="OK",
                            message=f"Xử lý thành công trong {lat_ms}ms"
                        )
                    return True, res

                # If rate limited (429), try next key in this provider's pool
                if res == "RATE_LIMIT_429":
                    if ai_logger:
                        ai_logger.log_event(
                            source="model1",
                            model=model,
                            provider=provider,
                            latency_ms=int((time.monotonic() - t0) * 1000),
                            status="WARN",
                            message=f"Key {mask_key(active_key)} bị 429 Rate-Limit, đang xoay tua..."
                        )
                    continue
                # If invalid key or other error, also continue to next key
                continue

            # If all keys in this provider failed, log and fall through to next provider
            logger.info(f"[AIManager] Provider '{provider}' pool exhausted/rate-limited. Failing over to next provider...")
            if ai_logger:
                ai_logger.log_event(
                    source="model1",
                    model=model,
                    provider=provider,
                    latency_ms=0,
                    status="WARN",
                    message=f"Hết key khả dụng trên {provider}. Chuyển tầng sang provider dự phòng..."
                )

        if ai_logger:
            ai_logger.log_event(
                source="model1",
                model=model,
                provider=routing,
                latency_ms=0,
                status="ERROR",
                message="Toàn bộ AI Providers và Key Pools đều không phản hồi"
            )
        return False, ""

    # ─── Asynchronous Execution (Discord Bot / cogs/ai.py) ──────────────────────

    async def _call_gemini_async(self, session: aiohttp.ClientSession, key: str, prompt: str, system_instruction: str = "", model: str = "gemini-3.6-flash", image_url: str = None, timeout: int = 15) -> Tuple[bool, str]:
        """Asynchronous Google Gemini call with SSRF defense and Vision support."""
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if image_url and not is_safe_image_url(image_url):
            return False, "IMAGE_SSRF_BLOCKED"
        if image_url:
            try:
                import base64
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=8)) as img_resp:
                    if img_resp.status == 200:
                        img_bytes = await img_resp.read()
                        mime = img_resp.headers.get("Content-Type", "image/jpeg")
                        b64_data = base64.b64encode(img_bytes).decode("utf-8")
                        parts.append({
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64_data
                            }
                        })
            except Exception:
                pass

        target_models = [model] if model and model.startswith("gemini-") else []
        for m in GEMINI_MODELS:
            if m not in target_models:
                target_models.append(m)

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": key
        }
        body: Dict[str, Any] = {
            "contents": [{"parts": parts}]
        }
        if system_instruction:
            body["system_instruction"] = {"parts": [{"text": system_instruction}]}

        last_error = ""
        for m in target_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            parsed = urlparse(url)
            if parsed.hostname not in ALLOWED_HOSTS:
                return False, "SSRF Blocked"

            try:
                async with session.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            cparts = candidates[0].get("content", {}).get("parts", [])
                            if cparts:
                                self.reset_cooldown(key)
                                return True, cparts[0].get("text", "").strip()
                    elif resp.status == 429:
                        self.mark_cooldown(key, base_cooldown=60.0)
                        return False, "RATE_LIMIT_429"
                    else:
                        last_error = f"HTTP {resp.status}"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "Gemini API Error"

    async def _call_groq_async(self, session: aiohttp.ClientSession, key: str, prompt: str, system_instruction: str = "", model: str = "qwen/qwen3.8-27b", image_url: str = None, timeout: int = 15) -> Tuple[bool, str]:
        """Asynchronous Groq Cloud call."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        parsed = urlparse(url)
        if parsed.hostname not in ALLOWED_HOSTS:
            return False, "SSRF Blocked"

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        messages: List[Dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if image_url and not is_safe_image_url(image_url):
            return False, "IMAGE_SSRF_BLOCKED"

        if image_url:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Hãy mô tả và phân tích bức ảnh này."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            })
            target_models = ["meta-llama/llama-3.2-11b-vision-preview"]
        else:
            messages.append({"role": "user", "content": prompt})
            target_models = [model] if model and not model.startswith("gemini-") else []
            for m in GROQ_MODELS:
                if m not in target_models:
                    target_models.append(m)

        last_error = ""
        for m in target_models:
            body = {
                "model": m,
                "messages": messages,
                "temperature": 0.6,
                "max_tokens": 1500
            }
            try:
                async with session.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            self.reset_cooldown(key)
                            return True, choices[0].get("message", {}).get("content", "").strip()
                    elif resp.status == 429:
                        self.mark_cooldown(key, base_cooldown=60.0)
                        return False, "RATE_LIMIT_429"
                    else:
                        last_error = f"HTTP {resp.status}"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "Groq API Error"

    async def _call_openrouter_async(self, session: aiohttp.ClientSession, key: str, prompt: str, system_instruction: str = "", image_url: str = None, timeout: int = 15) -> Tuple[bool, str]:
        """Asynchronous OpenRouter call."""
        url = "https://openrouter.ai/api/v1/chat/completions"
        parsed = urlparse(url)
        if parsed.hostname not in ALLOWED_HOSTS:
            return False, "SSRF Blocked"

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://zerynbot.id.vn",
            "X-Title": "ZerynBot"
        }
        messages: List[Dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if image_url and not is_safe_image_url(image_url):
            return False, "IMAGE_SSRF_BLOCKED"

        if image_url:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Hãy mô tả và phân tích bức ảnh này."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            })
            target_models = ["meta-llama/llama-3.2-11b-vision-instruct:free"]
        else:
            messages.append({"role": "user", "content": prompt})
            target_models = OPENROUTER_MODELS

        last_error = ""
        for m in target_models:
            body = {"model": m, "messages": messages, "max_tokens": 1500}
            try:
                async with session.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            raw = choices[0].get("message", {}).get("content", "") or ""
                            clean = _sanitize_mgr(raw)
                            if clean:
                                self.reset_cooldown(key)
                                return True, clean
                    elif resp.status == 429:
                        self.mark_cooldown(key, base_cooldown=60.0)
                        return False, "RATE_LIMIT_429"
                    elif resp.status == 529:  # OpenRouter overloaded
                        import asyncio
                        await asyncio.sleep(2)
                        last_error = "OVERLOADED_529"
                    else:
                        last_error = f"HTTP {resp.status}"
            except Exception as e:
                last_error = str(e)

        return False, last_error or "OpenRouter API Error"

    async def call_ai_async(self, prompt: str, system_instruction: str = "", image_url: str = None, preferred_model: str = None) -> Tuple[bool, str]:
        """
        Main asynchronous entry point with multi-key rotation and multi-provider failover.
        Returns: (success_bool, response_or_error_string)
        """
        cfg = self.load_pools()
        routing = cfg["routing_mode"]
        model = preferred_model or cfg["model"]

        gemini_pool = list(cfg["gemini_keys"])
        groq_pool = list(cfg["groq_keys"])
        openrouter_pool = list(cfg["openrouter_keys"])

        # Determine order of provider attempts (Google Gemini is always last fallback)
        provider_chain = self._get_provider_chain(routing, model)

        pools_map = {
            "gemini": gemini_pool,
            "groq": groq_pool,
            "openrouter": openrouter_pool
        }

        async with aiohttp.ClientSession() as session:
            for provider in provider_chain:
                p_keys = pools_map.get(provider, [])
                if not p_keys:
                    continue

                attempts = min(len(p_keys), 4)
                for _ in range(attempts):
                    active_key = self.get_next_available_key(provider, p_keys)
                    if not active_key:
                        break

                    t0_attempt = time.time()
                    if provider == "gemini":
                        ok, res = await self._call_gemini_async(session, active_key, prompt, system_instruction, model=model, image_url=image_url)
                    elif provider == "groq":
                        ok, res = await self._call_groq_async(session, active_key, prompt, system_instruction, model=model, image_url=image_url)
                    elif provider == "openrouter":
                        ok, res = await self._call_openrouter_async(session, active_key, prompt, system_instruction, image_url=image_url)
                    else:
                        ok, res = False, "Unknown provider"

                    if ok:
                        lat_ms = int((time.time() - t0_attempt) * 1000)
                        if ai_logger:
                            ai_logger.log_event(
                                source="model1",
                                model=model,
                                provider=provider,
                                latency_ms=lat_ms,
                                status="OK",
                                message=f"Xử lý thành công trong {lat_ms}ms"
                            )
                        return True, res

                    if res == "RATE_LIMIT_429":
                        if ai_logger:
                            ai_logger.log_event(
                                source="model1",
                                model=model,
                                provider=provider,
                                latency_ms=int((time.time() - t0_attempt) * 1000),
                                status="WARN",
                                message=f"Key {mask_key(active_key)} bị 429 Rate-Limit, đang xoay tua..."
                            )
                        continue
                    continue

                logger.info(f"[AIManager] Async Provider '{provider}' pool exhausted/rate-limited. Failing over...")
                if ai_logger:
                    ai_logger.log_event(
                        source="model1",
                        model=model,
                        provider=provider,
                        latency_ms=0,
                        status="WARN",
                        message=f"Hết key khả dụng trên {provider}. Chuyển tầng sang provider dự phòng..."
                    )

        if ai_logger:
            ai_logger.log_event(
                source="model1",
                model=model,
                provider=routing,
                latency_ms=0,
                status="ERROR",
                message="Toàn bộ AI Providers và Key Pools đều không phản hồi"
            )
        return False, ""

    # ─── Gọi 1 provider với 1 key CỤ THỂ (key riêng của guild) ──────────────────

    async def call_provider_async(
        self,
        provider: str,
        key: str,
        prompt: str,
        system_instruction: str = "",
        image_url: str = None,
        preferred_model: str = None,
    ) -> Tuple[bool, str]:
        """
        Gọi đúng 1 provider bằng 1 key CỤ THỂ (key riêng từng guild).

        Trước đây bot/cogs/ai.py tự implement lại HTTP cho cả 3 provider → tồn tại
        hai bản logic AI song song (một bản có cooldown/circuit breaker/sanitize,
        một bản không). Nay mọi đường đi đều dùng chung implementation tại đây.

        Trả về (ok, text). Bị 429 → (False, "RATE_LIMIT_429") và key vào cooldown
        như pool toàn cục; URL ảnh không an toàn → (False, "IMAGE_SSRF_BLOCKED").

        Lưu ý: mỗi lần gọi tạo 1 ClientSession riêng (giống call_ai_async) — cố ý
        không giữ session dài hạn trong singleton vì manager được dùng từ cả bot
        (event loop) lẫn dashboard (thread), tránh dùng session qua nhiều loop.
        """
        k = (key or "").strip()
        if not k:
            return False, "EMPTY_KEY"
        if self.is_in_cooldown(k):
            return False, "RATE_LIMIT_429"

        model = (preferred_model or self.load_pools().get("model") or "").strip()

        async with aiohttp.ClientSession() as session:
            if provider == "gemini":
                gemini_model = model if model.startswith("gemini-") else "gemini-3.6-flash"
                return await self._call_gemini_async(
                    session, k, prompt, system_instruction,
                    model=gemini_model, image_url=image_url,
                )
            if provider == "groq":
                return await self._call_groq_async(
                    session, k, prompt, system_instruction,
                    model=model, image_url=image_url,
                )
            if provider == "openrouter":
                return await self._call_openrouter_async(
                    session, k, prompt, system_instruction, image_url=image_url,
                )
        return False, "Unknown provider"

    # ─── Multi-Key Diagnostics & Testing ───────────────────────────────────────

    def test_single_key(self, key: str, target_model: str = "") -> Dict[str, Any]:
        """Test a single key against its respective provider and measure latency."""
        k = (key or "").strip()
        if not k:
            return {"ok": False, "provider": "unknown", "key": "", "message": "Key rỗng"}

        prov = classify_key(k)
        masked = mask_key(k)
        t0 = time.time()

        if prov == "groq":
            m = target_model if (target_model and not target_model.startswith("gemini-")) else "qwen/qwen3.8-27b"
            ok, res = self._call_groq_sync(k, "Hi", model=m, timeout=6)
            latency = int((time.time() - t0) * 1000)
            if ok:
                return {
                    "ok": True,
                    "provider": "Groq Cloud",
                    "model": m,
                    "key_masked": masked,
                    "latency_ms": latency,
                    "message": f"🟢 Kết nối Groq siêu tốc ({latency}ms) với {m}"
                }
            return {
                "ok": False,
                "provider": "Groq Cloud",
                "model": m,
                "key_masked": masked,
                "latency_ms": latency,
                "message": f"🔴 Lỗi kết nối Groq: {res}"
            }

        elif prov == "openrouter":
            m = "openrouter/free"
            ok, res = self._call_openrouter_sync(k, "Hi", model=m, timeout=12)
            latency = int((time.time() - t0) * 1000)
            if ok:
                return {
                    "ok": True,
                    "provider": "OpenRouter",
                    "model": m,
                    "key_masked": masked,
                    "latency_ms": latency,
                    "message": f"🟢 Kết nối OpenRouter Free ({latency}ms) với {m}"
                }
            return {
                "ok": False,
                "provider": "OpenRouter",
                "model": m,
                "key_masked": masked,
                "latency_ms": latency,
                "message": f"🔴 Lỗi OpenRouter: {res}"
            }

        else:
            # Google Gemini
            m = target_model if (target_model and target_model.startswith("gemini-")) else "gemini-3.6-flash"
            ok, res = self._call_gemini_sync(k, "Hi", model=m, timeout=8)
            latency = int((time.time() - t0) * 1000)
            if ok:
                return {
                    "ok": True,
                    "provider": "Google Gemini",
                    "model": m,
                    "key_masked": masked,
                    "latency_ms": latency,
                    "message": f"🟢 Kết nối Google Gemini ({latency}ms) với {m}"
                }
            return {
                "ok": False,
                "provider": "Google Gemini",
                "model": m,
                "key_masked": masked,
                "latency_ms": latency,
                "message": f"🔴 Lỗi Google Gemini: {res}"
            }

    def test_all_pools(self, gemini_keys: List[str], groq_keys: List[str], openrouter_keys: List[str], target_model: str = "") -> List[Dict[str, Any]]:
        """
        Test all keys in all pools concurrently with bounded ThreadPoolExecutor (max_workers=3)
        to protect Helio G85 ARM CPU from load spikes.
        """
        all_keys = []
        for k in gemini_keys:
            all_keys.append(k)
        for k in groq_keys:
            all_keys.append(k)
        for k in openrouter_keys:
            all_keys.append(k)

        if not all_keys:
            return []

        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.test_single_key, k, target_model) for k in all_keys]
            for f in futures:
                try:
                    results.append(f.result(timeout=12))
                except Exception as e:
                    results.append({"ok": False, "provider": "Error", "message": str(e)})

        return results


# Global Singleton Instance
ai_manager = AIProviderManager()

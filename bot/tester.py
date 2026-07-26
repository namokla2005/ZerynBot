"""
tester.py — Self-Diagnostic Test Suite for Bot V2 (Termux / Android Optimized).
Runs automated checks for all 11 modules at bot startup.
Reports status to Feedback Webhook and halts startup if any test fails.
"""
import sys
import os
import time
import shutil
import asyncio
import traceback
import sqlite3
import importlib.util

import aiohttp

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import config
from cache import cache

def _safe_print(text: str):
    """Safe print wrapper preventing UnicodeEncodeError on non-UTF8 terminals."""
    try:
        print(text, flush=True)
    except Exception:
        try:
            print(text.encode("ascii", errors="ignore").decode("ascii"), flush=True)
        except Exception:
            pass

async def _send_webhook_report(title: str, description: str, color: int, fields: list = None):
    """Async webhook report using aiohttp."""
    if not config.WEBHOOK_LOG_URL:
        return
    try:
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {"text": "Bot V2 Self-Diagnostic Tester"}
        }
        if fields:
            embed["fields"] = fields
            
        payload = {"embeds": [embed]}
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            await session.post(config.WEBHOOK_LOG_URL, json=payload, timeout=timeout)
    except Exception as e:
        _safe_print(f"[Tester] Error sending webhook report: {e}")

class SystemTester:
    @staticmethod
    async def run_all_tests() -> bool:
        """Run diagnostic checks on all 11 system modules."""
        _safe_print("🔍 Đang chạy hệ thống tự kiểm thử (Self-Diagnostic Tester)...")
        results = []
        failed_modules = []
        error_details = {}

        # 1. Database Check
        try:
            from database import DB_PATH
            def _test_db():
                with sqlite3.connect(DB_PATH, timeout=5) as conn:
                    conn.execute("PRAGMA journal_mode;").fetchone()
                    conn.execute("SELECT COUNT(*) FROM guilds;").fetchone()
            await asyncio.wait_for(asyncio.to_thread(_test_db), timeout=5.0)
            results.append("🟢 **Database (SQLite WAL)** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Database (SQLite WAL)")
            error_details["Database (SQLite WAL)"] = "TimeoutError: SQLite DB query timed out after 5.0s (DB Locked)."
            results.append("🔴 **Database (SQLite WAL)** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Database (SQLite WAL)")
            error_details["Database (SQLite WAL)"] = traceback.format_exc()
            results.append("🔴 **Database (SQLite WAL)** — FAIL")

        # 2. Cache & Redis Check
        try:
            async def _test_cache():
                test_key = "self_check_test_key"
                await cache.aset(test_key, {"status": "ok"}, ttl=10)
                await cache.aget(test_key)
                await cache.adelete(test_key)
            await asyncio.wait_for(_test_cache(), timeout=5.0)
            cache_type = "Redis" if cache.enabled else "Local Memory Fallback"
            results.append(f"🟢 **Cache ({cache_type})** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Cache & Redis")
            error_details["Cache & Redis"] = "TimeoutError: Cache operation timed out after 5.0s."
            results.append("🔴 **Cache & Redis** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Cache & Redis")
            error_details["Cache & Redis"] = traceback.format_exc()
            results.append("🔴 **Cache & Redis** — FAIL")

        # 3. Music Module Check (yt-dlp & FFmpeg)
        try:
            spec = importlib.util.find_spec("bot.cogs.music")
            if spec is None:
                raise ImportError("Module bot.cogs.music không tìm thấy!")
            import yt_dlp
            ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg", path="/data/data/com.termux/files/usr/bin")
            if not ffmpeg_path:
                raise RuntimeError("Binary FFmpeg không tìm thấy trên hệ thống (PATH / Termux)!")
            results.append("🟢 **Music (yt-dlp & FFmpeg)** — OK")
        except Exception as e:
            failed_modules.append("Music (yt-dlp & FFmpeg)")
            error_details["Music (yt-dlp & FFmpeg)"] = traceback.format_exc()
            results.append("🔴 **Music (yt-dlp & FFmpeg)** — FAIL")

        # 4. AutoMod Check
        try:
            from database import async_get_automod_settings
            await asyncio.wait_for(async_get_automod_settings("0"), timeout=5.0)
            results.append("🟢 **AutoMod Module** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("AutoMod Module")
            error_details["AutoMod Module"] = "TimeoutError: AutoMod settings query timed out after 5.0s."
            results.append("🔴 **AutoMod Module** — TIMEOUT")
        except Exception as e:
            failed_modules.append("AutoMod Module")
            error_details["AutoMod Module"] = traceback.format_exc()
            results.append("🔴 **AutoMod Module** — FAIL")

        # 5. Reaction Roles Check
        try:
            from database import get_reaction_roles_panels
            await asyncio.wait_for(asyncio.to_thread(get_reaction_roles_panels, "0"), timeout=5.0)
            results.append("🟢 **Reaction Roles** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Reaction Roles")
            error_details["Reaction Roles"] = "TimeoutError: Reaction Roles query timed out after 5.0s."
            results.append("🔴 **Reaction Roles** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Reaction Roles")
            error_details["Reaction Roles"] = traceback.format_exc()
            results.append("🔴 **Reaction Roles** — FAIL")

        # 6. Ticket Module Check
        try:
            from database import async_get_all_ticket_panels
            await asyncio.wait_for(async_get_all_ticket_panels(), timeout=5.0)
            results.append("🟢 **Ticket Module** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Ticket Module")
            error_details["Ticket Module"] = "TimeoutError: Ticket query timed out after 5.0s."
            results.append("🔴 **Ticket Module** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Ticket Module")
            error_details["Ticket Module"] = traceback.format_exc()
            results.append("🔴 **Ticket Module** — FAIL")

        # 7. Leveling Module Check
        try:
            from database import async_get_leveling_settings
            await asyncio.wait_for(async_get_leveling_settings("0"), timeout=5.0)
            results.append("🟢 **Leveling Module** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Leveling Module")
            error_details["Leveling Module"] = "TimeoutError: Leveling query timed out after 5.0s."
            results.append("🔴 **Leveling Module** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Leveling Module")
            error_details["Leveling Module"] = traceback.format_exc()
            results.append("🔴 **Leveling Module** — FAIL")

        # 8. Giveaway Module Check
        try:
            from database import async_get_active_giveaways
            await asyncio.wait_for(async_get_active_giveaways(), timeout=5.0)
            results.append("🟢 **Giveaway Module** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Giveaway Module")
            error_details["Giveaway Module"] = "TimeoutError: Giveaway query timed out after 5.0s."
            results.append("🔴 **Giveaway Module** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Giveaway Module")
            error_details["Giveaway Module"] = traceback.format_exc()
            results.append("🔴 **Giveaway Module** — FAIL")

        # 9. Logger & Webhook Check
        try:
            spec = importlib.util.find_spec("bot.cogs.logger")
            if spec is None:
                raise ImportError("Module bot.cogs.logger không tìm thấy!")
            from database import async_get_logger_settings
            await asyncio.wait_for(async_get_logger_settings("0"), timeout=5.0)
            results.append("🟢 **Logger & Webhooks** — OK")
        except asyncio.TimeoutError:
            failed_modules.append("Logger & Webhooks")
            error_details["Logger & Webhooks"] = "TimeoutError: Logger settings query timed out after 5.0s."
            results.append("🔴 **Logger & Webhooks** — TIMEOUT")
        except Exception as e:
            failed_modules.append("Logger & Webhooks")
            error_details["Logger & Webhooks"] = traceback.format_exc()
            results.append("🔴 **Logger & Webhooks** — FAIL")

        # 10. Info & Utility Check
        try:
            spec_u = importlib.util.find_spec("bot.cogs.utility")
            spec_i = importlib.util.find_spec("bot.cogs.info")
            if spec_u is None or spec_i is None:
                raise ImportError("Module bot.cogs.utility/info không tìm thấy!")
            results.append("🟢 **Info & Utility** — OK")
        except Exception as e:
            failed_modules.append("Info & Utility")
            error_details["Info & Utility"] = traceback.format_exc()
            results.append("🔴 **Info & Utility** — FAIL")

        # 11. Admin & System Config Check
        try:
            if not config.TOKEN:
                raise ValueError("DISCORD_TOKEN bị trống trong file .env!")
            results.append("🟢 **Admin & System** — OK")
        except Exception as e:
            failed_modules.append("Admin & System")
            error_details["Admin & System"] = traceback.format_exc()
            results.append("🔴 **Admin & System** — FAIL")

        # ─── Process Results ──────────────────────────────────────────────────
        if failed_modules:
            _safe_print(f"❌ [Tester] Phát hiện lỗi ở {len(failed_modules)} module: {', '.join(failed_modules)}")
            for mod in failed_modules:
                _safe_print(f"\n--- [Lỗi tại {mod}] ---")
                _safe_print(error_details[mod])
            
            # Send failure report to Webhook
            desc = "\n".join(results)
            fields = [
                {
                    "name": f"🚨 Lỗi tại [{mod}]",
                    "value": f"```py\n{error_details[mod][-900:]}\n```"
                }
                for mod in failed_modules[:5] # Max 5 fields for Discord embed
            ]
            await _send_webhook_report(
                title=f"🚨 PHÁT HIỆN LỖI HỆ THỐNG ({len(failed_modules)} MODULES) — DỪNG KHỞI ĐỘNG BOT",
                description=desc,
                color=0xED4245, # Red
                fields=fields
            )
            return False

        # All 11 tests passed!
        _safe_print("✅ [Tester] Tất cả 11/11 modules đã kiểm thử thành công!")
        desc = "\n".join(results) + "\n\n*🎉 Tất cả 11/11 modules kiểm thử thành công! Bot sẵn sàng hoạt động.*"
        await _send_webhook_report(
            title="🚀 BÁO CÁO KIỂM THỬ KHỞI ĐỘNG HỆ THỐNG",
            description=desc,
            color=0x57F287 # Green
        )
        return True

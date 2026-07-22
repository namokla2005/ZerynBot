"""
tester.py — Self-Diagnostic Test Suite for Bot V2.
Runs automated checks for all modules at bot startup.
Reports status to Feedback Webhook and halts startup if any test fails.
"""
import sys
import os
import time
import shutil
import traceback
import sqlite3
import requests

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

def _send_webhook_report(title: str, description: str, color: int, fields: list = None):
    """Utility to send test report to config.WEBHOOK_LOG_URL."""
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
        requests.post(config.WEBHOOK_LOG_URL, json=payload, timeout=10)
    except Exception as e:
        _safe_print(f"[Tester] Error sending webhook report: {e}")

class SystemTester:
    @staticmethod
    async def run_all_tests() -> bool:
        """Run diagnostic checks on all 11 system modules."""
        _safe_print("🔍 Đang chạy hệ thống tự kiểm thử (Self-Diagnostic Tester)...")
        results = []
        failed_module = None
        error_traceback = ""

        # 1. Database Check
        try:
            from database import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                conn.execute("SELECT COUNT(*) FROM guilds;").fetchone()
            results.append("🟢 **Database (SQLite WAL)** — OK")
        except Exception as e:
            failed_module = "Database (SQLite WAL)"
            error_traceback = traceback.format_exc()
            results.append("🔴 **Database (SQLite WAL)** — FAIL")

        # 2. Cache & Redis Check
        if not failed_module:
            try:
                test_key = "self_check_test_key"
                await cache.aset(test_key, {"status": "ok"}, ttl=10)
                val = await cache.aget(test_key)
                await cache.adelete(test_key)
                cache_type = "Redis" if cache.enabled else "Local Memory Fallback"
                results.append(f"🟢 **Cache ({cache_type})** — OK")
            except Exception as e:
                failed_module = "Cache & Redis"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Cache & Redis** — FAIL")

        # 3. Music Module Check (yt-dlp & FFmpeg)
        if not failed_module:
            try:
                import yt_dlp
                from bot.cogs.music import _get_stream_url
                ffmpeg_path = shutil.which("ffmpeg")
                if not ffmpeg_path:
                    raise RuntimeError("Binary FFmpeg không tìm thấy trên hệ thống (PATH)!")
                results.append("🟢 **Music (yt-dlp & FFmpeg)** — OK")
            except Exception as e:
                failed_module = "Music (yt-dlp & FFmpeg)"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Music (yt-dlp & FFmpeg)** — FAIL")

        # 4. AutoMod Check
        if not failed_module:
            try:
                from bot.cogs.automod import URL_PATTERN, DISCORD_INVITE_PATTERN
                from database import async_get_automod_settings
                await async_get_automod_settings("0")
                results.append("🟢 **AutoMod Module** — OK")
            except Exception as e:
                failed_module = "AutoMod Module"
                error_traceback = traceback.format_exc()
                results.append("🔴 **AutoMod Module** — FAIL")

        # 5. Reaction Roles Check
        if not failed_module:
            try:
                from database import get_reaction_roles_panels
                get_reaction_roles_panels("0")
                results.append("🟢 **Reaction Roles** — OK")
            except Exception as e:
                failed_module = "Reaction Roles"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Reaction Roles** — FAIL")

        # 6. Ticket Module Check
        if not failed_module:
            try:
                from database import get_ticket_panels
                get_ticket_panels("0")
                results.append("🟢 **Ticket Module** — OK")
            except Exception as e:
                failed_module = "Ticket Module"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Ticket Module** — FAIL")

        # 7. Leveling Module Check
        if not failed_module:
            try:
                from database import async_get_leveling_settings
                await async_get_leveling_settings("0")
                results.append("🟢 **Leveling Module** — OK")
            except Exception as e:
                failed_module = "Leveling Module"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Leveling Module** — FAIL")

        # 8. Giveaway Module Check
        if not failed_module:
            try:
                from database import async_get_active_giveaways
                await async_get_active_giveaways()
                results.append("🟢 **Giveaway Module** — OK")
            except Exception as e:
                failed_module = "Giveaway Module"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Giveaway Module** — FAIL")

        # 9. Logger & Webhook Check
        if not failed_module:
            try:
                from database import async_get_logger_settings
                from bot.cogs.logger import COLOR_INFO
                await async_get_logger_settings("0")
                results.append("🟢 **Logger & Webhooks** — OK")
            except Exception as e:
                failed_module = "Logger & Webhooks"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Logger & Webhooks** — FAIL")

        # 10. Info & Utility Check
        if not failed_module:
            try:
                from bot.cogs.utility import Utility
                from bot.cogs.info import Info
                results.append("🟢 **Info & Utility** — OK")
            except Exception as e:
                failed_module = "Info & Utility"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Info & Utility** — FAIL")

        # 11. Admin & System Config Check
        if not failed_module:
            try:
                if not config.TOKEN:
                    raise ValueError("DISCORD_TOKEN bị trống trong file .env!")
                results.append("🟢 **Admin & System** — OK")
            except Exception as e:
                failed_module = "Admin & System"
                error_traceback = traceback.format_exc()
                results.append("🔴 **Admin & System** — FAIL")

        # ─── Process Results ──────────────────────────────────────────────────
        if failed_module:
            _safe_print(f"❌ [Tester] Phát hiện lỗi ở module: {failed_module}")
            _safe_print(error_traceback)
            
            # Send failure report to Webhook
            desc = "\n".join(results)
            fields = [
                {
                    "name": f"🚨 Chi tiết lỗi tại [{failed_module}]",
                    "value": f"```py\n{error_traceback[:1000]}\n```"
                }
            ]
            _send_webhook_report(
                title="🚨 PHÁT HIỆN LỖI HỆ THỐNG — DỪNG KHỞI ĐỘNG BOT",
                description=desc,
                color=0xED4245, # Red
                fields=fields
            )
            return False

        # All 11 tests passed!
        _safe_print("✅ [Tester] Tất cả 11/11 modules đã kiểm thử thành công!")
        desc = "\n".join(results) + "\n\n*🎉 Tất cả 11/11 modules kiểm thử thành công! Bot sẵn sàng hoạt động.*"
        _send_webhook_report(
            title="🚀 BÁO CÁO KIỂM THỬ KHỞI ĐỘNG HỆ THỐNG",
            description=desc,
            color=0x57F287 # Green
        )
        return True

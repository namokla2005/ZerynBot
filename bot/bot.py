"""
bot.py — Discord Bot v2 entry point.
Uses discord.py app_commands (slash commands) as primary interface.
"""
import asyncio
import logging
import sys
import os
import json
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone

# Add v2/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands
import config
from database import init_db

from logging.handlers import RotatingFileHandler

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BotV2")

try:
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "bot.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)
except Exception as exc:
    sys.stderr.write(f"Failed to setup RotatingFileHandler: {exc}\n")


class DiscordWebhookHandler(logging.Handler):
    """Sends ERROR and CRITICAL logs to a Discord Webhook (Non-blocking)."""

    def __init__(self, webhook_url: str):
        super().__init__(level=logging.ERROR)
        self.webhook_url = webhook_url
        self.last_sent = 0.0

    def emit(self, record: logging.LogRecord):
        # Rate limit sending to webhook (1 message per 5 seconds max)
        now = time.time()
        if now - self.last_sent < 5.0:
            return
        self.last_sent = now
        threading.Thread(target=self._send, args=(record,), daemon=True).start()

    def _send(self, record: logging.LogRecord):
        import requests
        try:
            log_entry = self.format(record)
            # Truncate if too long (keep the bottom error traceback tail)
            if len(log_entry) > 3900:
                log_entry = "... (truncated)\n" + log_entry[-3900:]

            embed = {
                "title": f"🚨 Bot Error: {record.levelname}",
                "description": f"```py\n{log_entry}\n```",
                "color": 0xED4245 if record.levelno >= logging.ERROR else 0xFEE75C,
                "footer": {"text": f"File: {record.filename} | Line: {record.lineno}"},
            }

            payload = {"embeds": [embed]}
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception:
            pass  # Silently fail if webhook is invalid or network error


# ─── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True


# ─── Bot class ─────────────────────────────────────────────────────────────────
class BotV2(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("/"),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )

        # Rate limit state
        self.last_used = defaultdict(float)

    async def _cleanup_cooldowns(self):
        """Dọn entry cooldown cũ hơn 60 giây mỗi 5 phút."""
        while not self.is_closed():
            await asyncio.sleep(300)
            now = time.time()
            expired = [uid for uid, t in self.last_used.items() if now - t > 60]
            for uid in expired:
                del self.last_used[uid]
            if expired:
                logger.debug(f"[Cooldown] Cleaned {len(expired)} expired entries")

    # ─── Health-check (Lớp 1: tự phát hiện & thoát khi offline lâu) ─────────────
    # Bot ghi data/health.json để dashboard trả /health. Khi bot offline quá
    # OFFLINE_THRESHOLD giây, _offline_watchdog_task sẽ close() cho watchdog
    # bên ngoài restart → bot tự online lại sau mất mạng.
    HEALTH_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "health.json",
    )
    OFFLINE_THRESHOLD = 5 * 60  # 5 phút: đủ thời gian cho wifi khôi phục tạm thời

    def _write_health_sync(self, online: bool):
        """Ghi health.json dạng atomic (chạy trong executor để không block loop)."""
        try:
            os.makedirs(os.path.dirname(self.HEALTH_FILE), exist_ok=True)
            now_iso = datetime.now(timezone.utc).isoformat()
            data = {
                "online": online,
                "last_ready": getattr(self, "_last_ready_iso", now_iso if online else None),
                "last_change": now_iso,
                "pid": os.getpid(),
            }
            tmp = self.HEALTH_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.HEALTH_FILE)  # atomic trên cùng filesystem
        except Exception as e:
            logger.debug(f"[Health] write failed: {e}")

    async def _write_health(self, online: bool):
        """Wrapper async: đẩy ghi file sang thread pool."""
        if online:
            self._last_ready_iso = datetime.now(timezone.utc).isoformat()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_health_sync, online)

    async def on_disconnect(self):
        """discord.py gọi khi mất kết nối gateway. Ghi offline ngay."""
        logger.warning("⚠️  Mất kết nối Discord gateway (on_disconnect).")
        await self._write_health(False)

    async def on_resumed(self):
        """discord.py gọi khi reconnect thành công (không qua on_ready)."""
        logger.info("🔄  Đã kết nối lại Discord (on_resumed).")
        await self._write_health(True)

    async def _offline_watchdog_task(self):
        """Kiểm tra mỗi 60s: nếu bot chưa ready quá OFFLINE_THRESHOLD giây → close().

        Khi close(), process exit != 0 → watchdog bên ngoài thấy và restart.
        Đây là cơ chế tự cứu khi discord.py reconnect thất bại vĩnh viễn.
        KHÔNG dùng before_loop/wait_until_ready vì mục đích chính là phát hiện khi chưa ready.
        """
        disconnected_at = None
        while not self.is_closed():
            await asyncio.sleep(60)
            if self.is_ready():
                disconnected_at = None  # reset khi đang khỏe
                continue
            # Chưa ready / đang offline
            if disconnected_at is None:
                disconnected_at = time.time()
                logger.warning(f"[Health] Bot chưa ready — bắt đầu đếm thời gian offline.")
            else:
                elapsed = time.time() - disconnected_at
                logger.warning(
                    f"[Health] Bot offline đã {int(elapsed)}s / {self.OFFLINE_THRESHOLD}s"
                )
                if elapsed >= self.OFFLINE_THRESHOLD:
                    logger.error(
                        f"[Health] Bot offline quá {self.OFFLINE_THRESHOLD}s — "
                        f"tự close() để watchdog restart."
                    )
                    await self._write_health(False)
                    try:
                        await self.close()
                    except Exception as e:
                        logger.error(f"[Health] close() error: {e}")
                    return

    async def setup_hook(self):
        """Load all cogs, then sync slash commands if --sync flag is passed."""

        # ─── Health-check init: bot đang starting → ghi offline ──
        await self._write_health(False)
        # Khởi động task nội bộ phát hiện offline lâu
        self._health_task = asyncio.create_task(self._offline_watchdog_task())
        # ─────────────────────────────────────────────────────────

        # ─── Global Cooldown Check ──────────────────────────────
        async def global_cooldown_check(interaction: discord.Interaction) -> bool:
            # Bypass for bot owner
            if interaction.user.id == config.BOT_OWNER_ID:
                return True

            now = time.time()
            user_id = interaction.user.id
            if now - self.last_used[user_id] < config.GLOBAL_COOLDOWN:
                remaining = int(config.GLOBAL_COOLDOWN - (now - self.last_used[user_id]))
                await interaction.response.send_message(
                    f"⏳ Vui lòng đợi {remaining}s nữa trước khi dùng lệnh.", ephemeral=True
                )
                return False

            self.last_used[user_id] = now
            return True

        self.tree.interaction_check = global_cooldown_check
        self.tree.on_error = self.on_app_command_error
        # ────────────────────────────────────────────────────────

        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                ext = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext)
                    logger.info(f"✅  Loaded: {ext}")
                except Exception as exc:
                    logger.error(f"❌  Failed {ext}: {exc}")

        # Sync slash commands chỉ khi có cờ --sync
        if "--sync" in sys.argv:
            if config.DEV_GUILD_ID:
                guild_obj = discord.Object(id=config.DEV_GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced_dev = await self.tree.sync(guild=guild_obj)
                logger.info(f"⚡  Synced {len(synced_dev)} commands to dev guild (instant)")

            synced_global = await self.tree.sync()
            logger.info(
                f"🌐  Synced {len(synced_global)} commands globally (up to 1 hour to propagate)"
            )
        else:
            logger.info("⚡  Skipping command sync (run with 'python bot/bot.py --sync' to force sync)")

    async def on_ready(self):
        if not hasattr(self, "_ready_once"):
            self._ready_once = True
            self._cleanup_task = asyncio.create_task(self._cleanup_cooldowns())
            logger.info("─" * 55)
            logger.info(f"✅  Online: {self.user} (ID: {self.user.id})")
            logger.info(f"🌐  Servers: {len(self.guilds)}")
            logger.info(f"📊  Dashboard: {config.DASHBOARD_URL}")
            logger.info("─" * 55)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"/help | {len(self.guilds)} server(s) | {sum(g.member_count for g in self.guilds)} member(s)",
            )
        )
        logger.info(f"🔄  Ready/Reconnected: {self.user} | {len(self.guilds)} servers")
        await self._write_health(True)  # Health-check: bot đã online

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        logger.error(f"Command error: {error}")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ):
        msg = "⚠️ Có lỗi xảy ra khi thực hiện lệnh này."
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "❌ Bạn không có quyền sử dụng lệnh này."
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            msg = "❌ Bot thiếu quyền để thực hiện hành động này."

        embed = discord.Embed(description=msg, color=config.COLOR_ERROR)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass
        logger.error(f"App command error: {error}")


bot = BotV2()

# ─── Main ──────────────────────────────────────────────────────────────────────
async def main():
    if not config.TOKEN:
        logger.error("❌  DISCORD_TOKEN missing! Set it in .env")
        return

    init_db()
    logger.info("✅  Database ready")

    # ─── Self-Diagnostic Tester ─────────────────────────────
    try:
        from tester import SystemTester
        test_passed = await SystemTester.run_all_tests()
        if not test_passed:
            logger.warning("⚠️  Self-Diagnostic Test reported warnings, proceeding with bot startup...")
    except Exception as e:
        logger.warning(f"⚠️  Self-Diagnostic Test error: {e}")
    # ────────────────────────────────────────────────────────

    if config.WEBHOOK_LOG_URL:
        webhook_handler = DiscordWebhookHandler(config.WEBHOOK_LOG_URL)
        webhook_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(webhook_handler)
        logger.info("✅  Webhook logging enabled")

    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

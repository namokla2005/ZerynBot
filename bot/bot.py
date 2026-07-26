"""
bot.py — Discord Bot v2 entry point.
Uses discord.py app_commands (slash commands) as primary interface.
"""
import asyncio
import logging
import sys
import os
import time
import threading
from collections import defaultdict

# Add v2/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands
import config
from database import init_db

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BotV2")


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

    async def setup_hook(self):
        """Load all cogs, then sync slash commands if --sync flag is passed."""

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
        from bot.tester import SystemTester
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

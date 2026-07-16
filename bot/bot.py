"""
bot.py — Discord Bot v2 entry point.
Uses discord.py app_commands (slash commands) as primary interface.
"""
import asyncio
import logging
import sys
import os

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

# ─── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ─── Bot class ─────────────────────────────────────────────────────────────────
class BotV2(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("/"),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )

    async def setup_hook(self):
        """Load all cogs, then sync slash commands."""
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                ext = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext)
                    logger.info(f"✅  Loaded: {ext}")
                except Exception as exc:
                    logger.error(f"❌  Failed {ext}: {exc}")

        # Sync slash commands
        if config.DEV_GUILD_ID:
            guild_obj = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            synced_dev = await self.tree.sync(guild=guild_obj)
            logger.info(f"⚡  Synced {len(synced_dev)} commands to dev guild (instant)")
        
        synced_global = await self.tree.sync()
        logger.info(f"🌐  Synced {len(synced_global)} commands globally (up to 1 hour to propagate)")

    async def on_ready(self):
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} server(s) | /help",
            )
        )
        logger.info("─" * 55)
        logger.info(f"✅  Online: {self.user} (ID: {self.user.id})")
        logger.info(f"🌐  Servers: {len(self.guilds)}")
        logger.info(f"📊  Dashboard: {config.DASHBOARD_URL}")
        logger.info("─" * 55)

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

    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

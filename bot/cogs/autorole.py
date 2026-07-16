import discord
from discord.ext import commands
from discord import app_commands
import json
import aiosqlite

from database import DB_PATH, async_is_module_enabled, async_get_guild_settings
from bot import checks

class AutoRole(commands.Cog, name="AutoRole"):
    """Cấu hình Auto Roles qua Discord"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not await async_is_module_enabled(str(ctx.guild.id), "autoroles"):
            await ctx.send("❌ Module Auto Roles hiện đang bị tắt. Vui lòng bật trên Dashboard.")
            return False
        return True

    @commands.hybrid_group(name="autorole", description="Cấu hình Auto Roles qua Discord")
    @app_commands.default_permissions(manage_roles=True)
    @checks.is_bot_admin()
    async def autorole(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await self.show(ctx)

    @autorole.command(name="show", description="Xem cấu hình Auto Roles hiện tại")
    @app_commands.default_permissions(manage_roles=True)
    async def show(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if not await async_is_module_enabled(guild_id, "autoroles"):
            await ctx.send("❌ Module Auto Roles hiện đang bị tắt. Vui lòng bật trên Dashboard.", ephemeral=True)
            return

        settings = await async_get_guild_settings(guild_id)
        enabled = int(settings.get("autoroles_enabled", 0))
        
        roles_user_str = settings.get("autoroles_user", "[]")
        roles_bot_str = settings.get("autoroles_bot", "[]")
        
        try:
            roles_user = json.loads(roles_user_str)
            roles_bot = json.loads(roles_bot_str)
        except Exception:
            roles_user, roles_bot = [], []
            
        user_mentions = [f"<@&{r}>" for r in roles_user] if roles_user else ["*Không có*"]
        bot_mentions = [f"<@&{r}>" for r in roles_bot] if roles_bot else ["*Không có*"]
        
        embed = discord.Embed(
            title="⚙️ Cấu hình Auto Roles",
            color=0x5865F2 if enabled else 0xED4245
        )
        embed.add_field(name="Trạng thái", value="✅ Đã bật" if enabled else "❌ Đã tắt", inline=False)
        embed.add_field(name="Roles cho Thành viên", value=", ".join(user_mentions), inline=False)
        embed.add_field(name="Roles cho Bot", value=", ".join(bot_mentions), inline=False)
        
        await ctx.send(embed=embed)



async def setup(bot):
    await bot.add_cog(AutoRole(bot))

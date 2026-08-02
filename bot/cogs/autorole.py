import discord
from discord.ext import commands
from discord import app_commands
import json
import aiosqlite

from database import DB_PATH, async_is_module_enabled, async_get_guild_settings
import checks
from i18n import tr

class AutoRole(commands.Cog, name="AutoRole"):
    """Cấu hình Auto Roles qua Discord"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not await async_is_module_enabled(str(ctx.guild.id), "autoroles"):
            s = await async_get_guild_settings(str(ctx.guild.id))
            await ctx.send(tr(s, "autorole.disabled_msg"))
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
        settings = await async_get_guild_settings(guild_id)
        if not await async_is_module_enabled(guild_id, "autoroles"):
            await ctx.send(tr(settings, "autorole.disabled_msg"), ephemeral=True)
            return

        enabled = int(settings.get("autoroles_enabled", 0))
        
        roles_user_str = settings.get("autoroles_user", "[]")
        roles_bot_str = settings.get("autoroles_bot", "[]")
        
        try:
            roles_user = json.loads(roles_user_str)
            roles_bot = json.loads(roles_bot_str)
        except Exception:
            roles_user, roles_bot = [], []
            
        none_txt = tr(settings, "automod.none")
        user_mentions = [f"<@&{r}>" for r in roles_user] if roles_user else [none_txt]
        bot_mentions = [f"<@&{r}>" for r in roles_bot] if roles_bot else [none_txt]
        
        embed = discord.Embed(
            title=tr(settings, "autorole.title"),
            color=0x5865F2 if enabled else 0xED4245
        )
        embed.add_field(name=tr(settings, "autorole.status"), value=tr(settings, "autorole.enabled") if enabled else tr(settings, "autorole.disabled"), inline=False)
        embed.add_field(name=tr(settings, "autorole.user_roles"), value=", ".join(user_mentions), inline=False)
        embed.add_field(name=tr(settings, "autorole.bot_roles"), value=", ".join(bot_mentions), inline=False)
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoRole(bot))


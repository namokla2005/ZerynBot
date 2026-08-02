"""
Cog: Admin (v2) — config prefix command for server admins.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import async_get_guild_settings, async_is_module_enabled
import checks
from i18n import tr


class Admin(commands.Cog):
    """Lệnh quản trị server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="config", description="Xem cài đặt hiện tại của server và link dashboard")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def config_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)

        wc = s.get("welcome_channel_id")
        gc = s.get("goodbye_channel_id")
        not_cfg = tr(s, "admin.not_configured")
        w_ch  = f"<#{wc}>" if wc else not_cfg
        g_ch  = f"<#{gc}>" if gc else not_cfg
        w_type = tr(s, "admin.embed_type") if s.get("welcome_use_embed") else tr(s, "admin.text_type")
        g_type = tr(s, "admin.embed_type") if s.get("goodbye_use_embed") else tr(s, "admin.text_type")

        modules = {
            "welcome_goodbye": await async_is_module_enabled(guild_id, "welcome_goodbye"),
            "autoroles":       await async_is_module_enabled(guild_id, "autoroles"),
            "leveling":        await async_is_module_enabled(guild_id, "leveling"),
            "info":            await async_is_module_enabled(guild_id, "info"),
            "utility":         await async_is_module_enabled(guild_id, "utility"),
            "music":           await async_is_module_enabled(guild_id, "music"),
            "tickets":         await async_is_module_enabled(guild_id, "tickets"),
            "reactionroles":   await async_is_module_enabled(guild_id, "reactionroles"),
            "automods":        await async_is_module_enabled(guild_id, "automods"),
            "logger":          await async_is_module_enabled(guild_id, "logger"),
            "giveaways":       await async_is_module_enabled(guild_id, "giveaways")
        }
        
        # Split into two columns for better formatting
        mod_keys = list(modules.keys())
        half = (len(mod_keys) + 1) // 2
        
        mod_col1 = "\n".join(f"{'✅' if modules[k] else '❌'} `{k}`" for k in mod_keys[:half])
        mod_col2 = "\n".join(f"{'✅' if modules[k] else '❌'} `{k}`" for k in mod_keys[half:])

        embed = discord.Embed(
            title=tr(s, "admin.config_title", server=ctx.guild.name),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name=tr(s, "admin.welcome_channel"),  value=w_ch,    inline=True)
        embed.add_field(name=tr(s, "admin.welcome_type"),     value=w_type,  inline=True)
        embed.add_field(name="\u200b",                         value="\u200b",inline=True)
        embed.add_field(name=tr(s, "admin.goodbye_channel"),  value=g_ch,    inline=True)
        embed.add_field(name=tr(s, "admin.goodbye_type"),     value=g_type,  inline=True)
        embed.add_field(name="\u200b",                         value="\u200b",inline=True)
        
        embed.add_field(name=tr(s, "admin.modules_label", num=1), value=mod_col1, inline=True)
        embed.add_field(name=tr(s, "admin.modules_label", num=2), value=mod_col2, inline=True)
        embed.add_field(name="\u200b",                            value="\u200b",inline=True)

        embed.add_field(
            name=tr(s, "admin.dashboard_label"),
            value=f"[{tr(s, 'admin.open_dashboard')}]({config.DASHBOARD_URL}/dashboard/{guild_id})",
            inline=False,
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=tr(s, "admin.open_dashboard"), style=discord.ButtonStyle.link, url=f"{config.DASHBOARD_URL}/dashboard/{guild_id}", emoji="🌐"))

        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="reactionroles", description="Truy cập Dashboard để tạo bảng Reaction Roles")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def reactionroles_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)
        embed = discord.Embed(
            title=tr(s, "admin.rr_title"),
            description=tr(s, "admin.rr_desc"),
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[{tr(s, 'admin.open_config')}]({config.DASHBOARD_URL}/dashboard/{guild_id}/reactionroles)"
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sync", description="Đồng bộ lệnh slash commands (Admin only)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def sync_cmd(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        async with ctx.typing():
            synced = await self.bot.tree.sync()
            await ctx.send(tr(s, "admin.sync_success", count=len(synced)))

    @commands.hybrid_command(name="ticket", description="Truy cập Dashboard để tạo panel ticket")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def ticket_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)
        embed = discord.Embed(
            title=tr(s, "admin.ticket_title"),
            description=tr(s, "admin.ticket_desc"),
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[{tr(s, 'admin.open_config')}]({config.DASHBOARD_URL}/dashboard/{guild_id}/tickets)"
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))


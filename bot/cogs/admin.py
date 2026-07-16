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
from bot import checks


class Admin(commands.Cog):
    """Lệnh quản trị server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="config", description="Xem cài đặt hiện tại của server và link dashboard")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def config_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)

        wc = s.get("welcome_channel_id")
        gc = s.get("goodbye_channel_id")
        w_ch  = f"<#{wc}>" if wc else "⚠️ Chưa cài đặt"
        g_ch  = f"<#{gc}>" if gc else "⚠️ Chưa cài đặt"
        w_type = "📦 Embed" if s.get("welcome_use_embed") else "💬 Text"
        g_type = "📦 Embed" if s.get("goodbye_use_embed") else "💬 Text"

        modules = {
            "utility":         await async_is_module_enabled(guild_id, "utility"),
            "welcome_goodbye": await async_is_module_enabled(guild_id, "welcome_goodbye"),
            "info":            await async_is_module_enabled(guild_id, "info"),
            "music":           await async_is_module_enabled(guild_id, "music"),
        }
        mod_str = "\n".join(
            f"{'✅' if v else '❌'} `{k}`" for k, v in modules.items()
        )

        embed = discord.Embed(
            title=f"⚙️ Cài đặt — {ctx.guild.name}",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🎉 Welcome Channel",  value=w_ch,    inline=True)
        embed.add_field(name="🎉 Kiểu tin nhắn",    value=w_type,  inline=True)
        embed.add_field(name="\u200b",               value="\u200b",inline=True)
        embed.add_field(name="👋 Goodbye Channel",  value=g_ch,    inline=True)
        embed.add_field(name="👋 Kiểu tin nhắn",    value=g_type,  inline=True)
        embed.add_field(name="\u200b",               value="\u200b",inline=True)
        embed.add_field(name="🧩 Modules",           value=mod_str, inline=False)
        embed.add_field(
            name="🌐 Dashboard",
            value=f"[Mở Dashboard]({config.DASHBOARD_URL}/dashboard/{guild_id})",
            inline=False,
        )

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="reactionroles", description="Truy cập Dashboard để tạo bảng Reaction Roles")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def reactionroles_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        embed = discord.Embed(
            title="🎭 Reaction Roles",
            description="Tính năng này được cấu hình trực quan thông qua Dashboard.",
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[Mở trang cấu hình]({config.DASHBOARD_URL}/dashboard/{guild_id}/reactionroles)"
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sync", description="Đồng bộ lệnh slash commands (Admin only)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def sync_cmd(self, ctx: commands.Context):
        async with ctx.typing():
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ Đã đồng bộ {len(synced)} lệnh slash commands.")

    @commands.hybrid_command(name="ticket", description="Truy cập Dashboard để tạo panel ticket")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def ticket_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        embed = discord.Embed(
            title="🎫 Ticket System",
            description="Tính năng này được cấu hình trực quan thông qua Dashboard.",
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[Mở trang cấu hình]({config.DASHBOARD_URL}/dashboard/{guild_id}/tickets)"
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))

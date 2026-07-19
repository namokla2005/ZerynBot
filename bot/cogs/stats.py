import discord
from discord.ext import commands
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import async_increment_stat

class Stats(commands.Cog):
    """Ghi nhận số liệu hoạt động ngầm để phục vụ cho Dashboard Analytics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
            
        guild_id = str(message.guild.id)
        # Increment total messages
        await async_increment_stat(guild_id, "message", "total")
        # Increment channel specific messages for top channels chart
        await async_increment_stat(guild_id, "channel_message", str(message.channel.id))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        await async_increment_stat(guild_id, "member", "join")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        await async_increment_stat(guild_id, "member", "leave")

    @commands.Cog.listener()
    async def on_automod_action(self, guild: discord.Guild, user: discord.Member, action_type: str, reason: str, jump_url: str = None):
        guild_id = str(guild.id)
        # Shorten action type for label if needed
        action_label = "warn" if "Cảnh báo" in action_type else ("timeout" if "Timeout" in action_type else "other")
        await async_increment_stat(guild_id, "automod", action_label)

    @commands.Cog.listener()
    async def on_ticket_action(self, guild: discord.Guild, user: discord.Member, action_type: str, ticket_name: str):
        guild_id = str(guild.id)
        action_label = "open" if "Mở" in action_type else ("close" if "Đóng" in action_type else "other")
        await async_increment_stat(guild_id, "ticket", action_label)

async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))

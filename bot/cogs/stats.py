import discord
from discord.ext import commands
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import async_increment_stat

class Stats(commands.Cog):
    """Ghi nhận số liệu hoạt động ngầm để phục vụ cho Dashboard Analytics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stat_buffer: dict = {}  # {(guild_id, stat_type, stat_key): count}
        self._flush_task = asyncio.create_task(self._flush_stats())

    def cog_unload(self):
        self._flush_task.cancel()
        if self._stat_buffer:
            asyncio.create_task(self._force_flush())

    async def _flush_stats(self):
        """Gom stats và ghi vào DB mỗi 30 giây thay vì mỗi event."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(30)
            if not self._stat_buffer:
                continue
            buffer = self._stat_buffer.copy()
            self._stat_buffer.clear()
            for (guild_id, stat_type, stat_key), count in buffer.items():
                try:
                    await async_increment_stat(guild_id, stat_type, stat_key, count)
                except Exception as e:
                    print(f"[Stats] Flush error: {e}")

    async def _force_flush(self):
        """Flush khẩn cấp khi cog bị unload."""
        buffer = self._stat_buffer.copy()
        self._stat_buffer.clear()
        for (guild_id, stat_type, stat_key), count in buffer.items():
            try:
                await async_increment_stat(guild_id, stat_type, stat_key, count)
            except Exception as e:
                print(f"[Stats] Force flush error: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
            
        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)

        key_total = (guild_id, "message", "total")
        key_channel = (guild_id, "channel_message", channel_id)

        self._stat_buffer[key_total] = self._stat_buffer.get(key_total, 0) + 1
        self._stat_buffer[key_channel] = self._stat_buffer.get(key_channel, 0) + 1

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        key = (guild_id, "member", "join")
        self._stat_buffer[key] = self._stat_buffer.get(key, 0) + 1

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        key = (guild_id, "member", "leave")
        self._stat_buffer[key] = self._stat_buffer.get(key, 0) + 1

    @commands.Cog.listener()
    async def on_automod_action(self, guild: discord.Guild, user: discord.Member, action_type: str, reason: str, jump_url: str = None):
        guild_id = str(guild.id)
        is_warn = "Cảnh báo" in action_type or "Warn" in action_type or "Warning" in action_type
        is_timeout = "Timeout" in action_type or "Aislamiento" in action_type or "Castigo" in action_type or "Exclusion" in action_type or "禁言" in action_type
        action_label = "warn" if is_warn else ("timeout" if is_timeout else "other")
        key = (guild_id, "automod", action_label)
        self._stat_buffer[key] = self._stat_buffer.get(key, 0) + 1

    @commands.Cog.listener()
    async def on_ticket_action(self, guild: discord.Guild, user: discord.Member, action_type: str, ticket_name: str):
        guild_id = str(guild.id)
        is_open = "Mở" in action_type or "Open" in action_type or "Created" in action_type
        is_close = "Đóng" in action_type or "Close" in action_type or "Deleted" in action_type
        action_label = "open" if is_open else ("close" if is_close else "other")
        key = (guild_id, "ticket", action_label)
        self._stat_buffer[key] = self._stat_buffer.get(key, 0) + 1

async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))


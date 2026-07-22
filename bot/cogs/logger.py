import discord
from discord.ext import commands
import time
import datetime
import traceback
import config
from database import async_get_logger_settings, async_is_module_enabled

COLOR_CREATE = 0x57F287
COLOR_DELETE = 0xED4245
COLOR_UPDATE = 0xFEE75C
COLOR_JOIN = 0x57F287
COLOR_LEAVE = 0xED4245
COLOR_MOD = 0xEB459E
COLOR_INFO = 0x3498DB

class Logger(commands.Cog):
    """Ghi lại nhật ký các hoạt động trong server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_log_channel(self, guild: discord.Guild, event_key: str):
        guild_id = str(guild.id)
        if not await async_is_module_enabled(guild_id, "logger"):
            return None
            
        settings = await async_get_logger_settings(guild_id)
        if not settings.get("log_channel_id"):
            return None
            
        # Check if this specific event type is enabled
        if not settings.get(event_key, 0):
            return None
            
        channel = guild.get_channel(int(settings["log_channel_id"]))
        return channel

    # 1. Message Events
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
            
        log_channel = await self.get_log_channel(message.guild, "log_message_delete")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🗑️ Tin nhắn bị xóa",
            description=f"Tin nhắn của {message.author.mention} bị xóa trong {message.channel.mention}",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Nội dung", value=message.content[:1024] or "*Không có nội dung*", inline=False)
        embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"Message ID: {message.id}")
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
            
        log_channel = await self.get_log_channel(before.guild, "log_message_edit")
        if not log_channel: return
        
        embed = discord.Embed(
            title="✏️ Tin nhắn được chỉnh sửa",
            description=f"Tin nhắn của {before.author.mention} được chỉnh sửa trong {before.channel.mention} [Jump]({after.jump_url})",
            color=COLOR_UPDATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Trước đó", value=before.content[:1024] or "*Trống*", inline=False)
        embed.add_field(name="Sau khi sửa", value=after.content[:1024] or "*Trống*", inline=False)
        embed.set_author(name=f"{before.author.name} ({before.author.id})", icon_url=before.author.display_avatar.url)
        embed.set_footer(text=f"Message ID: {before.id}")
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 2. Member Events
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log_channel = await self.get_log_channel(member.guild, "log_member_join_leave")
        if not log_channel: return
        
        embed = discord.Embed(
            title="📥 Thành viên tham gia",
            description=f"{member.mention} đã tham gia server",
            color=COLOR_JOIN,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="Ngày tạo tài khoản", value=f"<t:{int(member.created_at.timestamp())}:R>")
        embed.set_author(name=f"{member.name} ({member.id})", icon_url=member.display_avatar.url)
        embed.set_footer(text=f"Thành viên thứ #{member.guild.member_count}")
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        log_channel = await self.get_log_channel(member.guild, "log_member_join_leave")
        if not log_channel: return
        
        # Could check audit log for kick, but Discord intents can make it tricky. We'll just log "Leave/Kick" here.
        # on_member_ban handles bans.
        embed = discord.Embed(
            title="📤 Thành viên rời đi",
            description=f"{member.mention} đã rời khỏi server",
            color=COLOR_LEAVE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{member.name} ({member.id})", icon_url=member.display_avatar.url)
        
        # Check audit log for kick
        if member.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        embed.title = "👢 Thành viên bị Kick"
                        embed.description = f"{member.mention} đã bị Kick khỏi server bởi {entry.user.mention}"
                        embed.add_field(name="Lý do", value=entry.reason or "*Không có*")
                        break
            except Exception:
                pass
                
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self.get_log_channel(guild, "log_member_kick_ban")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🔨 Thành viên bị Ban",
            description=f"{user.mention} đã bị Ban khỏi server",
            color=COLOR_MOD,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if user.display_avatar else None)
        
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                    if entry.target.id == user.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        embed.description = f"{user.mention} đã bị Ban bởi {entry.user.mention}"
                        embed.add_field(name="Lý do", value=entry.reason or "*Không có*")
                        break
            except Exception:
                pass
                
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self.get_log_channel(guild, "log_member_kick_ban")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🕊️ Thành viên được Unban",
            description=f"{user.mention} đã được gỡ Ban",
            color=COLOR_JOIN,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if user.display_avatar else None)
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
            
        log_channel = await self.get_log_channel(before.guild, "log_member_role_change")
        if not log_channel: return
        
        added_roles = [r for r in after.roles if r not in before.roles]
        removed_roles = [r for r in before.roles if r not in after.roles]
        
        if not added_roles and not removed_roles:
            return
            
        embed = discord.Embed(
            title="🛡️ Thay đổi Role",
            description=f"Role của {before.mention} đã bị thay đổi",
            color=COLOR_UPDATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{before.name} ({before.id})", icon_url=before.display_avatar.url)
        
        if added_roles:
            embed.add_field(name="Thêm Role", value=" ".join([r.mention for r in added_roles]), inline=False)
        if removed_roles:
            embed.add_field(name="Bớt Role", value=" ".join([r.mention for r in removed_roles]), inline=False)
            
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 3. Channel Events
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        log_channel = await self.get_log_channel(channel.guild, "log_channel_change")
        if not log_channel: return
        
        embed = discord.Embed(
            title="📁 Kênh được tạo mới",
            description=f"Kênh {channel.mention} (`{channel.name}`) vừa được tạo",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        log_channel = await self.get_log_channel(channel.guild, "log_channel_change")
        if not log_channel: return
        
        embed = discord.Embed(
            title="📁 Kênh bị xóa",
            description=f"Kênh `{channel.name}` đã bị xóa",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 4. Role Events
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        log_channel = await self.get_log_channel(role.guild, "log_role_change")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🛡️ Role được tạo mới",
            description=f"Role {role.mention} (`{role.name}`) vừa được tạo",
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        log_channel = await self.get_log_channel(role.guild, "log_role_change")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🛡️ Role bị xóa",
            description=f"Role `{role.name}` đã bị xóa",
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 5. Custom Events (Automod & Ticket)
    @commands.Cog.listener()
    async def on_automod_action(self, guild: discord.Guild, user: discord.Member, action_type: str, reason: str, jump_url: str = None):
        log_channel = await self.get_log_channel(guild, "log_automod")
        if not log_channel: return
        
        embed = discord.Embed(
            title="⚠️ Vi phạm Automod",
            description=f"{user.mention} đã vi phạm Automod",
            color=COLOR_MOD,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if hasattr(user, 'display_avatar') else None)
        embed.add_field(name="Hành động", value=action_type, inline=True)
        embed.add_field(name="Lý do", value=reason, inline=True)
        if jump_url:
            embed.add_field(name="Tin nhắn gốc", value=f"[Link đến tin nhắn]({jump_url})", inline=False)
            
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_ticket_action(self, guild: discord.Guild, user: discord.Member, action_type: str, ticket_name: str):
        log_channel = await self.get_log_channel(guild, "log_ticket")
        if not log_channel: return
        
        embed = discord.Embed(
            title="🎫 Hoạt động Ticket",
            description=f"{user.mention if user else 'Hệ thống'} đã **{action_type}** ticket `{ticket_name}`",
            color=COLOR_INFO,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Logger(bot))

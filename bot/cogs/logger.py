import discord
from discord.ext import commands
import time
import datetime
import traceback
import config
from database import async_get_logger_settings, async_is_module_enabled, async_get_guild_settings
from i18n import tr

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
        
        s = await async_get_guild_settings(str(message.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.msg_del_title"),
            description=tr(s, "logger.msg_del_desc", user=message.author.mention, channel=message.channel.mention),
            color=COLOR_DELETE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        no_cnt = tr(s, "logger.no_content")
        embed.add_field(name=tr(s, "logger.content"), value=message.content[:1024] or no_cnt, inline=False)
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
        
        s = await async_get_guild_settings(str(before.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.msg_edit_title"),
            description=tr(s, "logger.msg_edit_desc", user=before.author.mention, channel=before.channel.mention, url=after.jump_url),
            color=COLOR_UPDATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        empty_txt = tr(s, "logger.empty")
        embed.add_field(name=tr(s, "logger.before"), value=before.content[:1024] or empty_txt, inline=False)
        embed.add_field(name=tr(s, "logger.after"), value=after.content[:1024] or empty_txt, inline=False)
        embed.set_author(name=f"{before.author.name} ({before.author.id})", icon_url=before.author.display_avatar.url)
        embed.set_footer(text=f"Message ID: {before.id}")
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 2. Member Events
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log_channel = await self.get_log_channel(member.guild, "log_member_join_leave")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(member.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.member_join_title"),
            description=tr(s, "logger.member_join_desc", user=member.mention),
            color=COLOR_JOIN,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name=tr(s, "logger.account_created"), value=f"<t:{int(member.created_at.timestamp())}:R>")
        embed.set_author(name=f"{member.name} ({member.id})", icon_url=member.display_avatar.url)
        embed.set_footer(text=tr(s, "logger.member_num_footer", cnt=member.guild.member_count))
        
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        log_channel = await self.get_log_channel(member.guild, "log_member_join_leave")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(member.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.member_leave_title"),
            description=tr(s, "logger.member_leave_desc", user=member.mention),
            color=COLOR_LEAVE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{member.name} ({member.id})", icon_url=member.display_avatar.url)
        
        # Check audit log for kick
        if member.guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        embed.title = tr(s, "logger.member_kick_title")
                        embed.description = tr(s, "logger.member_kick_desc", user=member.mention, by=entry.user.mention)
                        embed.add_field(name=tr(s, "automod.dm_reason"), value=entry.reason or tr(s, "automod.none"))
                        break
            except Exception:
                pass
                
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self.get_log_channel(guild, "log_member_kick_ban")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.ban_title"),
            description=tr(s, "logger.ban_desc", user=user.mention),
            color=COLOR_MOD,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if user.display_avatar else None)
        
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                    if entry.target.id == user.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        embed.description = tr(s, "logger.ban_by_desc", user=user.mention, by=entry.user.mention)
                        embed.add_field(name=tr(s, "automod.dm_reason"), value=entry.reason or tr(s, "automod.none"))
                        break
            except Exception:
                pass
                
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        log_channel = await self.get_log_channel(guild, "log_member_kick_ban")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.unban_title"),
            description=tr(s, "logger.unban_desc", user=user.mention),
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
            
        s = await async_get_guild_settings(str(before.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.role_change_title"),
            description=tr(s, "logger.role_change_desc", user=before.mention),
            color=COLOR_UPDATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{before.name} ({before.id})", icon_url=before.display_avatar.url)
        
        if added_roles:
            embed.add_field(name=tr(s, "logger.role_add"), value=" ".join([r.mention for r in added_roles]), inline=False)
        if removed_roles:
            embed.add_field(name=tr(s, "logger.role_remove"), value=" ".join([r.mention for r in removed_roles]), inline=False)
            
        try: await log_channel.send(embed=embed)
        except Exception: pass

    # 3. Channel Events
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        log_channel = await self.get_log_channel(channel.guild, "log_channel_change")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(channel.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.ch_create_title"),
            description=tr(s, "logger.ch_create_desc", ch=channel.mention, name=channel.name),
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        log_channel = await self.get_log_channel(channel.guild, "log_channel_change")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(channel.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.ch_del_title"),
            description=tr(s, "logger.ch_del_desc", name=channel.name),
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
        
        s = await async_get_guild_settings(str(role.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.role_create_title"),
            description=tr(s, "logger.role_create_desc", role=role.mention, name=role.name),
            color=COLOR_CREATE,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        log_channel = await self.get_log_channel(role.guild, "log_role_change")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(role.guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.role_del_title"),
            description=tr(s, "logger.role_del_desc", name=role.name),
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
        
        s = await async_get_guild_settings(str(guild.id))
        embed = discord.Embed(
            title=tr(s, "logger.automod_violation_title"),
            description=tr(s, "logger.automod_violation_desc", user=user.mention),
            color=COLOR_MOD,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if hasattr(user, 'display_avatar') else None)
        embed.add_field(name=tr(s, "logger.action"), value=action_type, inline=True)
        embed.add_field(name=tr(s, "automod.dm_reason"), value=reason, inline=True)
        if jump_url:
            embed.add_field(name=tr(s, "logger.orig_msg"), value=tr(s, "logger.msg_link", url=jump_url), inline=False)
            
        try: await log_channel.send(embed=embed)
        except Exception: pass

    @commands.Cog.listener()
    async def on_ticket_action(self, guild: discord.Guild, user: discord.Member, action_type: str, ticket_name: str):
        log_channel = await self.get_log_channel(guild, "log_ticket")
        if not log_channel: return
        
        s = await async_get_guild_settings(str(guild.id))
        user_str = user.mention if user else tr(s, "logger.ticket_system")
        embed = discord.Embed(
            title=tr(s, "logger.ticket_act_title"),
            description=tr(s, "logger.ticket_act_desc", user=user_str, action=action_type, name=ticket_name),
            color=COLOR_INFO,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        try: await log_channel.send(embed=embed)
        except Exception: pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Logger(bot))


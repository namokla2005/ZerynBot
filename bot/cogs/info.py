"""
Cog: Info (v2) — Prefix commands: serverinfo, userinfo, avatar
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import async_get_guild_settings
from i18n import tr


class Info(commands.Cog):
    """Thông tin server, user, avatar."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            return
        from database import async_is_module_enabled
        enabled = await async_is_module_enabled(str(ctx.guild.id), "info")
        if not enabled:
            s = await async_get_guild_settings(str(ctx.guild.id))
            await ctx.send(tr(s, "common.module_disabled", module="Info"))
            raise commands.CommandError("Module disabled")

    # ─── serverinfo ────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="serverinfo", description="Hiển thị thông tin chi tiết về server")
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        s = await async_get_guild_settings(str(guild.id))
        text_ch  = len(guild.text_channels)
        voice_ch = len(guild.voice_channels)
        cats     = len(guild.categories)
        total    = guild.member_count
        bots     = sum(1 for m in guild.members if m.bot)
        humans   = total - bots

        verif_map = {
            discord.VerificationLevel.none:    tr(s, "info.verify_none"),
            discord.VerificationLevel.low:     tr(s, "info.verify_low"),
            discord.VerificationLevel.medium:  tr(s, "info.verify_medium"),
            discord.VerificationLevel.high:    tr(s, "info.verify_high"),
            discord.VerificationLevel.highest: tr(s, "info.verify_highest"),
        }

        embed = discord.Embed(
            title=tr(s, "info.serverinfo_title", server=guild.name),
            description=guild.description or "",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.add_field(name=tr(s, "info.server_id_field"), value=f"`{guild.id}`",        inline=True)
        embed.add_field(name=tr(s, "info.owner_field"),      value=guild.owner.mention,    inline=True)
        embed.add_field(
            name=tr(s, "info.created_field"),
            value=f"<t:{int(guild.created_at.timestamp())}:D> (<t:{int(guild.created_at.timestamp())}:R>)",
            inline=False,
        )
        embed.add_field(name=tr(s, "info.total_field"),    value=f"**{total}**",  inline=True)
        embed.add_field(name=tr(s, "info.humans_field"),   value=f"**{humans}**", inline=True)
        embed.add_field(name=tr(s, "info.bots_field"),     value=f"**{bots}**",   inline=True)
        embed.add_field(name=tr(s, "info.text_field"),     value=f"**{text_ch}**",  inline=True)
        embed.add_field(name=tr(s, "info.voice_field"),    value=f"**{voice_ch}**", inline=True)
        embed.add_field(name=tr(s, "info.category_field"), value=f"**{cats}**",   inline=True)
        embed.add_field(name=tr(s, "info.roles_field"),    value=f"**{len(guild.roles)}**",   inline=True)
        embed.add_field(name=tr(s, "info.emoji_field"),    value=f"**{len(guild.emojis)}**",  inline=True)
        embed.add_field(
            name=tr(s, "info.boost_field"),
            value=f"Level **{guild.premium_tier}** — **{guild.premium_subscription_count or 0}** boosts",
            inline=True,
        )
        embed.add_field(name=tr(s, "info.verify_field"), value=verif_map.get(guild.verification_level, tr(s, "info.verify_unknown")), inline=True)
        embed.set_footer(
            text=tr(s, "info.requested_by_footer", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── userinfo ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="userinfo", description="Hiển thị thông tin chi tiết về người dùng")
    @commands.guild_only()
    @app_commands.describe(member="Người dùng cần xem thông tin (mặc định: bạn)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        s = await async_get_guild_settings(str(ctx.guild.id))

        flags = member.public_flags
        badges = []
        if flags.staff:                    badges.append("👮 Discord Staff")
        if flags.partner:                  badges.append("🤝 Partner")
        if flags.hypesquad:                badges.append("🏠 HypeSquad")
        if flags.bug_hunter:               badges.append("🐛 Bug Hunter")
        if flags.verified_bot_developer:   badges.append("🛠️ Verified Bot Dev")
        if flags.early_supporter:          badges.append("🌟 Early Supporter")

        roles = [r for r in reversed(member.roles) if r.name != "@everyone"]
        no_roles_txt = tr(s, "info.no_roles")
        if len(roles) > 10:
            roles_str = " ".join(r.mention for r in roles[:10]) + f" +{len(roles)-10}"
        else:
            roles_str = " ".join(r.mention for r in roles) if roles else no_roles_txt

        color = member.color if member.color != discord.Color.default() else config.COLOR_INFO
        status_map = {
            discord.Status.online:  tr(s, "info.status_online"),
            discord.Status.idle:    tr(s, "info.status_idle"),
            discord.Status.dnd:     tr(s, "info.status_dnd"),
            discord.Status.offline: tr(s, "info.status_offline"),
        }

        embed = discord.Embed(
            title=tr(s, "info.userinfo_title", user=member.display_name),
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name=tr(s, "info.username_field"),  value=f"`{member.name}`",  inline=True)
        embed.add_field(name=tr(s, "info.id_field"),        value=f"`{member.id}`",    inline=True)
        embed.add_field(name=tr(s, "info.bot_field"),       value="✅" if member.bot else "❌", inline=True)
        embed.add_field(
            name=tr(s, "info.account_created"),
            value=f"<t:{int(member.created_at.timestamp())}:D> (<t:{int(member.created_at.timestamp())}:R>)",
            inline=False,
        )
        embed.add_field(
            name=tr(s, "info.joined_server"),
            value=f"<t:{int(member.joined_at.timestamp())}:D> (<t:{int(member.joined_at.timestamp())}:R>)" if member.joined_at else "N/A",
            inline=False,
        )
        embed.add_field(name=tr(s, "info.status_field"),  value=status_map.get(member.status, "⚫"), inline=True)
        embed.add_field(name=tr(s, "info.badges_field"),  value=" • ".join(badges) if badges else tr(s, "info.no_badges"), inline=False)
        embed.add_field(name=f"{tr(s, 'info.roles_field')} ({len(roles)})", value=roles_str, inline=False)
        embed.set_footer(
            text=tr(s, "info.requested_by_footer", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── avatar ────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="avatar", description="Hiển thị avatar full-size của người dùng")
    @app_commands.describe(member="Người dùng cần xem avatar (mặc định: bạn)")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author

        formats = []
        for fmt in ("png", "jpg", "webp"):
            url = member.display_avatar.replace(format=fmt, size=1024).url
            formats.append(f"[{fmt.upper()}]({url})")
        if member.display_avatar.is_animated():
            formats.append(f"[GIF]({member.display_avatar.replace(format='gif', size=1024).url})")

        guild_id = str(ctx.guild.id) if ctx.guild else ""
        settings = await async_get_guild_settings(guild_id) if guild_id else {}

        embed = discord.Embed(
            title=tr(settings, "info.avatar_title", user=member.display_name),
            color=config.COLOR_AVATAR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_image(url=member.display_avatar.with_size(1024).url)
        embed.add_field(name=f"📥 {tr(settings, 'info.download')}", value=" • ".join(formats), inline=False)

        if member.guild_avatar and member.guild_avatar != member.avatar:
            embed.add_field(
                name="🌐 Avatar",
                value=f"[Link]({member.avatar.with_size(1024).url})",
                inline=True,
            )
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── botinfo ───────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="botinfo", description="Hiển thị thông số kỹ thuật và trạng thái của bot")
    async def botinfo(self, ctx: commands.Context):
        import platform
        guild_id = str(ctx.guild.id) if ctx.guild else ""
        s = await async_get_guild_settings(guild_id) if guild_id else {}

        embed = discord.Embed(
            title=tr(s, "info.botinfo_title"),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
        embed.add_field(name=tr(s, "info.python_field"),  value=f"`{platform.python_version()}`", inline=True)
        embed.add_field(name=tr(s, "info.os_field"),      value=f"`{platform.system()} {platform.release()}`", inline=True)
        embed.add_field(name=tr(s, "info.servers_field"), value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name=tr(s, "info.users_field"),   value=f"`{sum(g.member_count for g in self.bot.guilds)}`", inline=True)
        embed.add_field(name=tr(s, "info.ping_field"),    value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        
        await ctx.send(embed=embed)

    # ─── roleinfo ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="roleinfo", description="Hiển thị thông tin về một Role")
    @commands.guild_only()
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        s = await async_get_guild_settings(str(ctx.guild.id))
        embed = discord.Embed(
            title=tr(s, "info.roleinfo_title", role=role.name),
            color=role.color if role.color != discord.Color.default() else config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name=tr(s, "info.id_field"),             value=f"`{role.id}`", inline=True)
        embed.add_field(name=tr(s, "info.role_color_field"),     value=f"`{str(role.color)}`", inline=True)
        embed.add_field(name=tr(s, "info.role_members_field"),   value=f"**{len(role.members)}**", inline=True)
        embed.add_field(name=tr(s, "info.role_mentionable_field"), value="✅" if role.mentionable else "❌", inline=True)
        embed.add_field(name=tr(s, "info.role_hoist_field"),     value="✅" if role.hoist else "❌", inline=True)
        embed.add_field(name=tr(s, "info.created_field"),        value=f"<t:{int(role.created_at.timestamp())}:D>", inline=True)
        
        await ctx.send(embed=embed)

    # ─── channelinfo ───────────────────────────────────────────────────────────
    @commands.hybrid_command(name="channelinfo", description="Hiển thị thông tin về một Kênh")
    @commands.guild_only()
    async def channelinfo(self, ctx: commands.Context, channel: discord.abc.GuildChannel = None):
        channel = channel or ctx.channel
        s = await async_get_guild_settings(str(ctx.guild.id))
        embed = discord.Embed(
            title=tr(s, "info.channelinfo_title", channel=channel.name),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name=tr(s, "info.id_field"),               value=f"`{channel.id}`", inline=True)
        embed.add_field(name=tr(s, "info.channel_type_field"),     value=f"`{str(channel.type)}`", inline=True)
        
        if hasattr(channel, "category") and channel.category:
            embed.add_field(name=tr(s, "info.channel_category_field"), value=f"`{channel.category.name}`", inline=True)
            
        embed.add_field(name=tr(s, "info.created_field"), value=f"<t:{int(channel.created_at.timestamp())}:D>", inline=True)
        
        if isinstance(channel, discord.TextChannel):
            slow_txt = f"`{channel.slowmode_delay}s`" if channel.slowmode_delay else tr(s, "info.channel_no_slowmode")
            embed.add_field(name=tr(s, "info.channel_nsfw_field"),     value="✅" if channel.nsfw else "❌", inline=True)
            embed.add_field(name=tr(s, "info.channel_slowmode_field"), value=slow_txt, inline=True)
            
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))


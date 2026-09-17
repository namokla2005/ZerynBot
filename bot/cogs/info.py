"""
Cog: Info (v2) — Prefix & Slash commands: serverinfo, userinfo, avatar, botinfo, roleinfo, channelinfo
"""
import sys, os, time, platform
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import async_get_guild_settings
from i18n import tr
try:
    from emojis import e, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, clean_title


class Info(commands.Cog):
    """Thông tin server, user, avatar, bot, role, channel."""

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
        if not guild.chunked:
            try:
                await guild.chunk()
            except Exception:
                pass

        s = await async_get_guild_settings(str(guild.id))
        text_ch  = len(guild.text_channels)
        voice_ch = len(guild.voice_channels)
        stage_ch = len(guild.stage_channels)
        forum_ch = len(getattr(guild, "forum_channels", []))
        cats     = len(guild.categories)
        total    = guild.member_count or len(guild.members) or 1
        bots     = sum(1 for m in guild.members if m.bot)
        humans   = max(0, total - bots)

        verif_map = {
            discord.VerificationLevel.none:    tr(s, "info.verify_none"),
            discord.VerificationLevel.low:     tr(s, "info.verify_low"),
            discord.VerificationLevel.medium:  tr(s, "info.verify_medium"),
            discord.VerificationLevel.high:    tr(s, "info.verify_high"),
            discord.VerificationLevel.highest: tr(s, "info.verify_highest"),
        }

        owner_val = guild.owner.mention if guild.owner else f"<@{guild.owner_id}>"

        embed = discord.Embed(
            title=embed_title("zb_cat_info", tr(s, "info.serverinfo_title", server=guild.name)),
            description=guild.description or "",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.add_field(name=tr(s, "info.server_id_field"), value=f"`{guild.id}`", inline=True)
        embed.add_field(name=tr(s, "info.owner_field"),      value=owner_val,       inline=True)
        embed.add_field(name=tr(s, "info.verify_field"), value=f"{e('zb_verified')} " + verif_map.get(guild.verification_level, tr(s, "info.verify_unknown")), inline=True)
        embed.add_field(
            name=tr(s, "info.created_field"),
            value=f"<t:{int(guild.created_at.timestamp())}:D> (<t:{int(guild.created_at.timestamp())}:R>)",
            inline=False,
        )
        embed.add_field(name=tr(s, "info.total_field"),    value=f"**{total}**",  inline=True)
        embed.add_field(name=tr(s, "info.humans_field"),   value=f"**{humans}**", inline=True)
        embed.add_field(name=tr(s, "info.bots_field"),     value=f"**{bots}**",   inline=True)

        channels_detail = f"💬 Text: **{text_ch}** • 🔊 Voice: **{voice_ch}**"
        if stage_ch:
            channels_detail += f" • 🎭 Stage: **{stage_ch}**"
        if forum_ch:
            channels_detail += f" • 📑 Forum: **{forum_ch}**"
        channels_detail += f" • 📁 Categories: **{cats}**"

        embed.add_field(name=f"📺 Kênh ({len(guild.channels)})", value=channels_detail, inline=False)
        embed.add_field(name=tr(s, "info.roles_field"),    value=f"**{len(guild.roles)}**",   inline=True)
        embed.add_field(name=tr(s, "info.emoji_field"),    value=f"**{len(guild.emojis)}**",  inline=True)
        embed.add_field(
            name=tr(s, "info.boost_field"),
            value=f"Level **{guild.premium_tier}** — **{guild.premium_subscription_count or 0}** boosts",
            inline=True,
        )
        if guild.afk_channel:
            embed.add_field(name="💤 AFK Channel", value=f"{guild.afk_channel.mention} ({guild.afk_timeout // 60}m)", inline=True)

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

        if not ctx.guild.chunked:
            try:
                await ctx.guild.chunk()
            except Exception:
                pass

        flags = getattr(member, "public_flags", None)
        badges = []
        if flags:
            if getattr(flags, "staff", False):                  badges.append("👮 Discord Staff")
            if getattr(flags, "partner", False):                badges.append("🤝 Partner")
            if getattr(flags, "hypesquad", False):              badges.append("🏠 HypeSquad Events")
            if getattr(flags, "hypesquad_bravery", False):      badges.append("🟣 Bravery")
            if getattr(flags, "hypesquad_brilliance", False):   badges.append("🔴 Brilliance")
            if getattr(flags, "hypesquad_balance", False):      badges.append("🟢 Balance")
            if getattr(flags, "bug_hunter", False):             badges.append("🐛 Bug Hunter")
            if getattr(flags, "bug_hunter_level_2", False):     badges.append("🐛 Bug Hunter Gold")
            if getattr(flags, "verified_bot_developer", False) or getattr(flags, "early_verified_bot_developer", False): badges.append(f"{e('zb_verified')} Early Bot Dev")
            if getattr(flags, "active_developer", False):       badges.append("⚡ Active Developer")
            if getattr(flags, "early_supporter", False):        badges.append("🌟 Early Supporter")

        roles = [r for r in reversed(member.roles) if r.name != "@everyone"] if hasattr(member, "roles") else []
        no_roles_txt = tr(s, "info.no_roles")
        if len(roles) > 10:
            roles_str = " ".join(r.mention for r in roles[:10]) + f" +{len(roles)-10}"
        else:
            roles_str = " ".join(r.mention for r in roles) if roles else no_roles_txt

        color = member.color if hasattr(member, "color") and member.color != discord.Color.default() else config.COLOR_INFO
        status_map = {
            discord.Status.online:    tr(s, "info.status_online"),
            discord.Status.idle:      tr(s, "info.status_idle"),
            discord.Status.dnd:       tr(s, "info.status_dnd"),
            discord.Status.offline:   tr(s, "info.status_offline"),
            discord.Status.streaming: "🟣 Streaming",
        }

        # Calculate join position
        join_pos = "N/A"
        if member.joined_at and ctx.guild:
            sorted_members = sorted((m for m in ctx.guild.members if m.joined_at), key=lambda m: m.joined_at)
            try:
                pos = sorted_members.index(member) + 1
                join_pos = f"#{pos}"
            except ValueError:
                pass

        top_role = member.top_role.mention if getattr(member, "top_role", None) and member.top_role.name != "@everyone" else "N/A"

        embed = discord.Embed(
            title=embed_title("zb_cat_info", tr(s, "info.userinfo_title", user=member.display_name)),
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name=tr(s, "info.username_field"),  value=f"`{member.name}`",  inline=True)
        embed.add_field(name=tr(s, "info.id_field"),        value=f"`{member.id}`",    inline=True)
        embed.add_field(name=tr(s, "info.bot_field"),       value="🤖 BOT" if member.bot else "👤 User", inline=True)
        embed.add_field(
            name=tr(s, "info.account_created"),
            value=f"<t:{int(member.created_at.timestamp())}:D> (<t:{int(member.created_at.timestamp())}:R>)",
            inline=False,
        )
        joined_val = f"<t:{int(member.joined_at.timestamp())}:D> (<t:{int(member.joined_at.timestamp())}:R>)" if getattr(member, "joined_at", None) else "N/A"
        embed.add_field(
            name=tr(s, "info.joined_server"),
            value=joined_val,
            inline=True,
        )
        embed.add_field(name="📍 Thứ tự gia nhập", value=f"**{join_pos}**", inline=True)
        member_status = getattr(member, "status", discord.Status.offline)
        embed.add_field(name=tr(s, "info.status_field"), value=status_map.get(member_status, tr(s, "info.status_offline")), inline=True)
        embed.add_field(name="👑 Vai trò cao nhất", value=top_role, inline=True)
        embed.add_field(name=tr(s, "info.badges_field"), value=" • ".join(badges) if badges else tr(s, "info.no_badges"), inline=False)
        embed.add_field(name=f"{tr(s, 'info.roles_field')} ({len(roles)})", value=roles_str, inline=False)
        embed.set_footer(
            text=tr(s, "info.requested_by_footer", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── avatar ────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="avatar", description="Hiển thị avatar full-size của người dùng")
    @app_commands.describe(user="Người dùng cần xem avatar (mặc định: bạn)")
    async def avatar(self, ctx: commands.Context, user: discord.User = None):
        target = user or ctx.author
        guild_member = ctx.guild.get_member(target.id) if ctx.guild else None

        formats = []
        for fmt in ("png", "jpg", "webp"):
            url = target.display_avatar.replace(format=fmt, size=1024).url
            formats.append(f"[{fmt.upper()}]({url})")
        if target.display_avatar.is_animated():
            formats.append(f"[GIF]({target.display_avatar.replace(format='gif', size=1024).url})")

        guild_id = str(ctx.guild.id) if ctx.guild else ""
        settings = await async_get_guild_settings(guild_id) if guild_id else {}

        embed = discord.Embed(
            title=embed_title("zb_cat_info", tr(settings, "info.avatar_title", user=target.display_name)),
            color=config.COLOR_AVATAR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_image(url=target.display_avatar.with_size(1024).url)
        embed.add_field(name=f"📥 {tr(settings, 'info.download')}", value=" • ".join(formats), inline=False)

        # Hiển thị avatar global nếu đang dùng server avatar riêng biệt
        if guild_member and getattr(guild_member, "guild_avatar", None):
            global_avatar = target.avatar or target.default_avatar
            embed.add_field(
                name="🌐 Global Avatar",
                value=f"[Link]({global_avatar.with_size(1024).url})",
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
        guild_id = str(ctx.guild.id) if ctx.guild else ""
        s = await async_get_guild_settings(guild_id) if guild_id else {}

        embed = discord.Embed(
            title=embed_title("zb_cat_ai", tr(s, "info.botinfo_title")),
            description="**Zeryn Bot V2** — Multi-Purpose Discord Bot for Communities, Music & AI.",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Calculate uptime
        uptime_seconds = int(time.time() - getattr(self.bot, "start_time", time.time()))
        days, rem = divmod(uptime_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s" if days else f"{hours}h {minutes}m {seconds}s"

        # RAM telemetry
        ram_str = "N/A"
        try:
            import psutil
            process = psutil.Process()
            ram_mb = process.memory_info().rss / (1024 * 1024)
            ram_str = f"{ram_mb:.1f} MB"
        except Exception:
            pass

        total_users = sum(g.member_count or 0 for g in self.bot.guilds)
        embed.add_field(name=tr(s, "info.python_field"),  value=f"`{platform.python_version()}`", inline=True)
        embed.add_field(name="📚 Discord.py",            value=f"`v{discord.__version__}`", inline=True)
        embed.add_field(name=tr(s, "info.os_field"),      value=f"`{platform.system()} {platform.release()}`", inline=True)
        embed.add_field(name="⏱️ Uptime",                 value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="💾 RAM",                    value=f"`{ram_str}`", inline=True)
        embed.add_field(name=tr(s, "info.ping_field"),    value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name=tr(s, "info.servers_field"), value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name=tr(s, "info.users_field"),   value=f"`{total_users}`", inline=True)
        embed.add_field(name="🧩 Modules & Lệnh",         value="`20 Modules • 108 Lệnh`", inline=True)

        embed.add_field(
            name="🔗 Liên kết hữu ích",
            value="[🌐 Web Dashboard](https://zerynbot.id.vn) • [💬 Support Server](https://discord.gg/VPybhdNbXC) • [📖 Danh Sách Lệnh](https://zerynbot.id.vn/commands)",
            inline=False
        )

        embed.set_footer(
            text=tr(s, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── roleinfo ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="roleinfo", description="Hiển thị thông tin về một Role")
    @commands.guild_only()
    @app_commands.describe(role="Vai trò cần xem thông tin")
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        s = await async_get_guild_settings(str(ctx.guild.id))
        embed = discord.Embed(
            title=embed_title("zb_cat_roles", tr(s, "info.roleinfo_title", role=role.name)),
            color=role.color if role.color != discord.Color.default() else config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if getattr(role, "icon", None):
            embed.set_thumbnail(url=role.icon.url)

        embed.add_field(name=tr(s, "info.id_field"),             value=f"`{role.id}`", inline=True)
        embed.add_field(name=tr(s, "info.role_color_field"),     value=f"`{str(role.color)}`", inline=True)
        embed.add_field(name="📍 Vị trí (Position)",             value=f"**#{role.position}** / {len(ctx.guild.roles)}", inline=True)
        embed.add_field(name=tr(s, "info.role_members_field"),   value=f"**{len(role.members)}**", inline=True)
        embed.add_field(name=tr(s, "info.role_mentionable_field"), value="✅" if role.mentionable else "❌", inline=True)
        embed.add_field(name=tr(s, "info.role_hoist_field"),     value="✅" if role.hoist else "❌", inline=True)
        embed.add_field(name=tr(s, "info.created_field"),        value=f"<t:{int(role.created_at.timestamp())}:D>", inline=False)

        # Key permissions
        key_perms = []
        perms = role.permissions
        if perms.administrator:   key_perms.append("Administrator")
        if perms.manage_guild:    key_perms.append("Manage Server")
        if perms.manage_channels: key_perms.append("Manage Channels")
        if perms.manage_roles:    key_perms.append("Manage Roles")
        if perms.ban_members:     key_perms.append("Ban Members")
        if perms.kick_members:    key_perms.append("Kick Members")
        if perms.mention_everyone:key_perms.append("Mention Everyone")
        if perms.view_audit_log:  key_perms.append("View Audit Log")
        if perms.manage_messages: key_perms.append("Manage Messages")

        perms_str = " • ".join(key_perms) if key_perms else "None (Thành viên thông thường)"
        embed.add_field(name="🔒 Quyền hạn nổi bật", value=perms_str, inline=False)

        embed.set_footer(
            text=tr(s, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── channelinfo ───────────────────────────────────────────────────────────
    @commands.hybrid_command(name="channelinfo", description="Hiển thị thông tin về một Kênh")
    @commands.guild_only()
    @app_commands.describe(channel="Kênh cần xem thông tin (mặc định: kênh hiện tại)")
    async def channelinfo(self, ctx: commands.Context, channel: discord.abc.GuildChannel = None):
        channel = channel or ctx.channel
        s = await async_get_guild_settings(str(ctx.guild.id))
        embed = discord.Embed(
            title=embed_title("zb_cat_info", tr(s, "info.channelinfo_title", channel=channel.name)),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name=tr(s, "info.id_field"),               value=f"`{channel.id}`", inline=True)
        embed.add_field(name=tr(s, "info.channel_type_field"),     value=f"`{str(channel.type)}`", inline=True)
        embed.add_field(name="📍 Vị trí",                          value=f"**#{channel.position + 1}**", inline=True)

        if hasattr(channel, "category") and channel.category:
            embed.add_field(name=tr(s, "info.channel_category_field"), value=f"`{channel.category.name}`", inline=True)

        embed.add_field(name=tr(s, "info.created_field"), value=f"<t:{int(channel.created_at.timestamp())}:D>", inline=True)

        if hasattr(channel, "topic") and channel.topic:
            embed.add_field(name="📝 Chủ đề (Topic)", value=channel.topic[:1024], inline=False)

        if isinstance(channel, discord.TextChannel):
            slow_txt = f"`{channel.slowmode_delay}s`" if channel.slowmode_delay else tr(s, "info.channel_no_slowmode")
            embed.add_field(name=tr(s, "info.channel_nsfw_field"),     value="✅" if channel.nsfw else "❌", inline=True)
            embed.add_field(name=tr(s, "info.channel_slowmode_field"), value=slow_txt, inline=True)
        elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            bitrate_kbps = getattr(channel, "bitrate", 64000) // 1000
            user_limit = getattr(channel, "user_limit", 0)
            embed.add_field(name="Bitrate", value=f"`{bitrate_kbps} kbps`", inline=True)
            embed.add_field(name="User Limit", value=f"`{user_limit if user_limit > 0 else '∞'}`", inline=True)

        embed.set_footer(
            text=tr(s, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))


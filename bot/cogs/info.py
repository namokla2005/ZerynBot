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
            await ctx.send("❌ Module **Info** đã bị tắt trong server này!")
            raise commands.CommandError("Module disabled")

    # ─── serverinfo ────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="serverinfo", description="Hiển thị thông tin chi tiết về server")
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        text_ch  = len(guild.text_channels)
        voice_ch = len(guild.voice_channels)
        cats     = len(guild.categories)
        total    = guild.member_count
        bots     = sum(1 for m in guild.members if m.bot)
        humans   = total - bots

        verif_map = {
            discord.VerificationLevel.none:    "Không có",
            discord.VerificationLevel.low:     "Thấp (Email xác nhận)",
            discord.VerificationLevel.medium:  "Trung bình (5 phút)",
            discord.VerificationLevel.high:    "Cao (10 phút)",
            discord.VerificationLevel.highest: "Rất cao (Số điện thoại)",
        }

        embed = discord.Embed(
            title=f"🏠 {guild.name}",
            description=guild.description or "",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.add_field(name="🪪 Server ID",       value=f"`{guild.id}`",        inline=True)
        embed.add_field(name="👑 Chủ sở hữu",      value=guild.owner.mention,    inline=True)
        embed.add_field(
            name="📅 Ngày tạo",
            value=f"<t:{int(guild.created_at.timestamp())}:D> (<t:{int(guild.created_at.timestamp())}:R>)",
            inline=False,
        )
        embed.add_field(name="👥 Tổng",   value=f"**{total}**",  inline=True)
        embed.add_field(name="👤 Người",  value=f"**{humans}**", inline=True)
        embed.add_field(name="🤖 Bot",    value=f"**{bots}**",   inline=True)
        embed.add_field(name="💬 Text",   value=f"**{text_ch}**",  inline=True)
        embed.add_field(name="🔊 Voice",  value=f"**{voice_ch}**", inline=True)
        embed.add_field(name="📁 Category", value=f"**{cats}**",   inline=True)
        embed.add_field(name="🏅 Roles",  value=f"**{len(guild.roles)}**",   inline=True)
        embed.add_field(name="😀 Emoji",  value=f"**{len(guild.emojis)}**",  inline=True)
        embed.add_field(
            name="🚀 Nitro Boost",
            value=f"Level **{guild.premium_tier}** — **{guild.premium_subscription_count or 0}** boosts",
            inline=True,
        )
        embed.add_field(name="🛡️ Xác minh", value=verif_map.get(guild.verification_level, "Không rõ"), inline=True)
        embed.set_footer(
            text=f"Yêu cầu bởi {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── userinfo ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="userinfo", description="Hiển thị thông tin chi tiết về người dùng")
    @commands.guild_only()
    @app_commands.describe(member="Người dùng cần xem thông tin (mặc định: bạn)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author

        flags = member.public_flags
        badges = []
        if flags.staff:                    badges.append("👮 Discord Staff")
        if flags.partner:                  badges.append("🤝 Partner")
        if flags.hypesquad:                badges.append("🏠 HypeSquad")
        if flags.bug_hunter:               badges.append("🐛 Bug Hunter")
        if flags.verified_bot_developer:   badges.append("🛠️ Verified Bot Dev")
        if flags.early_supporter:          badges.append("🌟 Early Supporter")

        roles = [r for r in reversed(member.roles) if r.name != "@everyone"]
        if len(roles) > 10:
            roles_str = " ".join(r.mention for r in roles[:10]) + f" +{len(roles)-10}"
        else:
            roles_str = " ".join(r.mention for r in roles) if roles else "Không có"

        color = member.color if member.color != discord.Color.default() else config.COLOR_INFO
        status_map = {
            discord.Status.online:  "🟢 Online",
            discord.Status.idle:    "🌙 Idle",
            discord.Status.dnd:     "🔴 Do Not Disturb",
            discord.Status.offline: "⚫ Offline",
        }

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🏷️ Username",    value=f"`{member.name}`",  inline=True)
        embed.add_field(name="🪪 ID",          value=f"`{member.id}`",    inline=True)
        embed.add_field(name="🤖 Bot",         value="✅" if member.bot else "❌", inline=True)
        embed.add_field(
            name="📅 Tạo tài khoản",
            value=f"<t:{int(member.created_at.timestamp())}:D> (<t:{int(member.created_at.timestamp())}:R>)",
            inline=False,
        )
        embed.add_field(
            name="📥 Gia nhập server",
            value=f"<t:{int(member.joined_at.timestamp())}:D> (<t:{int(member.joined_at.timestamp())}:R>)" if member.joined_at else "N/A",
            inline=False,
        )
        embed.add_field(name="🎮 Trạng thái",  value=status_map.get(member.status, "⚫"), inline=True)
        embed.add_field(name="🎖️ Huy hiệu",    value=" • ".join(badges) if badges else "Không có", inline=False)
        embed.add_field(name=f"🏅 Roles ({len(roles)})", value=roles_str, inline=False)
        embed.set_footer(
            text=f"Yêu cầu bởi {ctx.author.display_name}",
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

        embed = discord.Embed(
            title=f"🖼️ Avatar của {member.display_name}",
            color=config.COLOR_AVATAR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_image(url=member.display_avatar.with_size(1024).url)
        embed.add_field(name="📥 Tải xuống", value=" • ".join(formats), inline=False)

        if member.guild_avatar and member.guild_avatar != member.avatar:
            embed.add_field(
                name="🌐 Avatar toàn cục",
                value=f"[Xem]({member.avatar.with_size(1024).url})",
                inline=True,
            )
        embed.set_footer(
            text=f"Yêu cầu bởi {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── botinfo ───────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="botinfo", description="Hiển thị thông số kỹ thuật và trạng thái của bot")
    async def botinfo(self, ctx: commands.Context):
        import platform
        import psutil
        
        process = psutil.Process()
        memory_usage = process.memory_info().rss / 1024 ** 2
        cpu_usage = psutil.cpu_percent()
        
        embed = discord.Embed(
            title="🤖 Thông tin Bot",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
        embed.add_field(name="⚙️ CPU", value=f"`{cpu_usage}%`", inline=True)
        embed.add_field(name="🗄️ RAM", value=f"`{memory_usage:.2f} MB`", inline=True)
        embed.add_field(name="🐍 Python", value=f"`{platform.python_version()}`", inline=True)
        embed.add_field(name="🏰 Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="👥 Users", value=f"`{sum(g.member_count for g in self.bot.guilds)}`", inline=True)
        embed.add_field(name="🏓 Ping", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        
        await ctx.send(embed=embed)

    # ─── roleinfo ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="roleinfo", description="Hiển thị thông tin về một Role")
    @commands.guild_only()
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        embed = discord.Embed(
            title=f"🎭 Thông tin Role: {role.name}",
            color=role.color if role.color != discord.Color.default() else config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="🪪 ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="🎨 Màu hex", value=f"`{str(role.color)}`", inline=True)
        embed.add_field(name="👥 Số người có", value=f"**{len(role.members)}**", inline=True)
        embed.add_field(name="📌 Có thể tag", value="✅" if role.mentionable else "❌", inline=True)
        embed.add_field(name="👁️ Hiển thị riêng", value="✅" if role.hoist else "❌", inline=True)
        embed.add_field(name="📅 Ngày tạo", value=f"<t:{int(role.created_at.timestamp())}:D>", inline=True)
        
        await ctx.send(embed=embed)

    # ─── channelinfo ───────────────────────────────────────────────────────────
    @commands.hybrid_command(name="channelinfo", description="Hiển thị thông tin về một Kênh")
    @commands.guild_only()
    async def channelinfo(self, ctx: commands.Context, channel: discord.abc.GuildChannel = None):
        channel = channel or ctx.channel
        embed = discord.Embed(
            title=f"📺 Thông tin Kênh: {channel.name}",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="🪪 ID", value=f"`{channel.id}`", inline=True)
        embed.add_field(name="📂 Thể loại", value=f"`{str(channel.type)}`", inline=True)
        
        if hasattr(channel, "category") and channel.category:
            embed.add_field(name="📁 Category", value=f"`{channel.category.name}`", inline=True)
            
        embed.add_field(name="📅 Ngày tạo", value=f"<t:{int(channel.created_at.timestamp())}:D>", inline=True)
        
        if isinstance(channel, discord.TextChannel):
            embed.add_field(name="🔞 NSFW", value="✅" if channel.nsfw else "❌", inline=True)
            embed.add_field(name="⏱️ Slowmode", value=f"`{channel.slowmode_delay}s`" if channel.slowmode_delay else "`Không có`", inline=True)
            
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))

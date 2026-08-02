"""
Cog: Utility (v2) — Prefix commands: ping, membercount, help
"""
import sys, os, time, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import async_get_guild_settings
from i18n import tr
class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, settings: dict):
        self.bot = bot
        self.ctx = ctx
        self.settings = settings
        options = [
            discord.SelectOption(label=tr(settings, "help.home_label"), description=tr(settings, "help.home_desc"), emoji="🏠", value="home"),
            discord.SelectOption(label=tr(settings, "help.utility_label"), description=tr(settings, "help.utility_desc"), emoji="⚙️", value="utility"),
            discord.SelectOption(label=tr(settings, "help.info_label"), description=tr(settings, "help.info_desc"), emoji="ℹ️", value="info"),
            discord.SelectOption(label=tr(settings, "help.music_label"), description=tr(settings, "help.music_desc"), emoji="🎵", value="music"),
            discord.SelectOption(label=tr(settings, "help.admin_label"), description=tr(settings, "help.admin_desc"), emoji="🛠️", value="admin")
        ]
        super().__init__(placeholder=tr(settings, "help.placeholder"), min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)
        
        embed = discord.Embed(color=config.COLOR_INFO, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=tr(self.settings, "common.requested_by", user=self.ctx.author.display_name), icon_url=self.ctx.author.display_avatar.url)
        
        val = self.values[0]
        if val == "home":
            embed.title = tr(self.settings, "help.home_title")
            embed.description = tr(self.settings, "help.description")
            if self.bot.user.display_avatar:
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.add_field(name=tr(self.settings, "help.guide_name"), value=tr(self.settings, "help.guide_value"), inline=False)
        elif val == "utility":
            embed.title = tr(self.settings, "help.utility_title")
            embed.description = (
                "`/ping` — Kiểm tra độ trễ kết nối của bot\n"
                "`/membercount` — Thống kê số lượng thành viên và bot trong server\n"
                "`/help` — Danh sách tất cả các lệnh của bot\n"
                "`/poll [câu hỏi]` — Tạo một cuộc bình chọn nhanh\n"
                "`/roll [số]` — Tung xúc xắc (mặc định 1-100)\n"
                "`/choose [opt1, opt2]` — Bot sẽ chọn ngẫu nhiên giúp bạn"
            )
        elif val == "info":
            embed.title = tr(self.settings, "help.info_title")
            embed.description = (
                "`/serverinfo` — Hiển thị thông tin chi tiết về server\n"
                "`/userinfo [@user]` — Hiển thị thông tin chi tiết về người dùng\n"
                "`/avatar [@user]` — Hiển thị avatar full-size của người dùng\n"
                "`/botinfo` — Hiển thị thông số kỹ thuật của bot\n"
                "`/roleinfo [@role]` — Hiển thị thông tin về một Role\n"
                "`/channelinfo [#channel]` — Hiển thị thông tin về một Kênh"
            )
        elif val == "music":
            embed.title = tr(self.settings, "help.music_title")
            embed.description = (
                "`/join` — Bot vào kênh voice của bạn\n"
                "`/leave` — Bot rời kênh voice và xóa hàng chờ\n"
                "`/play [tên/link]` — Phát nhạc từ YouTube (tên bài hoặc link)\n"
                "`/search [tên]` — Tìm kiếm nhạc và chọn từ 5 kết quả\n"
                "`/stop` — Dừng nhạc và xóa toàn bộ hàng chờ\n"
                "`/resume` — Tiếp tục phát nhạc đang tạm dừng\n"
                "`/loop` — Bật/tắt chế độ lặp lại bài hiện tại\n"
                "`/autoplay` — Bật/tắt tự động phát bài tiếp theo\n"
                "`/replay` — Phát lại bài hát hiện tại từ đầu\n"
                "`/lofi` — Phát kênh Lofi Girl 24/7\n"
                "`/playlist name [tên]` — Tạo một playlist mới\n"
                "`/playlist show [tên]` — Hiển thị danh sách nhạc trong playlist\n"
                "`/playlist add [tên] [bài]` — Thêm bài hát vào playlist\n"
                "`/playlist play [tên]` — Phát toàn bộ bài hát trong playlist\n"
                "`/playlist remove [tên]` — Xóa playlist của bạn\n"
                "`/playlist removesong [tên]` — Xóa một bài hát khỏi playlist"
            )
        elif val == "admin":
            embed.title = tr(self.settings, "help.admin_title")
            embed.description = (
                "`config` — Xem cấu hình hiện tại của server và link dashboard (Dùng text hoặc tag bot)\n"
                "`/reactionroles` — Link cấu hình Reaction Roles trên Dashboard\n"
                "`/ticket` — Link cấu hình Ticket System trên Dashboard\n"
                "`/autorole show` — Xem cấu hình Auto Roles hiện tại\n"
                "`/automods show` — Xem cấu hình Automods hiện tại\n"
                "`/giveaway start/end/reroll` — Quản lý Giveaway"
            )

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, settings: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.settings = settings
        self.message = None
        self.add_item(HelpSelect(bot, ctx, settings))
        
        self.add_item(discord.ui.Button(label="Join Support Server", style=discord.ButtonStyle.link, url="https://discord.gg/VPybhdNbXC", emoji="💬"))
        self.add_item(discord.ui.Button(label="View Dashboard", style=discord.ButtonStyle.link, url="https://zerynbot.id.vn", emoji="🌐"))
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

class Utility(commands.Cog):
    """Lệnh tiện ích."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            return
        from database import async_is_module_enabled
        enabled = await async_is_module_enabled(str(ctx.guild.id), "utility")
        if not enabled:
            s = await async_get_guild_settings(str(ctx.guild.id))
            await ctx.send(tr(s, "common.module_disabled", module="Utility"))
            raise commands.CommandError("Module disabled")

    # ─── ping ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="ping", description="Kiểm tra độ trễ kết nối của bot")
    async def ping(self, ctx: commands.Context):
        ws = round(self.bot.latency * 1000)

        t0 = time.perf_counter()
        await ctx.defer()
        t1 = time.perf_counter()
        api = round((t1 - t0) * 1000)

        guild_id = str(ctx.guild.id) if ctx.guild else ""
        settings = await async_get_guild_settings(guild_id) if guild_id else {}

        if ws < 80:
            quality = tr(settings, "utility.quality_excellent")
        elif ws < 150:
            quality = tr(settings, "utility.quality_good")
        elif ws < 300:
            quality = tr(settings, "utility.quality_medium")
        else:
            quality = tr(settings, "utility.quality_poor")

        embed = discord.Embed(
            title=tr(settings, "utility.ping_title"),
            color=config.COLOR_PING,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name=f"🌐 {tr(settings, 'utility.ping_ws')}", value=f"**{ws}** ms", inline=True)
        embed.add_field(name=f"📡 {tr(settings, 'utility.ping_api')}", value=f"**{api}** ms", inline=True)
        embed.add_field(name=f"📊 {tr(settings, 'utility.ping_quality')}", value=quality, inline=True)
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.reply(embed=embed)

    # ─── membercount ───────────────────────────────────────────────────────────
    @commands.hybrid_command(name="membercount", description="Thống kê số lượng thành viên và bot trong server")
    @commands.guild_only()
    async def membercount(self, ctx: commands.Context):
        guild  = ctx.guild
        total  = guild.member_count or len(guild.members)

        bots = online = idle = dnd = offline = 0
        for m in guild.members:
            if m.bot:
                bots += 1
            if m.status == discord.Status.online:
                online += 1
            elif m.status == discord.Status.idle:
                idle += 1
            elif m.status == discord.Status.dnd:
                dnd += 1
            else:
                offline += 1

        humans = total - bots
        human_pct = round(humans / total * 100, 1) if total else 0
        bot_pct   = round(bots   / total * 100, 1) if total else 0

        bar_len   = 20
        filled    = round(human_pct / 100 * bar_len)
        progress  = f"`{'█' * filled}{'░' * (bar_len - filled)}` {human_pct}%"

        settings = await async_get_guild_settings(str(guild.id))

        embed = discord.Embed(
            title=tr(settings, "utility.membercount_title", server=guild.name),
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name=f"📊 {tr(settings, 'utility.membercount_total')}",  value=f"**{total}**", inline=True)
        embed.add_field(name=f"👤 {tr(settings, 'utility.membercount_humans')}", value=f"**{humans}** ({human_pct}%)", inline=True)
        embed.add_field(name=f"🤖 {tr(settings, 'utility.membercount_bots')}",   value=f"**{bots}** ({bot_pct}%)", inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_ratio')}", value=progress, inline=False)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_online')}", value=f"**{online}**",  inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_idle')}",   value=f"**{idle}**",    inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_dnd')}",    value=f"**{dnd}**",     inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_offline')}", value=f"**{offline}**", inline=True)
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── help ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="help", description="Danh sách tất cả các lệnh của bot")
    async def help_cmd(self, ctx: commands.Context):
        settings = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        embed = discord.Embed(
            title=tr(settings, "help.title"),
            description=tr(settings, "help.description"),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name=tr(settings, "help.guide_name"),
            value=tr(settings, "help.guide_value"),
            inline=False,
        )
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )

        view = HelpView(self.bot, ctx, settings)
        view.message = await ctx.send(embed=embed, view=view)

    # ─── poll ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="poll", description="Tạo một cuộc bình chọn nhanh")
    @discord.app_commands.describe(question="Câu hỏi bình chọn")
    async def poll(self, ctx: commands.Context, *, question: str):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        embed = discord.Embed(
            title=tr(s, "utility.poll_title"),
            description=tr(s, "utility.poll_desc", question=question),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "utility.poll_created_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await msg.add_reaction("🤷")

    # ─── roll ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="roll", description="Tung xúc xắc (ngẫu nhiên từ 1 đến số chỉ định)")
    @discord.app_commands.describe(max_number="Số lớn nhất (mặc định là 100)")
    async def roll(self, ctx: commands.Context, max_number: int = 100):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        if max_number <= 1:
            await ctx.send(tr(s, "utility.roll_min_err"))
            return
        result = random.randint(1, max_number)
        embed = discord.Embed(
            title=tr(s, "utility.roll_title"),
            description=tr(s, "utility.roll_result", res=result, max=max_number),
            color=0xFEE75C
        )
        await ctx.send(embed=embed)

    # ─── choose ────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="choose", description="Bot sẽ chọn ngẫu nhiên giúp bạn một phương án")
    @discord.app_commands.describe(options="Các phương án cách nhau bởi dấu phẩy (VD: Ăn cơm, Ăn phở, Nhịn)")
    async def choose(self, ctx: commands.Context, *, options: str):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        opts = [o.strip() for o in options.split(",") if o.strip()]
        if len(opts) < 2:
            await ctx.send(tr(s, "utility.choose_min_err"))
            return
        result = random.choice(opts)
        embed = discord.Embed(
            title=tr(s, "utility.choose_title"),
            description=tr(s, "utility.choose_result", opts=", ".join(opts), res=result),
            color=config.COLOR_INFO
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))


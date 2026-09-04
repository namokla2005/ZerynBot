"""
giveaway.py — Giveaway System for ZerynBot V2 (Essential Bot Aesthetic).
Features:
- Premium Dark Slate Banner Graphics.
- Clean structured key-value markdown layout.
- Blurple interactive 'Enter Giveaway' button with real-time entry counter.
- Optional required role restriction.
- Automatic roll task with celebratory announcements and jump URL links.
"""
import sys, os, time, json, random, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands, tasks
from discord import app_commands
import config

from database import (
    async_is_module_enabled,
    async_create_giveaway,
    async_get_giveaway,
    async_update_giveaway,
    async_get_active_giveaways,
    async_get_guild_settings
)
from i18n import tr
try:
    from emojis import e, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, clean_title

BANNER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "giveaway_banner.png")


def parse_duration(duration_str: str) -> int:
    """Parse a string like '10m', '1h', '2d' into seconds."""
    match = re.match(r"^(\d+)([smhd])$", duration_str.lower().strip())
    if not match:
        return 0
    val, unit = match.groups()
    val = int(val)
    if unit == 's': return val
    if unit == 'm': return val * 60
    if unit == 'h': return val * 3600
    if unit == 'd': return val * 86400
    return 0


def _build_giveaway_embed(
    prize: str,
    winners: int,
    host_id: str,
    end_time: int,
    participants_count: int,
    req_role_id: str = None,
    settings: dict = None,
    is_ended: bool = False,
    winners_mentions: str = None
) -> discord.Embed:
    """Tạo Embed Giveaway chuẩn phong cách Essential Bot với khoảng cách dòng thoáng đãng."""
    s = settings or {}
    host_mention = f"<@{host_id}>" if host_id else "—"

    if not is_ended:
        color = 0x5865F2  # Blurple
        title = f"{e('zb_cat_giveaway')} Giveaway: {prize}"

        top_lines = [
            f"**{tr(s, 'giveaway.prize')}:** {prize}",
            f"**{tr(s, 'giveaway.winners_cnt')}:** {winners}",
            f"**{tr(s, 'giveaway.hosted_by')}:** {host_mention}",
        ]
        if req_role_id:
            top_lines.append(f"**{tr(s, 'giveaway.req_role')}:** <@&{req_role_id}>")

        bottom_lines = [
            f"**{tr(s, 'giveaway.entries')}:** {participants_count}",
            f"**{tr(s, 'giveaway.ends_label')}:** <t:{end_time}:R> (<t:{end_time}:F>)",
        ]

        embed = discord.Embed(
            title=title,
            description="\n".join(top_lines) + "\n\n" + "\n".join(bottom_lines),
            color=color
        )
    else:
        color = 0x2B2D31  # Dark Slate
        title = embed_title("zb_cat_giveaway", tr(s, "giveaway.ended_title", prize=prize))

        w_text = winners_mentions if winners_mentions else tr(s, "giveaway.no_winners")
        top_lines = [
            f"**{tr(s, 'giveaway.prize')}:** {prize}",
            f"**{tr(s, 'giveaway.winners_label')}:** {w_text}",
            f"**{tr(s, 'giveaway.hosted_by')}:** {host_mention}",
        ]
        bottom_lines = [
            f"**{tr(s, 'giveaway.total_entries')}:** {participants_count}",
            f"**{tr(s, 'giveaway.ended_at_label')}:** <t:{end_time}:F>",
        ]

        embed = discord.Embed(
            title=title,
            description="\n".join(top_lines) + "\n\n" + "\n".join(bottom_lines),
            color=color
        )

    if os.path.isfile(BANNER_PATH):
        embed.set_image(url="attachment://giveaway_banner.png")

    return embed


class DynamicJoinView(discord.ui.View):
    def __init__(self, label: str = "🎉 Tham gia Giveaway"):
        super().__init__(timeout=None)
        self.join_btn.label = label

    @discord.ui.button(label="🎉 Tham gia Giveaway", style=discord.ButtonStyle.primary, custom_id="gw_join_btn")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = str(interaction.message.id)
        gw = await async_get_giveaway(msg_id)
        g_settings = await async_get_guild_settings(str(interaction.guild.id)) if interaction.guild else {}

        if not gw or gw["ended"] == 1:
            return await interaction.response.send_message(tr(g_settings, "giveaway.already_ended"), ephemeral=True)

        # Check required role if set
        req_role_id = gw.get("req_role_id")
        if req_role_id and interaction.guild:
            role = interaction.guild.get_role(int(req_role_id))
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(
                    tr(g_settings, "giveaway.role_missing", role=role.mention),
                    ephemeral=True
                )

        participants = json.loads(gw["participants_json"])
        user_id_str = str(interaction.user.id)

        if user_id_str in participants:
            participants.remove(user_id_str)
            await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
            resp_text = tr(g_settings, "giveaway.leave_msg")
        else:
            participants.append(user_id_str)
            await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
            resp_text = tr(g_settings, "giveaway.join_msg")

        # Re-render updated embed
        new_embed = _build_giveaway_embed(
            prize=gw["prize"],
            winners=gw["winners_count"],
            host_id=gw["host_id"],
            end_time=gw["end_at"],
            participants_count=len(participants),
            req_role_id=req_role_id,
            settings=g_settings
        )

        try:
            await interaction.message.edit(embed=new_embed)
        except Exception:
            pass

        await interaction.response.send_message(resp_text, ephemeral=True)


class DisabledJoinView(discord.ui.View):
    def __init__(self, label: str = "🎉 Đã kết thúc"):
        super().__init__(timeout=None)
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id="gw_join_btn_ended", disabled=True)
        self.add_item(btn)


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaway_loop.start()

    def cog_unload(self):
        self.giveaway_loop.cancel()

    @commands.hybrid_group(name="giveaway", description="Quản lý Giveaway trên máy chủ")
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            s = await async_get_guild_settings(str(ctx.guild.id))
            await ctx.send(tr(s, "giveaway.usage"))

    @giveaway.command(name="start", description="Tạo một Giveaway mới với giao diện chuyên nghiệp")
    @app_commands.describe(
        duration="Thời gian (ví dụ: 10m, 1h, 1d)",
        winners="Số người trúng thưởng (mặc định: 1)",
        prize="Tên phần thưởng",
        role="Vai trò yêu cầu để tham gia (tùy chọn)"
    )
    async def g_start(self, ctx: commands.Context, duration: str, winners: int, prize: str, role: discord.Role = None):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)
        if not await async_is_module_enabled(guild_id, "giveaways"):
            return await ctx.send(tr(s, "giveaway.disabled"), ephemeral=True)

        seconds = parse_duration(duration)
        if seconds <= 0:
            return await ctx.send(tr(s, "giveaway.invalid_duration"), ephemeral=True)

        if winners < 1:
            return await ctx.send(tr(s, "giveaway.min_winners"), ephemeral=True)

        end_time = int(time.time() + seconds)
        req_role_id = str(role.id) if role else None

        embed = _build_giveaway_embed(
            prize=prize,
            winners=winners,
            host_id=str(ctx.author.id),
            end_time=end_time,
            participants_count=0,
            req_role_id=req_role_id,
            settings=s
        )

        btn_label = tr(s, "giveaway.btn_enter") if tr(s, "giveaway.btn_enter") != "giveaway.btn_enter" else "🎉 Tham gia Giveaway"
        view = DynamicJoinView(label=btn_label)

        file = None
        if os.path.isfile(BANNER_PATH):
            file = discord.File(BANNER_PATH, filename="giveaway_banner.png")

        if file:
            msg = await ctx.send(embed=embed, view=view, file=file)
        else:
            msg = await ctx.send(embed=embed, view=view)

        # Lưu thông tin vào Database
        await async_create_giveaway(
            guild_id=guild_id,
            channel_id=str(ctx.channel.id),
            message_id=str(msg.id),
            host_id=str(ctx.author.id),
            prize=prize,
            winners_count=winners,
            end_at=end_time,
            req_role_id=req_role_id
        )

    @giveaway.command(name="end", description="Kết thúc sớm một Giveaway")
    @app_commands.describe(message_id="ID của tin nhắn Giveaway")
    async def g_end(self, ctx: commands.Context, message_id: str):
        s = await async_get_guild_settings(str(ctx.guild.id))
        gw = await async_get_giveaway(message_id)
        if not gw or gw["guild_id"] != str(ctx.guild.id):
            return await ctx.send(tr(s, "giveaway.not_found"))
        if gw["ended"] == 1:
            return await ctx.send(tr(s, "giveaway.ended_already"))

        await async_update_giveaway(message_id, ended=1)
        await ctx.send(tr(s, "giveaway.ending_process"))
        await self.roll_giveaway(gw)

    @giveaway.command(name="reroll", description="Chọn lại người thắng mới cho Giveaway đã kết thúc")
    @app_commands.describe(message_id="ID của tin nhắn Giveaway")
    async def g_reroll(self, ctx: commands.Context, message_id: str):
        s = await async_get_guild_settings(str(ctx.guild.id))
        gw = await async_get_giveaway(message_id)
        if not gw or gw["guild_id"] != str(ctx.guild.id):
            return await ctx.send(tr(s, "giveaway.not_found"))
        if gw["ended"] == 0:
            return await ctx.send(tr(s, "giveaway.not_ended_yet"))

        participants = json.loads(gw["participants_json"])
        if len(participants) == 0:
            return await ctx.send(tr(s, "giveaway.no_part_reroll"))

        winner_id = random.choice(participants)

        channel = ctx.guild.get_channel(int(gw["channel_id"]))
        if channel:
            msg_link = f"https://discord.com/channels/{ctx.guild.id}/{gw['channel_id']}/{message_id}"
            await channel.send(f"{tr(s, 'giveaway.reroll_msg', user=f'<@{winner_id}>', prize=gw['prize'])}\n👉 [Xem tin nhắn]({msg_link})")
            await ctx.send(tr(s, "giveaway.reroll_success"))
        else:
            await ctx.send(tr(s, "giveaway.channel_not_found"))

    async def roll_giveaway(self, gw: dict):
        channel = self.bot.get_channel(int(gw["channel_id"]))
        if not channel:
            return

        try:
            msg = await channel.fetch_message(int(gw["message_id"]))
        except (discord.NotFound, discord.HTTPException):
            return

        s = await async_get_guild_settings(gw["guild_id"])
        participants = json.loads(gw["participants_json"])
        winners_count = gw["winners_count"]

        if len(participants) <= winners_count:
            winners = participants
        else:
            winners = random.sample(participants, winners_count)

        winners_mentions = ", ".join([f"<@{w}>" for w in winners]) if winners else None

        embed = _build_giveaway_embed(
            prize=gw["prize"],
            winners=gw["winners_count"],
            host_id=gw["host_id"],
            end_time=gw["end_at"],
            participants_count=len(participants),
            req_role_id=gw.get("req_role_id"),
            settings=s,
            is_ended=True,
            winners_mentions=winners_mentions
        )

        ended_label = tr(s, "giveaway.btn_ended") if tr(s, "giveaway.btn_ended") != "giveaway.btn_ended" else "🎉 Đã kết thúc"
        await msg.edit(embed=embed, view=DisabledJoinView(label=ended_label))

        if winners:
            await channel.send(tr(s, "giveaway.congrats", winners=winners_mentions, prize=gw['prize'], url=msg.jump_url))
        else:
            await channel.send(tr(s, "giveaway.ended_empty", prize=gw['prize'], url=msg.jump_url))

    @tasks.loop(seconds=15)
    async def giveaway_loop(self):
        active_gws = await async_get_active_giveaways()
        now = time.time()
        for gw in active_gws:
            if gw["end_at"] <= now:
                gw_fresh = await async_get_giveaway(gw["message_id"])
                if gw_fresh and gw_fresh.get("ended") == 1:
                    continue
                await async_update_giveaway(gw["message_id"], ended=1)
                await self.roll_giveaway(gw)

    @giveaway_loop.before_loop
    async def before_giveaway_loop(self):
        await self.bot.wait_until_ready()
        # Đăng ký persistent view cho giveaway buttons
        self.bot.add_view(DynamicJoinView())


async def setup(bot):
    await bot.add_cog(Giveaway(bot))

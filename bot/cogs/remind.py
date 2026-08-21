"""
Cog: Remind (v2) — Hệ thống nhắc nhở & hẹn giờ thông minh (/remindme, /reminders, /delreminder)
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import config
from database import (
    async_get_guild_settings,
    async_is_module_enabled,
    async_add_reminder,
    async_get_due_reminders,
    async_delete_reminder,
    async_get_user_reminders
)
from i18n import tr


def parse_time_duration(time_str: str) -> int | None:
    """
    Chuyển đổi chuỗi thời gian thành số giây (seconds).
    Hỗ trợ:
    - 30s, 10m, 1h, 2h30m, 1d, 2d, 1w
    - 20:30, 08:00 (Hẹn giờ theo mốc giờ trong ngày)
    - Số nguyên đơn thuần (mặc định hiểu là phút, ví dụ: '10' -> 600s)
    """
    time_str = time_str.strip().lower()
    if not time_str:
        return None

    # 1. Kiểm tra định dạng giờ:phút (vd: 20:30 hoặc 08:15)
    time_match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            now_dt = datetime.now()
            target_dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_dt <= now_dt:
                target_dt += timedelta(days=1)
            diff = int((target_dt - now_dt).total_seconds())
            return diff if diff > 0 else None

    # 2. Kiểm tra định dạng số đơn thuần (hiểu là phút)
    if time_str.isdigit():
        return int(time_str) * 60

    # 3. Kiểm tra định dạng kết hợp: 1d2h30m10s
    pattern = r'(?:(\d+)\s*w)?\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?'
    match = re.match(f"^{pattern}$", time_str)
    if match and any(match.groups()):
        weeks   = int(match.group(1) or 0)
        days    = int(match.group(2) or 0)
        hours   = int(match.group(3) or 0)
        minutes = int(match.group(4) or 0)
        seconds = int(match.group(5) or 0)
        total_seconds = (weeks * 604800) + (days * 86400) + (hours * 3600) + (minutes * 60) + seconds
        return total_seconds if total_seconds > 0 else None

    return None


class Remind(commands.Cog):
    """Module Nhắc nhở & Hẹn giờ thông minh."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()

    @tasks.loop(seconds=15)
    async def reminder_task(self):
        """Quét và gửi các thông báo nhắc nhở đến hạn mỗi 15 giây."""
        try:
            now_ts = int(time.time())
            due_reminders = await async_get_due_reminders(now_ts)
            for r in due_reminders:
                remind_id = r["id"]
                user_id = int(r["user_id"])
                guild_id = int(r["guild_id"]) if r.get("guild_id") else None
                channel_id = int(r["channel_id"]) if r.get("channel_id") else None
                reason = r["reason"]

                # 1. Tìm user
                user = self.bot.get_user(user_id)
                if not user:
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except Exception:
                        user = None

                embed = discord.Embed(
                    title="⏰ Nhắc Nhở Đã Đến Giờ!",
                    description=f"**Nội dung:**\n>>> {reason}",
                    color=config.COLOR_PING,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="Zeryn Reminder • Hẹn giờ thông minh", icon_url=self.bot.user.display_avatar.url if self.bot.user else None)

                sent = False
                # 2. Thử gửi vào kênh chat ban đầu
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel and hasattr(channel, "send"):
                        try:
                            mention_str = user.mention if user else f"<@{user_id}>"
                            await channel.send(content=f"🔔 {mention_str}, bạn có một nhắc nhở!", embed=embed)
                            sent = True
                        except Exception:
                            pass

                # 3. Nếu chưa gửi được (hoặc kênh bị xóa / không có quyền), gửi qua DM
                if not sent and user:
                    try:
                        await user.send(content="🔔 Bạn có một lời nhắc hẹn giờ!", embed=embed)
                        sent = True
                    except Exception:
                        pass

                # 4. Xóa nhắc nhở khỏi database
                await async_delete_reminder(remind_id)
        except Exception as e:
            pass

    @reminder_task.before_loop
    async def before_reminder_task(self):
        await self.bot.wait_until_ready()

    # ─── Commands ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="remindme", aliases=["remind", "timer"], description="Đặt lịch nhắc nhở bạn sau một khoảng thời gian")
    @app_commands.describe(
        time="Thời gian nhắc (VD: 10m, 1h30m, 2d, hoặc 20:30)",
        reason="Nội dung cần nhắc nhở",
        dm="Gửi tin nhắn riêng qua DM thay vì kênh chat? (Mặc định: Không)"
    )
    async def remindme(self, ctx: commands.Context, time: str, reason: str, dm: bool = False):
        seconds = parse_time_duration(time)
        if not seconds:
            return await ctx.send(
                "⚠️ **Định dạng thời gian không hợp lệ!**\n"
                "💡 *Ví dụ hợp lệ: `10m` (10 phút), `1h30m` (1 giờ 30 phút), `2d` (2 ngày), hoặc `20:00` (8 giờ tối).*",
                ephemeral=True
            )

        if seconds < 10:
            return await ctx.send("⚠️ Thời gian hẹn tối thiểu là **10 giây**!", ephemeral=True)
        if seconds > 30 * 86400: # 30 days max
            return await ctx.send("⚠️ Thời gian hẹn tối đa là **30 ngày**!", ephemeral=True)

        now_ts = int(time.time())
        target_ts = now_ts + seconds
        guild_id = str(ctx.guild.id) if (ctx.guild and not dm) else ""
        channel_id = str(ctx.channel.id) if (ctx.guild and not dm) else ""

        reminder_id = await async_add_reminder(
            user_id=str(ctx.author.id),
            guild_id=guild_id,
            channel_id=channel_id,
            reason=reason.strip(),
            remind_at=target_ts
        )

        embed = discord.Embed(
            title="⏰ Đã Đặt Lịch Nhắc Nhở Thành Công!",
            description=(
                f"📝 **Nội dung:** {reason.strip()}\n"
                f"⏳ **Thời gian:** <t:{target_ts}:F> (<t:{target_ts}:R>)\n"
                f"📍 **Nơi nhận:** {'📥 Tin nhắn riêng (DM)' if dm or not ctx.guild else f'💬 {ctx.channel.mention}'}\n"
                f"🆔 **Mã nhắc nhở:** `#{reminder_id}`"
            ),
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Dùng /reminders để xem danh sách hoặc /delreminder để hủy", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="reminders", description="Xem danh sách các lời nhắc hẹn giờ đang hoạt động của bạn")
    async def reminders_list(self, ctx: commands.Context):
        reminders = await async_get_user_reminders(str(ctx.author.id))
        if not reminders:
            return await ctx.send("📭 Bạn hiện không có lời nhắc nào đang chờ.", ephemeral=True)

        embed = discord.Embed(
            title=f"📋 Danh Sách Nhắc Nhở Của {ctx.author.display_name}",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        desc_lines = []
        for r in reminders:
            ts = r["remind_at"]
            desc_lines.append(
                f"**`#{r['id']}`** • <t:{ts}:R> (<t:{ts}:d> <t:{ts}:t>)\n"
                f"└ 📝 *{r['reason'][:80]}*\n"
            )

        embed.description = "\n".join(desc_lines)
        embed.set_footer(text="Hủy nhắc nhở bằng lệnh: /delreminder <id>", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="delreminder", aliases=["unremind"], description="Hủy một lời nhắc hẹn giờ")
    @app_commands.describe(reminder_id="ID của lời nhắc (xem qua /reminders)")
    async def delreminder(self, ctx: commands.Context, reminder_id: int):
        reminders = await async_get_user_reminders(str(ctx.author.id))
        target = next((r for r in reminders if r["id"] == reminder_id), None)
        if not target:
            return await ctx.send(f"❌ Không tìm thấy lời nhắc có ID `#{reminder_id}` thuộc về bạn!", ephemeral=True)

        await async_delete_reminder(reminder_id)
        await ctx.send(f"✅ Đã hủy lời nhắc `#{reminder_id}` thành công!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Remind(bot))

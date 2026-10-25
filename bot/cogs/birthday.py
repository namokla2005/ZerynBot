"""
Cog: Birthday — Set/check/list birthdays, auto midnight congratulations,
temporary Birthday VIP role, gift Coins & XP.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import logging
import math
import time
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_set_birthday, async_get_birthday, async_remove_birthday,
    async_get_birthdays_today, async_get_upcoming_birthdays,
    async_get_birthday_settings,
    async_add_temp_role,
)
from i18n import tr
try:
    from emojis import e, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, clean_title

logger = logging.getLogger("BotV2")


def _next_occurrence(month: int, day: int, now: datetime) -> datetime:
    """Lần sinh nhật kế tiếp; 29/02 rơi vào năm không nhuận được coi là 28/02."""
    for year in (now.year, now.year + 1):
        try:
            candidate = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            candidate = datetime(year, month, 28, tzinfo=timezone.utc)
        if candidate >= now:
            return candidate
    return datetime(now.year + 1, month, 28, tzinfo=timezone.utc)


def _level_from_xp(xp: int) -> int:
    return math.floor(0.1 * math.sqrt(max(0, int(xp))))




class Birthday(commands.Cog):
    """Birthday management and auto-congratulations."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.birthday_loop.start()
        self.temp_role_loop.start()

    async def cog_unload(self):
        self.birthday_loop.cancel()
        self.temp_role_loop.cancel()

    async def _check_module(self, interaction: discord.Interaction) -> dict | None:
        if not interaction.guild:
            return None
        enabled = await async_is_module_enabled(str(interaction.guild.id), "birthday")
        if not enabled:
            s = await async_get_guild_settings(str(interaction.guild.id))
            await interaction.response.send_message(
                tr(s, "common.module_disabled", module="Birthday"), ephemeral=True
            )
            return None
        return await async_get_guild_settings(str(interaction.guild.id))

    # ─── /birthday set ──────────────────────────────────────────────────
    birthday_group = app_commands.Group(name="birthday", description="Birthday commands")

    @birthday_group.command(name="set", description="Set your birthday")
    @app_commands.describe(day="Day (1-31)", month="Month (1-12)", year="Year (optional)")
    @app_commands.guild_only()
    async def birthday_set(self, interaction: discord.Interaction,
                           day: app_commands.Range[int, 1, 31],
                           month: app_commands.Range[int, 1, 12],
                           year: int = None):
        s = await self._check_module(interaction)
        if not s:
            return

        # Validate date
        try:
            test_year = year or 2000
            datetime(test_year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return await interaction.response.send_message(
                tr(s, "birthday.invalid_date"), ephemeral=True
            )

        if year and (year < 1920 or year > datetime.now(timezone.utc).year):
            return await interaction.response.send_message(
                tr(s, "birthday.invalid_year"), ephemeral=True
            )

        await async_set_birthday(str(interaction.user.id), day, month, year)
        date_str = f"{day:02d}/{month:02d}" + (f"/{year}" if year else "")
        await interaction.response.send_message(
            tr(s, "birthday.set_success", date=date_str), ephemeral=True
        )

    # ─── /birthday check ────────────────────────────────────────────────
    @birthday_group.command(name="check", description="Check someone's birthday")
    @app_commands.describe(member="User to check (default: yourself)")
    @app_commands.guild_only()
    async def birthday_check(self, interaction: discord.Interaction, member: discord.Member = None):
        s = await self._check_module(interaction)
        if not s:
            return

        target = member or interaction.user
        bday = await async_get_birthday(str(target.id))
        if not bday:
            return await interaction.response.send_message(
                tr(s, "birthday.not_set", user=target.display_name), ephemeral=True
            )

        now = datetime.now(timezone.utc)
        bday_this_year = _next_occurrence(bday["month"], bday["day"], now)
        days_until = (bday_this_year - now).days

        date_str = f"{bday['day']:02d}/{bday['month']:02d}"
        if bday.get("year"):
            # Tuổi thật: nếu sinh nhật năm nay CHƯA tới thì phải trừ 1
            # (trước đây 2 nhánh if/else giống hệt nhau nên luôn báo dư 1 tuổi).
            had_birthday_this_year = (now.month, now.day) >= (bday["month"], bday["day"])
            age = now.year - bday["year"] - (0 if had_birthday_this_year else 1)
            date_str += f"/{bday['year']}"
        else:
            age = None

        embed = discord.Embed(
            title=f"{e('zb_cat_birthday')} {target.display_name}",
            color=0xFF69B4,
        )
        embed.add_field(name=tr(s, "birthday.field_date"), value=f"📅 {date_str}", inline=True)
        embed.add_field(name=tr(s, "birthday.field_countdown"), value=f"⏳ {days_until} " + tr(s, "birthday.days_left"), inline=True)
        if age:
            embed.add_field(name=tr(s, "birthday.field_age"), value=f"🎈 {age}", inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ─── /birthday list ─────────────────────────────────────────────────
    @birthday_group.command(name="list", description="View upcoming birthdays in this server")
    @app_commands.guild_only()
    async def birthday_list(self, interaction: discord.Interaction):
        s = await self._check_module(interaction)
        if not s:
            return

        now = datetime.now(timezone.utc)
        upcoming = await async_get_upcoming_birthdays(now.month, now.day, limit=10)

        # Filter to members in this guild
        guild_members = {str(m.id): m for m in interaction.guild.members}
        filtered = [b for b in upcoming if b["user_id"] in guild_members]

        if not filtered:
            return await interaction.response.send_message(
                tr(s, "birthday.no_birthdays"), ephemeral=True
            )

        lines = []
        for i, b in enumerate(filtered[:10], 1):
            m = guild_members[b["user_id"]]
            bday_this_year = _next_occurrence(b["month"], b["day"], now)
            days = (bday_this_year - now).days
            lines.append(f"**{i}.** {m.mention} — `{b['day']:02d}/{b['month']:02d}` ({days}d)")

        embed = discord.Embed(
            title=embed_title("zb_cat_birthday", tr(s, "birthday.list_title")),
            description="\n".join(lines),
            color=0xFF69B4,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /birthday remove ───────────────────────────────────────────────
    @birthday_group.command(name="remove", description="Remove your birthday")
    @app_commands.guild_only()
    async def birthday_remove(self, interaction: discord.Interaction):
        s = await self._check_module(interaction)
        if not s:
            return

        removed = await async_remove_birthday(str(interaction.user.id))
        if removed:
            await interaction.response.send_message(tr(s, "birthday.remove_success"), ephemeral=True)
        else:
            await interaction.response.send_message(tr(s, "birthday.not_set_self"), ephemeral=True)

    # ─── Midnight Birthday Loop ─────────────────────────────────────────
    @tasks.loop(hours=1)
    async def birthday_loop(self):
        """Check for birthdays every hour. Send congratulations at midnight (UTC).

        Lưu ý: loop chạy mỗi giờ nên trong khung 0h UTC nó có thể chạy nhiều lần.
        Vì vậy mỗi guild/ngày chỉ được xử lý MỘT lần — chống tặng coin/XP/VIP trùng
        (trước đây có thể gửi lặp vài chục lần trong cùng một buổi tối).
        """
        now = datetime.now(timezone.utc)
        # Chạy mọi giờ: marker theo ngày đảm bảo mỗi guild chỉ tặng một lần, và
        # downtime quanh 00:00 UTC không còn làm mất trọn ngày sinh nhật.
        today_key = now.strftime("%Y-%m-%d")
        today_birthdays = await async_get_birthdays_today(now.day, now.month)
        if not today_birthdays:
            return

        from database import async_get_maintenance_job, async_set_maintenance_job

        for guild in self.bot.guilds:
            try:
                # Đã chạy cho guild này trong ngày hôm nay? → bỏ qua.
                if await async_get_maintenance_job(f"birthday:{guild.id}:{today_key}"):
                    continue

                enabled = await async_is_module_enabled(str(guild.id), "birthday")
                if not enabled:
                    continue

                settings = await async_get_birthday_settings(str(guild.id))
                channel_id = settings.get("channel_id")
                if not channel_id:
                    continue

                channel = guild.get_channel(int(channel_id))
                if not channel:
                    continue

                s = await async_get_guild_settings(str(guild.id))
                role_id = settings.get("role_id")
                gift_coins = settings.get("gift_coins", 500)
                gift_xp = settings.get("gift_xp", 200)
                msg_template = settings.get("message_template")

                for bday in today_birthdays:
                    member = guild.get_member(int(bday["user_id"]))
                    if not member:
                        continue

                    # Send congratulation embed
                    if msg_template:
                        desc = msg_template.replace("{user}", member.mention).replace("{server}", guild.name)
                    else:
                        desc = tr(s, "birthday.auto_message", user=member.mention)

                    embed = discord.Embed(
                        title=embed_title("zb_cat_birthday", tr(s, "birthday.auto_title")),
                        description=desc,
                        color=0xFF69B4,
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)

                    gifts = []
                    # Gift coins
                    if gift_coins > 0:
                        try:
                            from database import async_modify_wallet
                            await async_modify_wallet(str(guild.id), str(member.id), gift_coins)
                            gifts.append(f"{e('zb_coin')} +{gift_coins} Coins")
                        except Exception as e:
                            logger.warning(f"[Birthday] Error gifting coins: {e}")

                    # Gift XP
                    if gift_xp > 0:
                        try:
                            from database import async_add_user_xp
                            await async_add_user_xp(
                                str(guild.id), str(member.id), gift_xp,
                                level_from_xp=_level_from_xp,
                            )
                            gifts.append(f"⭐ +{gift_xp} XP")
                        except Exception as e:
                            logger.warning(f"[Birthday] Error gifting XP: {e}")

                    if gifts:
                        embed.add_field(name="🎁 " + tr(s, "birthday.gifts"), value="\n".join(gifts), inline=False)

                    await channel.send(embed=embed)

                    # Add temporary Birthday VIP role
                    if role_id:
                        role = guild.get_role(int(role_id))
                        if role and role < guild.me.top_role:
                            added = False
                            try:
                                await member.add_roles(role, reason="Birthday VIP")
                                added = True
                                await async_add_temp_role(
                                    str(guild.id), str(member.id), str(role.id),
                                    time.time() + 86400,
                                )
                            except Exception as e:
                                logger.warning(f"[Birthday] Failed to add/store VIP role: {e}")
                                if added:
                                    try:
                                        await member.remove_roles(role, reason="Birthday VIP rollback")
                                    except Exception:
                                        pass

                # Đánh dấu đã xử lý xong cho guild trong ngày → không tặng lại.
                await async_set_maintenance_job(f"birthday:{guild.id}:{today_key}")

            except Exception as e:
                logger.error(f"[Birthday] Error processing guild {guild.id}: {e}")

    @birthday_loop.before_loop
    async def before_birthday_loop(self):
        await self.bot.wait_until_ready()

    # ─── Gỡ Birthday VIP role quá hạn (bền qua restart) ──────────────────
    @tasks.loop(minutes=1)
    async def temp_role_loop(self):
        from database import (
            async_get_expired_temp_roles,
            async_delete_temp_role,
            async_fail_temp_role,
        )

        rows = await async_get_expired_temp_roles(time.time(), limit=50)
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                await async_delete_temp_role(row["id"])
                continue
            member = guild.get_member(int(row["user_id"]))
            role = guild.get_role(int(row["role_id"]))
            if member is None or role is None:
                await async_delete_temp_role(row["id"])
                continue
            try:
                await member.remove_roles(role, reason="Birthday VIP expired")
                await async_delete_temp_role(row["id"])
            except discord.Forbidden:
                deleted = await async_fail_temp_role(row["id"], 3)
                logger.warning(
                    "[Birthday] Thiếu quyền gỡ VIP role %s khỏi %s (đã thử 3 lần: %s)",
                    role.id, member.id, deleted,
                )
            except Exception as exc:
                deleted = await async_fail_temp_role(row["id"], 3)
                logger.warning("[Birthday] Lỗi gỡ VIP role %s: %s (bỏ cuộc: %s)", role.id, exc, deleted)

    @temp_role_loop.before_loop
    async def before_temp_role_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthday(bot))

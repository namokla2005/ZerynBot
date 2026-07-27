"""
Cog: Leveling (v2)
"""
import sys, os, time, math, random, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

log = logging.getLogger("BotV2.Leveling")

import discord
from discord.ext import commands, tasks
from discord import app_commands
import config

from database import (
    async_is_module_enabled,
    async_get_leveling_settings,
    async_get_user_level,
    async_update_user_xp,
    async_get_level_roles,
    async_get_top_users,
    async_get_user_rank,
    async_reset_user_xp
)

def calc_level_from_xp(xp: int) -> int:
    return math.floor(0.1 * math.sqrt(xp))

def calc_xp_for_level(level: int) -> int:
    return int((level / 0.1) ** 2)

class Leveling(commands.Cog):
    """Hệ thống Leveling / XP cho người dùng."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_xp_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()

    async def _handle_level_up(self, member: discord.Member, old_level: int, new_level: int, settings: dict, current_channel=None):
        if new_level <= old_level:
            return
            
        guild = member.guild
        
        # Level Roles
        level_roles = await async_get_level_roles(str(guild.id))
        roles_to_add = []
        roles_to_remove = []
        
        # Determine highest role level earned
        highest_earned_lvl = 0
        for lvl in level_roles.keys():
            if int(lvl) <= new_level and int(lvl) > highest_earned_lvl:
                highest_earned_lvl = int(lvl)
                
        stack_rewards = settings.get("stack_rewards", 0)
        
        for lvl, role_id_str in level_roles.items():
            role = guild.get_role(int(role_id_str))
            if not role:
                continue
                
            lvl_int = int(lvl)
            if lvl_int <= new_level:
                if stack_rewards == 1:
                    # Keep all earned roles
                    if role not in member.roles:
                        roles_to_add.append(role)
                else:
                    # Only keep the highest earned role
                    if lvl_int == highest_earned_lvl:
                        if role not in member.roles:
                            roles_to_add.append(role)
                    else:
                        if role in member.roles:
                            roles_to_remove.append(role)
        
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason=f"Level Up (remove old)")
            except Exception:
                pass
                
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason=f"Level Up to {new_level}")
            except Exception:
                pass
                
        # Announcement
        channel_id = settings.get("announce_channel_id")
        channel = None
        if channel_id == "current":
            channel = current_channel
        elif channel_id:
            channel = guild.get_channel(int(channel_id))
            
        if channel:
            msg_template = settings.get("announce_message", "🎉 Chúc mừng {user} đã đạt cấp **{level}**!")
            msg = msg_template.replace("{user}", member.mention).replace("{user_name}", member.name).replace("{level}", str(new_level)).replace("{server}", guild.name)
            try:
                await channel.send(msg)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
            
        guild_id = str(message.guild.id)
        if not await async_is_module_enabled(guild_id, "leveling"):
            return
            
        settings = await async_get_leveling_settings(guild_id)
        user_data = await async_get_user_level(guild_id, str(message.author.id))
        
        now = time.time()
        last_msg_at = user_data.get("last_message_at", 0)
        
        # 60s cooldown for message XP
        if now - last_msg_at < 60:
            return
            
        xp_gain = random.randint(settings.get("message_xp_min", 15), settings.get("message_xp_max", 25))
        new_xp = user_data["xp"] + xp_gain
        old_level = user_data["level"]
        new_level = calc_level_from_xp(new_xp)
        
        await async_update_user_xp(guild_id, str(message.author.id), new_xp, new_level, last_message_at=now)
        
        if new_level > old_level:
            await self._handle_level_up(message.author, old_level, new_level, settings, current_channel=message.channel)

    @tasks.loop(seconds=90)
    async def voice_xp_task(self):
        # Lặp qua từng guild, nhưng skip nhanh nếu không có voice channel nào đủ người.
        # Mỗi user hợp lệ được thu thập rồi đọc level 1 lần (batch), ghi 1 lần update riêng.
        for guild in self.bot.guilds:
            try:
                guild_id = str(guild.id)

                # Skip nhanh: không có voice channel nào có >=2 thành viên → bỏ qua cả guild
                if not any(len(vc.members) >= 2 for vc in guild.voice_channels):
                    continue

                if not await async_is_module_enabled(guild_id, "leveling"):
                    continue

                settings = await async_get_leveling_settings(guild_id)
                voice_xp_gain = settings.get("voice_xp", 10)
                if voice_xp_gain <= 0:
                    continue

                now = time.time()

                # Thu thập tất cả member hợp lệ trong guild (không phải bot, không mute/deaf/afk)
                eligible: list[discord.Member] = []
                for vc in guild.voice_channels:
                    if len(vc.members) < 2:
                        continue
                    for member in vc.members:
                        if member.bot:
                            continue
                        v = member.voice
                        if v is None or v.self_mute or v.self_deaf or v.mute or v.deaf or v.afk:
                            continue
                        eligible.append(member)

                for member in eligible:
                    user_data = await async_get_user_level(guild_id, str(member.id))
                    last_voice_at = user_data.get("last_voice_xp_at", 0)

                    if now - last_voice_at < 80:  # buffer 10s dưới interval 90s
                        continue

                    new_xp = user_data["xp"] + voice_xp_gain
                    old_level = user_data["level"]
                    new_level = calc_level_from_xp(new_xp)

                    await async_update_user_xp(guild_id, str(member.id), new_xp, new_level, last_voice_xp_at=now)

                    if new_level > old_level:
                        await self._handle_level_up(member, old_level, new_level, settings, current_channel=member.voice.channel)
            except Exception as e:
                log.warning(f"[Leveling] voice_xp_task lỗi ở guild {getattr(guild, 'id', '?')}: {e}")
                continue
                        
    @voice_xp_task.before_loop
    async def before_voice_xp_task(self):
        await self.bot.wait_until_ready()

    # ─── Commands ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="rank", description="Xem cấp độ và XP của bạn hoặc người khác")
    @app_commands.describe(member="Người dùng cần xem")
    @commands.guild_only()
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        
        member = member or ctx.author
        if member.bot:
            return await ctx.send("❌ Bot không có cấp độ!")
            
        guild_id = str(ctx.guild.id)
        if not await async_is_module_enabled(guild_id, "leveling"):
            return await ctx.send("❌ Module **Leveling** đã bị tắt trong server này!")
        user_data = await async_get_user_level(guild_id, str(member.id))
        rank_pos = await async_get_user_rank(guild_id, str(member.id))
        
        xp = user_data["xp"]
        level = user_data["level"]
        
        next_level_xp = calc_xp_for_level(level + 1)
        prev_level_xp = calc_xp_for_level(level)
        
        # Try to generate rank card
        try:
            try:
                from bot.card_generator import generate_rank_card
            except (ImportError, ModuleNotFoundError):
                from card_generator import generate_rank_card
            buf = await generate_rank_card(member, xp, level, rank_pos, next_level_xp, prev_level_xp)
            if buf:
                file = discord.File(fp=buf, filename="rank.png")
                return await ctx.send(file=file)
        except Exception as e:
            import logging
            logging.getLogger("BotV2").warning(f"[Leveling] Rank card error: {e}")
            
        # Fallback to embed
        embed = discord.Embed(title=f"Cấp độ của {member.display_name}", color=config.COLOR_INFO)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Rank", value=f"#{rank_pos}", inline=True)
        embed.add_field(name="Level", value=f"{level}", inline=True)
        
        progress = xp - prev_level_xp
        total_needed = next_level_xp - prev_level_xp
        pct = int((progress / total_needed) * 100) if total_needed > 0 else 100
        
        bar_len = 20
        filled = int((pct / 100) * bar_len)
        bar = f"[{'█' * filled}{'░' * (bar_len - filled)}]"
        
        embed.add_field(name="XP", value=f"{xp} / {next_level_xp}\n`{bar}` {pct}%", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leaderboard", aliases=["lb"], description="Bảng xếp hạng cấp độ của server")
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if not await async_is_module_enabled(guild_id, "leveling"):
            return await ctx.send("❌ Module **Leveling** đã bị tắt trong server này!")
            
        top_users = await async_get_top_users(guild_id, 10)
        
        if not top_users:
            return await ctx.send("Chưa có ai nhận được XP trong server này!")
            
        embed = discord.Embed(title=f"🏆 Bảng xếp hạng - {ctx.guild.name}", color=config.COLOR_INFO)
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
            
        desc = ""
        for i, u in enumerate(top_users):
            member = ctx.guild.get_member(int(u["user_id"]))
            name = member.mention if member else f"<@{u['user_id']}>"
            
            medal = "🏅"
            if i == 0: medal = "🥇"
            elif i == 1: medal = "🥈"
            elif i == 2: medal = "🥉"
            
            desc += f"{medal} **#{i+1}** | {name} • **Lvl {u['level']}** ({u['xp']} XP)\n"
            
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.hybrid_group(name="xp", description="Quản lý XP người dùng")
    @commands.has_permissions(administrator=True)
    async def xp(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("Sử dụng: `/xp set` hoặc `/xp reset`")

    @xp.command(name="set", description="Thiết lập XP cho một người dùng")
    @app_commands.describe(member="Người dùng", amount="Số lượng XP mới")
    async def xp_set(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount < 0:
            return await ctx.send("❌ XP không thể âm!")
            
        guild_id = str(ctx.guild.id)
        new_level = calc_level_from_xp(amount)
        await async_update_user_xp(guild_id, str(member.id), amount, new_level)
        
        await ctx.send(f"✅ Đã đặt XP của {member.mention} thành **{amount}** (Cấp độ: **{new_level}**).")

    @xp.command(name="reset", description="Khôi phục XP của một người dùng về 0")
    @app_commands.describe(member="Người dùng")
    async def xp_reset(self, ctx: commands.Context, member: discord.Member):
        guild_id = str(ctx.guild.id)
        await async_reset_user_xp(guild_id, str(member.id))
        await ctx.send(f"✅ Đã reset XP của {member.mention} về 0.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))

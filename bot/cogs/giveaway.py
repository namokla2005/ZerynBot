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
    async_get_active_giveaways
)

def parse_duration(duration_str: str) -> int:
    """Parse a string like '1h', '30m', '1d' into seconds."""
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

class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaway_loop.start()

    def cog_unload(self):
        self.giveaway_loop.cancel()

    @commands.hybrid_group(name="giveaway", description="Quản lý Giveaway")
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("Sử dụng: `/giveaway start`, `/giveaway end`, `/giveaway reroll`")

    @giveaway.command(name="start", description="Tạo một Giveaway mới")
    @app_commands.describe(duration="Thời gian (vd: 1m, 1h, 1d)", winners="Số người thắng", prize="Phần thưởng")
    async def g_start(self, ctx: commands.Context, duration: str, winners: int, prize: str):
        guild_id = str(ctx.guild.id)
        if not await async_is_module_enabled(guild_id, "giveaways"):
            return await ctx.send("❌ Module **Giveaways** đã bị tắt trong server này!", ephemeral=True)
            
        seconds = parse_duration(duration)
        if seconds <= 0:
            return await ctx.send("❌ Thời gian không hợp lệ! (Ví dụ: `10m`, `1h`, `2d`)", ephemeral=True)
            
        if winners < 1:
            return await ctx.send("❌ Số người thắng phải ít nhất là 1!", ephemeral=True)
            
        end_time = int(time.time() + seconds)
        
        embed = discord.Embed(title=f"🎉 GIVEAWAY: {prize}", color=config.COLOR_PRIMARY)
        embed.description = f"Bấm vào nút **🎉 Tham gia** bên dưới để nhận cơ hội trúng giải nhé!"
        embed.add_field(name="🎁 Phần thưởng", value=f"**{prize}**", inline=False)
        embed.add_field(name="🏆 Số người thắng", value=f"**{winners}**", inline=True)
        embed.add_field(name="👥 Số người tham gia", value="**0** người", inline=True)
        embed.add_field(name="⏰ Kết thúc", value=f"<t:{end_time}:R> (<t:{end_time}:f>)", inline=False)
        embed.set_footer(text=f"Tạo bởi {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        
        class DynamicJoinView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                
            @discord.ui.button(label="🎉 Tham gia", style=discord.ButtonStyle.primary, custom_id="gw_join_btn")
            async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                msg_id = str(interaction.message.id)
                gw = await async_get_giveaway(msg_id)
                if not gw or gw["ended"] == 1:
                    return await interaction.response.send_message("❌ Giveaway này đã kết thúc hoặc không tồn tại!", ephemeral=True)
                    
                participants = json.loads(gw["participants_json"])
                user_id_str = str(interaction.user.id)
                
                if user_id_str in participants:
                    participants.remove(user_id_str)
                    await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
                    await interaction.response.send_message("Nhường người khác hả? Bạn đã rời khỏi Giveaway!", ephemeral=True)
                else:
                    participants.append(user_id_str)
                    await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
                    await interaction.response.send_message("🎉 Bạn đã tham gia Giveaway thành công! Chúc may mắn nhé!", ephemeral=True)
                    
                embed = interaction.message.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name == "👥 Số người tham gia":
                        embed.set_field_at(i, name="👥 Số người tham gia", value=f"**{len(participants)}** người", inline=True)
                        break
                try:
                    await interaction.message.edit(embed=embed)
                except:
                    pass

        view = DynamicJoinView()
        msg = await ctx.send(embed=embed, view=view)
        
        # Save to DB
        await async_create_giveaway(
            guild_id=guild_id,
            channel_id=str(ctx.channel.id),
            message_id=str(msg.id),
            host_id=str(ctx.author.id),
            prize=prize,
            winners_count=winners,
            end_at=end_time
        )

    @giveaway.command(name="end", description="Kết thúc sớm một Giveaway")
    @app_commands.describe(message_id="ID của tin nhắn Giveaway")
    async def g_end(self, ctx: commands.Context, message_id: str):
        gw = await async_get_giveaway(message_id)
        if not gw or gw["guild_id"] != str(ctx.guild.id):
            return await ctx.send("❌ Không tìm thấy Giveaway này trong server!")
        if gw["ended"] == 1:
            return await ctx.send("❌ Giveaway này đã kết thúc rồi!")
            
        await async_update_giveaway(message_id, ended=1)
        await ctx.send("✅ Đang tiến hành quay số và kết thúc Giveaway...")
        await self.roll_giveaway(gw)

    @giveaway.command(name="reroll", description="Chọn lại người thắng mới")
    @app_commands.describe(message_id="ID của tin nhắn Giveaway")
    async def g_reroll(self, ctx: commands.Context, message_id: str):
        gw = await async_get_giveaway(message_id)
        if not gw or gw["guild_id"] != str(ctx.guild.id):
            return await ctx.send("❌ Không tìm thấy Giveaway này trong server!")
        if gw["ended"] == 0:
            return await ctx.send("❌ Giveaway này chưa kết thúc!")
            
        participants = json.loads(gw["participants_json"])
        if len(participants) == 0:
            return await ctx.send("❌ Không có ai tham gia để reroll!")
            
        winner_id = random.choice(participants)
        
        channel = ctx.guild.get_channel(int(gw["channel_id"]))
        if channel:
            await channel.send(f"🎉 **REROLL**: Chúc mừng <@{winner_id}> đã trúng giải **{gw['prize']}**! (https://discord.com/channels/{ctx.guild.id}/{gw['channel_id']}/{message_id})")
            await ctx.send("✅ Reroll thành công!")
        else:
            await ctx.send("❌ Không tìm thấy kênh để gửi thông báo!")

    async def roll_giveaway(self, gw: dict):
        channel = self.bot.get_channel(int(gw["channel_id"]))
        if not channel:
            return
            
        try:
            msg = await channel.fetch_message(int(gw["message_id"]))
        except discord.NotFound:
            return
            
        participants = json.loads(gw["participants_json"])
        winners_count = gw["winners_count"]
        
        if len(participants) < winners_count:
            winners = participants
        else:
            winners = random.sample(participants, winners_count)
            
        embed = msg.embeds[0]
        embed.title = f"🎊 GIVEAWAY KẾT THÚC: {gw['prize']}"
        embed.color = discord.Color.dark_gray()
        
        for i, field in enumerate(embed.fields):
            if "⏰ Kết thúc" in field.name:
                embed.set_field_at(i, name="⏰ Đã kết thúc lúc", value=f"<t:{gw['end_at']}:f>", inline=False)
                break
                
        if winners:
            winners_mentions = ", ".join([f"<@{w}>" for w in winners])
            embed.description = f"**Người trúng giải:** {winners_mentions}"
        else:
            embed.description = "**Không có ai tham gia!** 😢"
            
        class DisabledJoinView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                btn = discord.ui.Button(label="🎉 Đã kết thúc", style=discord.ButtonStyle.secondary, custom_id="gw_join_btn_ended", disabled=True)
                self.add_item(btn)
                
        await msg.edit(embed=embed, view=DisabledJoinView())
        
        if winners:
            await channel.send(f"🎉 Chúc mừng {winners_mentions} đã trúng giải **{gw['prize']}**! 🎁\n{msg.jump_url}")
        else:
            await channel.send(f"😢 Giveaway **{gw['prize']}** đã kết thúc mà không có ai tham gia!\n{msg.jump_url}")

    @tasks.loop(seconds=15)
    async def giveaway_loop(self):
        active_gws = await async_get_active_giveaways()
        now = time.time()
        for gw in active_gws:
            if gw["end_at"] <= now:
                await async_update_giveaway(gw["message_id"], ended=1)
                await self.roll_giveaway(gw)

    @giveaway_loop.before_loop
    async def before_giveaway_loop(self):
        await self.bot.wait_until_ready()
        
        class DynamicJoinView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
            @discord.ui.button(label="🎉 Tham gia", style=discord.ButtonStyle.primary, custom_id="gw_join_btn")
            async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                msg_id = str(interaction.message.id)
                gw = await async_get_giveaway(msg_id)
                if not gw or gw["ended"] == 1:
                    return await interaction.response.send_message("❌ Giveaway này đã kết thúc hoặc không tồn tại!", ephemeral=True)
                participants = json.loads(gw["participants_json"])
                user_id_str = str(interaction.user.id)
                if user_id_str in participants:
                    participants.remove(user_id_str)
                    await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
                    await interaction.response.send_message("Nhường người khác hả? Bạn đã rời khỏi Giveaway!", ephemeral=True)
                else:
                    participants.append(user_id_str)
                    await async_update_giveaway(msg_id, participants_json=json.dumps(participants))
                    await interaction.response.send_message("🎉 Bạn đã tham gia Giveaway thành công! Chúc may mắn nhé!", ephemeral=True)
                embed = interaction.message.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name == "👥 Số người tham gia":
                        embed.set_field_at(i, name="👥 Số người tham gia", value=f"**{len(participants)}** người", inline=True)
                        break
                try:
                    await interaction.message.edit(embed=embed)
                except:
                    pass
                    
        self.bot.add_view(DynamicJoinView())

async def setup(bot):
    await bot.add_cog(Giveaway(bot))

"""
ticket.py — Discord Bot Cog for Ticket System.
Handles ticket creation, permission overwrites, and deletion.
Uses global on_interaction listener to dynamically route button clicks.
"""
import asyncio
import os
import sys
import discord
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import database as db


class Ticket(commands.Cog, name="Tickets"):
    """🎫 Lệnh và sự kiện Ticket System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            return
        enabled = await db.async_is_module_enabled(str(ctx.guild.id), "tickets")
        if not enabled:
            await ctx.send("❌ Module **Tickets** đã bị tắt trong server này!")
            raise commands.CommandError("Module disabled")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Global listener to handle ticket buttons without needing persistent views registration."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        
        # ─── Ticket Button Click ──────────────────────────────────────────────
        if custom_id.startswith("ticket:btn:"):
            try:
                btn_id = int(custom_id.split(":")[-1])
            except ValueError:
                return

            # Check if module is enabled
            guild = interaction.guild
            if not guild:
                return
            enabled = await db.async_is_module_enabled(str(guild.id), "tickets")
            if not enabled:
                await interaction.response.send_message(
                    "❌ Tính năng Ticket đã bị tắt trong server này!", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            # Retrieve button settings
            btn_data = await db.async_get_ticket_button(btn_id)
            if not btn_data:
                await interaction.followup.send(
                    "❌ Nút bấm này không còn khả dụng (đã bị xóa trên dashboard)!", ephemeral=True
                )
                return

            category_id = int(btn_data["category_id"])
            category = guild.get_channel(category_id)
            if not category or not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send(
                    "❌ Thất bại: Không tìm thấy danh mục để tạo kênh hỗ trợ!", ephemeral=True
                )
                return

            member = interaction.user

            # ─── Duplicate ticket check ──────────────────────────────────────
            clean_username_check = "".join(c for c in member.name.lower() if c.isalnum() or c in "-_")
            existing = discord.utils.get(
                category.channels,
                name=f"ticket-{clean_username_check}-{''.join(c for c in btn_data['label'].lower() if c.isalnum() or c in '-_')}"[:100]
            )
            if existing:
                await interaction.followup.send(
                    f"❌ Bạn đã có một ticket đang mở tại {existing.mention}!", ephemeral=True
                )
                return

            # Setup Overwrites
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
                )
            }

            # Add support roles overwrites if configured (handles single or comma-separated list)
            support_role_id_str = btn_data.get("support_role_id")
            support_roles = []
            if support_role_id_str:
                role_ids = [int(rid.strip()) for rid in support_role_id_str.split(",") if rid.strip().isdigit()]
                for rid in role_ids:
                    r = guild.get_role(rid)
                    if r:
                        support_roles.append(r)
                        overwrites[r] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                        )

            # Construct clean channel name
            clean_username = "".join(c for c in member.name.lower() if c.isalnum() or c in "-_")
            clean_btn_label = "".join(c for c in btn_data["label"].lower() if c.isalnum() or c in "-_")
            channel_name = f"ticket-{clean_username}-{clean_btn_label}"
            channel_name = channel_name[:100]

            try:
                ticket_channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"Ticket của {member.name} (ID: {member.id}) | Hỗ trợ: {btn_data['label']}"
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Không thể tạo kênh ticket: {e}", ephemeral=True
                )
                return

            # Send welcome embed inside the ticket channel
            embed = discord.Embed(
                title=f"🎫 Ticket: {btn_data['label']}",
                description=f"Xin chào {member.mention}! Cảm ơn bạn đã gửi yêu cầu hỗ trợ.\n"
                            f"Vui lòng nhập chi tiết câu hỏi hoặc yêu cầu của bạn dưới đây.\n"
                            f"Đội ngũ quản trị và hỗ trợ sẽ phản hồi sớm nhất có thể.",
                color=0x5865F2
            )
            embed.add_field(name="👤 Người tạo", value=member.mention, inline=True)
            if support_roles:
                embed.add_field(name="🛡️ Đội hỗ trợ", value=", ".join(r.mention for r in support_roles), inline=True)
            embed.set_footer(text="Nhấn nút màu đỏ bên dưới khi bạn đã trao đổi xong.")

            # Custom close view with static custom_id
            close_view = discord.ui.View(timeout=None)
            close_btn = discord.ui.Button(
                label="🔒 Đóng Ticket",
                style=discord.ButtonStyle.danger,
                custom_id="ticket:close"
            )
            close_view.add_item(close_btn)

            mentions = f"{member.mention}"
            if support_roles:
                mentions += " " + " ".join(r.mention for r in support_roles)

            await ticket_channel.send(content=mentions, embed=embed, view=close_view)
            await interaction.followup.send(
                f"✅ Đã tạo ticket thành công tại {ticket_channel.mention}!", ephemeral=True
            )
            
            self.bot.dispatch('ticket_action', guild, member, "Mở", channel_name)

        # ─── Ticket Close Button Click ────────────────────────────────────────
        elif custom_id == "ticket:close":
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            channel = interaction.channel
            member = interaction.user
            if not guild or not channel:
                return

            # Verify it is a ticket channel
            if not channel.name.startswith("ticket-"):
                await interaction.followup.send(
                    "❌ Lệnh này chỉ thực hiện được trong kênh ticket!", ephemeral=True
                )
                return

            # Permissions check
            # Allowed: Admin, Manage Channels, or Creator (matching ID in topic)
            is_allowed = False
            if member.guild_permissions.administrator or member.guild_permissions.manage_channels:
                is_allowed = True
            else:
                topic = channel.topic or ""
                if f"(ID: {member.id})" in topic:
                    is_allowed = True

            if not is_allowed:
                await interaction.followup.send(
                    "❌ Bạn không có quyền đóng ticket này!", ephemeral=True
                )
                return

            await channel.send(
                "🔒 **Kênh hỗ trợ này sẽ bị đóng và xóa hoàn toàn sau 5 giây...**"
            )
            
            self.bot.dispatch('ticket_action', guild, member, "Đóng/Xóa", channel.name)
            
            await asyncio.sleep(5)
            try:
                await channel.delete(reason=f"Ticket closed by {member.name}")
            except Exception as e:
                print(f"[Ticket] Error deleting channel: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket(bot))

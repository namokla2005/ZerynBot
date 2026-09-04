"""
Cog: Custom Commands & Auto-Responders (v2)
Features:
- Trigger-Response engine matching exact, contains, or startswith.
- Dynamic Variable Replacements ({user}, {mention}, {server}, {members}, {random:X-Y}).
- Rich Discord Embed support or Plain Text responses.
- Usage counter and seamless sync with Web Dashboard.
"""
import sys, os, json, random, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_get_custom_commands, async_find_custom_command,
    async_increment_custom_command_usage, add_custom_command,
    delete_custom_command
)
from i18n import tr
try:
    from emojis import e, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, clean_title


def format_custom_response(template: str, message: discord.Message) -> str:
    """Thay thế các biến động trong câu phản hồi."""
    res = template
    res = res.replace("{user}", message.author.display_name)
    res = res.replace("{user_name}", message.author.name)
    res = res.replace("{mention}", message.author.mention)
    res = res.replace("{server}", message.guild.name)
    res = res.replace("{members}", str(message.guild.member_count))
    res = res.replace("{channel}", message.channel.name)
    res = res.replace("{channel_mention}", message.channel.mention)

    # Thay thế {random:min-max}
    pattern = r"\{random:(\d+)-(\d+)\}"
    matches = re.findall(pattern, res)
    for m in matches:
        try:
            low, high = int(m[0]), int(m[1])
            if low <= high:
                val = random.randint(low, high)
                res = res.replace(f"{{random:{m[0]}-{m[1]}}}", str(val), 1)
        except Exception:
            pass

    return res


class CustomCommands(commands.Cog):
    """Module quản lý Lệnh Tùy Biến & Tự Động Phản Hồi."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "customcommands")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if not await async_is_module_enabled(str(message.guild.id), "customcommands"):
            return

        matched_cmd = await async_find_custom_command(str(message.guild.id), message.content)
        if not matched_cmd:
            return

        await async_increment_custom_command_usage(matched_cmd["id"])

        embed_json_str = matched_cmd.get("embed_json")
        response_text = matched_cmd.get("response_text") or ""

        # Trường hợp phản hồi bằng Rich Embed
        if embed_json_str:
            try:
                data = json.loads(embed_json_str) if isinstance(embed_json_str, str) else embed_json_str
                # Parse embed
                title = format_custom_response(data.get("title", ""), message) if data.get("title") else None
                desc = format_custom_response(data.get("description", ""), message) if data.get("description") else None
                color_hex = data.get("color", "#5865F2").replace("#", "")
                try:
                    color = int(color_hex, 16)
                except ValueError:
                    color = 0x5865F2

                embed = discord.Embed(title=title, description=desc, color=color)
                if data.get("image_url"):
                    embed.set_image(url=data["image_url"])
                if data.get("thumbnail_url"):
                    embed.set_thumbnail(url=data["thumbnail_url"])
                if data.get("footer_text"):
                    embed.set_footer(text=format_custom_response(data["footer_text"], message))

                content_msg = format_custom_response(response_text, message) if response_text else None
                await message.channel.send(content=content_msg, embed=embed)
                return
            except Exception as e:
                print(f"[CustomCmd] Error parsing embed JSON: {e}")

        # Trường hợp phản hồi bằng Text thường
        if response_text:
            formatted = format_custom_response(response_text, message)
            await message.channel.send(formatted)

    # ─── Slash Commands for Custom Commands ────────────────────────────────────
    cmd_group = app_commands.Group(name="customcmd", description="Quản lý Lệnh Tùy Biến & Auto-Responder")

    @cmd_group.command(name="list", description="Xem danh sách các lệnh tùy biến trong server")
    async def cmd_list(self, interaction: discord.Interaction):
        s = await async_get_guild_settings(str(interaction.guild.id))
        cmds = await async_get_custom_commands(str(interaction.guild.id))
        if not cmds:
            await interaction.response.send_message(tr(s, "customcmd.empty"), ephemeral=True)
            return

        desc = ""
        for c in cmds[:25]:
            match_badge = f"`[{c.get('match_type', 'exact')}]`"
            desc += f"• **`{c['trigger']}`** {match_badge} — {c.get('uses_count', 0)} {tr(s, 'customcmd.uses')}\n"

        embed = discord.Embed(
            title=embed_title("zb_cat_customcmd", tr(s, "customcmd.list_title", server=interaction.guild.name)),
            description=desc,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.send_message(embed=embed)

    @cmd_group.command(name="add", description="Thêm một lệnh phản hồi văn bản nhanh")
    @app_commands.describe(
        trigger="Từ khóa kích hoạt (VD: !ip, !rules, !donate)",
        response="Câu trả lời của bot (hỗ trợ {user}, {server}, {members})"
    )
    async def cmd_add(self, interaction: discord.Interaction, trigger: str, response: str):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(tr(s, "common.no_permission"), ephemeral=True)
            return

        clean_trigger = trigger.strip().lower()
        import database as db
        await db.async_add_custom_command(
            guild_id=str(interaction.guild.id),
            trigger=clean_trigger,
            match_type="exact",
            response_text=response,
            embed_json=None,
            creator_id=str(interaction.user.id)
        )
        await interaction.response.send_message(tr(s, "customcmd.added_success", trigger=clean_trigger), ephemeral=True)

    @cmd_group.command(name="delete", description="Xóa một lệnh tùy biến")
    @app_commands.describe(trigger="Từ khóa kích hoạt của lệnh cần xóa")
    async def cmd_delete(self, interaction: discord.Interaction, trigger: str):
        s = await async_get_guild_settings(str(interaction.guild.id))
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(tr(s, "common.no_permission"), ephemeral=True)
            return

        clean_trigger = trigger.strip().lower()
        cmds = await async_get_custom_commands(str(interaction.guild.id))
        target_cmd = next((c for c in cmds if c["trigger"].lower() == clean_trigger), None)

        if not target_cmd:
            await interaction.response.send_message(tr(s, "customcmd.not_found", trigger=clean_trigger), ephemeral=True)
            return

        import database as db
        await db.async_delete_custom_command(target_cmd["id"], str(interaction.guild.id))
        await interaction.response.send_message(tr(s, "customcmd.deleted_success", trigger=clean_trigger), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))

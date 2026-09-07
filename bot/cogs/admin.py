import io
import logging
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone

import checks
import discord
from discord.ext import commands, tasks

import config
from database import (
    async_get_guild_settings,
    async_is_module_enabled,
    async_wal_checkpoint,
)
from i18n import tr

try:
    from emojis import clean_title, e, embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import clean_title, e, embed_title

logger = logging.getLogger("BotV2.Admin")


class Admin(commands.Cog):
    """Lệnh quản trị server & bảo trì hệ thống."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_backup_task.start()

    def cog_unload(self):
        self.auto_backup_task.cancel()

    @tasks.loop(hours=24)
    async def auto_backup_task(self):
        """Tự động sao lưu database bot.db và dọn dẹp WAL mỗi 24 giờ."""
        try:
            # 1. Checkpoint WAL để database sạch sẽ
            await async_wal_checkpoint()

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "bot.db")
            if not os.path.isfile(db_path):
                return

            backup_dir = os.path.join(base_dir, "data", "backups")
            os.makedirs(backup_dir, exist_ok=True)

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
            zip_filename = f"backup_{timestamp}.zip"
            zip_path = os.path.join(backup_dir, zip_filename)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_path, arcname="bot.db")

            logger.info(f"📦 [Auto-Backup] Created database backup: {zip_path}")

            # 2. Xóa các bản backup cũ hơn 7 ngày để tiết kiệm dung lượng
            now = datetime.now(timezone.utc).timestamp()
            for f in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, f)
                if os.path.isfile(fp) and f.startswith("backup_") and f.endswith(".zip"):
                    if now - os.path.getmtime(fp) > 7 * 86400:
                        try:
                            os.remove(fp)
                        except Exception:
                            pass

            # 3. Gửi file backup về Discord Webhook chuyên dụng (BACKUP_DB)
            backup_webhook = config.BACKUP_DB_URL or config.WEBHOOK_LOG_URL
            if backup_webhook:
                import aiohttp
                size_kb = round(os.path.getsize(zip_path) / 1024, 2)
                async with aiohttp.ClientSession() as session:
                    with open(zip_path, "rb") as f:
                        form = aiohttp.FormData()
                        form.add_field(
                            "payload_json",
                            f'{{"embeds": [{{"title": "📦 Bản Sao Lưu Tự Động 24h (Database Backup)", "description": "✅ Đã tạo và lưu trữ thành công bản sao lưu `bot.db` định kỳ.\\n📁 **Dung lượng:** `{size_kb} KB`\\n⏱️ **Thời gian:** <t:{int(time.time())}:F>", "color": 5763719, "timestamp": "{datetime.now(timezone.utc).isoformat()}"}}]}}'
                        )
                        form.add_field("file", f, filename=zip_filename, content_type="application/zip")
                        await session.post(backup_webhook, data=form)
        except Exception as e:
            logger.warning(f"[Auto-Backup] Error during auto backup: {e}")

    @auto_backup_task.before_loop
    async def before_auto_backup_task(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="config", description="Xem cài đặt hiện tại của server và link dashboard")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def config_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)

        wc = s.get("welcome_channel_id")
        gc = s.get("goodbye_channel_id")
        not_cfg = tr(s, "admin.not_configured")
        w_ch  = f"<#{wc}>" if wc else not_cfg
        g_ch  = f"<#{gc}>" if gc else not_cfg
        w_type = tr(s, "admin.embed_type") if s.get("welcome_use_embed") else tr(s, "admin.text_type")
        g_type = tr(s, "admin.embed_type") if s.get("goodbye_use_embed") else tr(s, "admin.text_type")

        modules = {
            "welcome_goodbye": await async_is_module_enabled(guild_id, "welcome_goodbye"),
            "autoroles":       await async_is_module_enabled(guild_id, "autoroles"),
            "leveling":        await async_is_module_enabled(guild_id, "leveling"),
            "info":            await async_is_module_enabled(guild_id, "info"),
            "utility":         await async_is_module_enabled(guild_id, "utility"),
            "music":           await async_is_module_enabled(guild_id, "music"),
            "tickets":         await async_is_module_enabled(guild_id, "tickets"),
            "reactionroles":   await async_is_module_enabled(guild_id, "reactionroles"),
            "automods":        await async_is_module_enabled(guild_id, "automods"),
            "logger":          await async_is_module_enabled(guild_id, "logger"),
            "giveaways":       await async_is_module_enabled(guild_id, "giveaways")
        }
        
        # Split into two columns for better formatting
        mod_keys = list(modules.keys())
        half = (len(mod_keys) + 1) // 2
        
        mod_col1 = "\n".join(f"{'✅' if modules[k] else '❌'} `{k}`" for k in mod_keys[:half])
        mod_col2 = "\n".join(f"{'✅' if modules[k] else '❌'} `{k}`" for k in mod_keys[half:])

        embed = discord.Embed(
            title=embed_title("zb_cat_utility", tr(s, "admin.config_title", server=ctx.guild.name)),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name=tr(s, "admin.welcome_channel"),  value=w_ch,    inline=True)
        embed.add_field(name=tr(s, "admin.welcome_type"),     value=w_type,  inline=True)
        embed.add_field(name="\u200b",                         value="\u200b",inline=True)
        embed.add_field(name=tr(s, "admin.goodbye_channel"),  value=g_ch,    inline=True)
        embed.add_field(name=tr(s, "admin.goodbye_type"),     value=g_type,  inline=True)
        embed.add_field(name="\u200b",                         value="\u200b",inline=True)
        
        embed.add_field(name=tr(s, "admin.modules_label", num=1), value=mod_col1, inline=True)
        embed.add_field(name=tr(s, "admin.modules_label", num=2), value=mod_col2, inline=True)
        embed.add_field(name="\u200b",                            value="\u200b",inline=True)

        embed.add_field(
            name=tr(s, "admin.dashboard_label"),
            value=f"[{tr(s, 'admin.open_dashboard')}]({config.DASHBOARD_URL}/dashboard/{guild_id})",
            inline=False,
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=tr(s, "admin.open_dashboard"), style=discord.ButtonStyle.link, url=f"{config.DASHBOARD_URL}/dashboard/{guild_id}", emoji="🌐"))

        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="reactionroles", description="Truy cập Dashboard để tạo bảng Reaction Roles")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def reactionroles_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)
        embed = discord.Embed(
            title=embed_title("zb_cat_roles", tr(s, "admin.rr_title")),
            description=tr(s, "admin.rr_desc"),
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[{tr(s, 'admin.open_config')}]({config.DASHBOARD_URL}/dashboard/{guild_id}/reactionroles)"
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sync", description="Đồng bộ lệnh slash commands tức thì")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def sync_cmd(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        async with ctx.typing():
            try:
                # 1. Đồng bộ tức thì (0s) cho guild hiện tại
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced_guild = await self.bot.tree.sync(guild=ctx.guild)
                # 2. Đồng bộ toàn cầu
                synced_global = await self.bot.tree.sync()
                await ctx.send(tr(s, "admin.sync_success_detailed", guild_count=len(synced_guild), global_count=len(synced_global), guild_name=ctx.guild.name))
            except Exception as e:
                await ctx.send(tr(s, "admin.sync_error", error=str(e)))

    @commands.hybrid_command(name="ticket", description="Truy cập Dashboard để tạo panel ticket")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def ticket_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_guild_settings(guild_id)
        embed = discord.Embed(
            title=tr(s, "admin.ticket_title"),
            description=tr(s, "admin.ticket_desc"),
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="🌐 Link",
            value=f"[{tr(s, 'admin.open_config')}]({config.DASHBOARD_URL}/dashboard/{guild_id}/tickets)"
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="backup", description="[Chủ Bot] Sao lưu cơ sở dữ liệu bot.db ngay lập tức")
    async def backup_cmd(self, ctx: commands.Context):
        if not config.BOT_OWNER_ID or ctx.author.id != config.BOT_OWNER_ID:
            return await ctx.send("⛔ Lệnh này chỉ dành riêng cho **Chủ sở hữu Bot** (Bot Owner)!", ephemeral=True)

        await ctx.defer(ephemeral=True)
        try:
            # 1. Thu nhỏ và làm sạch WAL
            await async_wal_checkpoint()

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "bot.db")
            if not os.path.isfile(db_path):
                return await ctx.send("❌ Không tìm thấy file `data/bot.db`!", ephemeral=True)

            # 2. Tạo zip trong bộ nhớ RAM
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_path, arcname="bot.db")
            zip_buffer.seek(0)

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
            filename = f"ZerynBot_backup_{timestamp}.zip"
            size_kb = round(len(zip_buffer.getvalue()) / 1024, 2)

            file = discord.File(fp=zip_buffer, filename=filename)
            embed = discord.Embed(
                title="📦 Sao Lưu Cơ Sở Dữ Liệu Thành Công",
                description=(
                    f"✅ Đã đóng gói và làm sạch WAL file cơ sở dữ liệu `bot.db` an toàn.\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Dung lượng:** `{size_kb} KB`\n"
                    f"⏱️ **Thời gian:** <t:{int(time.time())}:F>"
                ),
                color=config.COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Bản sao lưu chứa toàn bộ cấu hình, level, kinh tế và playlist")
            await ctx.send(embed=embed, file=file, ephemeral=True)

            # Gửi thêm 1 bản lưu trữ lên Webhook BACKUP_DB
            backup_webhook = config.BACKUP_DB_URL
            if backup_webhook:
                try:
                    import aiohttp
                    zip_buffer.seek(0)
                    async with aiohttp.ClientSession() as session:
                        form = aiohttp.FormData()
                        form.add_field(
                            "payload_json",
                            f'{{"embeds": [{{"title": "📦 Bản Sao Lưu Thủ Công (/backup)", "description": "👑 **Người thực hiện:** <@{ctx.author.id}>\\n📁 **Dung lượng:** `{size_kb} KB`\\n⏱️ **Thời gian:** <t:{int(time.time())}:F>", "color": 5763719, "timestamp": "{datetime.now(timezone.utc).isoformat()}"}}]}}'
                        )
                        form.add_field("file", zip_buffer.getvalue(), filename=filename, content_type="application/zip")
                        await session.post(backup_webhook, data=form)
                except Exception as ex:
                    logger.warning(f"Failed to forward backup to BACKUP_DB webhook: {ex}")
        except Exception as e:
            await ctx.send(f"❌ Lỗi khi tạo bản sao lưu: `{e}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))



"""
Template chuẩn tạo Cog mới cho ZerynBot V2
Bao gồm:
- Module Guard kiểm tra trạng thái bật/tắt của Module
- Đa ngôn ngữ tr()
- Truy cập cơ sở dữ liệu bất đồng bộ aiosqlite
- Bắt lỗi và Logging an toàn
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import discord
from discord.ext import commands
from discord import app_commands
import config
from database import (
    async_get_guild_settings,
    async_is_module_enabled
)
from i18n import tr
from cache import cache

logger = logging.getLogger("bot.feature_name")


class ExampleFeature(commands.Cog, name="ExampleFeature"):
    """Mô tả tính năng của Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="examplename",
        description="Mô tả ngắn gọn lệnh hiển thị trong menu Discord"
    )
    @app_commands.describe(
        query="Tham số truyền vào cho lệnh"
    )
    async def example_cmd(self, ctx: commands.Context, query: str = ""):
        """Xử lý lệnh người dùng gọi."""
        # 1. Đảm bảo lệnh được gọi từ máy chủ
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể sử dụng trong máy chủ Discord.")

        guild_id = str(ctx.guild.id)
        settings = await async_get_guild_settings(guild_id)

        # 2. BẮT BUỘC: Kiểm tra Module Guard
        if not await async_is_module_enabled(guild_id, "example_module"):
            return await ctx.reply(
                tr(settings, "common.module_disabled"),
                ephemeral=True
            )

        # 3. Phản hồi trì hoãn (nếu tác vụ cần xử lý > 2 giây)
        # await ctx.defer()

        try:
            # 4. Xử lý nghiệp vụ chính
            result_text = f"Xử lý thành công cho: {query}" if query else "Hoàn tất!"

            # 5. Phản hồi kèm đa ngôn ngữ
            embed = discord.Embed(
                title=tr(settings, "example.title", default="✨ Kết quả"),
                description=result_text,
                color=config.COLOR_PRIMARY
            )
            embed.set_footer(text=f"{ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)

        except Exception as e:
            logger.error(f"Lỗi khi thực thi lệnh /examplename tại guild {guild_id}: {e}", exc_info=True)
            await ctx.reply(
                tr(settings, "common.error_occurred", default="❌ Đã xảy ra lỗi khi thực thi lệnh!"),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ExampleFeature(bot))

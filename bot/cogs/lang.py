"""
lang.py — Language Cog for ZerynBot V2.
Provides hybrid command /lang (slash + prefix) to set per-guild bot language.

Supported languages: vi, en, zh, es, pt, fr
Required permission: Manage Server (or Bot Owner)
"""
import discord
from discord import app_commands
from discord.ext import commands

from database import async_get_guild_settings, async_set_guild_language
from i18n import tr, i18n


LANG_CHOICES = [
    app_commands.Choice(name="🇻🇳 Tiếng Việt (vi)", value="vi"),
    app_commands.Choice(name="🇬🇧 English (en)",     value="en"),
    app_commands.Choice(name="🇨🇳 中文 (zh)",         value="zh"),
    app_commands.Choice(name="🇪🇸 Español (es)",      value="es"),
    app_commands.Choice(name="🇧🇷 Português (pt)",    value="pt"),
    app_commands.Choice(name="🇧🇪 Français (fr)",     value="fr"),
]


class Language(commands.Cog, name="Language"):
    """Quản lý ngôn ngữ của Bot trong máy chủ."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="lang",
        description="Thay đổi ngôn ngữ bot / Change bot language"
    )
    @app_commands.describe(language="Chọn ngôn ngữ / Select language (vi, en, zh, es, pt, fr)")
    @app_commands.choices(language=LANG_CHOICES)
    @app_commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def lang_cmd(self, ctx: commands.Context, language: str):
        """
        Đổi ngôn ngữ bot trong server này.
        Ví dụ: /lang language:en  hoặc  !lang en
        """
        guild_id = str(ctx.guild.id)
        supported = i18n.get_supported_languages()

        # Normalize: slash command trả về value của Choice, prefix có thể là bất kỳ
        lang_code = language.lower().strip() if isinstance(language, str) else "vi"

        if lang_code not in supported:
            settings = await async_get_guild_settings(guild_id)
            avail = ", ".join(f"`{c}`" for c in supported)
            await ctx.send(
                tr(settings, "lang.invalid", code=lang_code, available=avail),
                ephemeral=True
            )
            return

        await async_set_guild_language(guild_id, lang_code)

        # Phản hồi bằng ngôn ngữ vừa được chọn
        lang_display = supported[lang_code]             # e.g. "🇻🇳 Tiếng Việt"
        lang_flag = i18n.translate(lang_code, "lang.flag")
        lang_name = i18n.translate(lang_code, "lang.name")
        response = tr(lang_code, "lang.changed", lang_name=lang_name, lang_flag=lang_flag)
        await ctx.send(response)

    @lang_cmd.error
    async def lang_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, (commands.MissingPermissions, app_commands.MissingPermissions)):
            try:
                settings = await async_get_guild_settings(str(ctx.guild.id))
                await ctx.send(tr(settings, "lang.no_permission"), ephemeral=True)
            except Exception:
                await ctx.send("❌ Bạn không có quyền **Manage Server** để đổi ngôn ngữ!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Language(bot))

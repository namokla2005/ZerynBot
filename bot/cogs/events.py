"""
Cog: Events (v2)
on_member_join / on_member_remove — reads settings from SQLite.
Also caches guild metadata and channels on startup.

Welcome/Goodbye messages are now sent as banner card images (Pillow).
Falls back to a standard embed if card generation fails.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import io
import discord
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import (
    async_get_guild_settings,
    async_is_module_enabled,
    async_cache_guild,
    async_remove_guild,
    async_cache_channels,
    async_cache_roles,
    async_is_blacklisted,
)
from i18n import tr


def hex_to_int(hex_color: str) -> int:
    """Convert '#RRGGBB' string to integer color."""
    try:
        return int(hex_color.lstrip("#"), 16)
    except (ValueError, AttributeError):
        return 0x5865F2


def fmt(template: str, member: discord.Member) -> str:
    """Replace {placeholders} in a message template."""
    return (
        template
        .replace("{user}",         member.mention)
        .replace("{user_name}",    str(member.name))
        .replace("{user_id}",      str(member.id))
        .replace("{server}",       member.guild.name)
        .replace("{member_count}", str(member.guild.member_count))
    )


class Events(commands.Cog):
    """Sự kiện: chào mừng, tạm biệt, cache dữ liệu server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─── Cache on startup ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        import logging
        logger = logging.getLogger("BotV2")
        # ─ Kiểm tra blacklist trước (wrap try/except: đề phòng DB chưa migrate bảng guild_blacklist) ─
        try:
            blacklisted = await async_is_blacklisted(str(guild.id))
        except Exception as e:
            logger.warning(f"[Events] Không kiểm tra được blacklist cho guild {guild.id}: {e}")
            blacklisted = False
        if blacklisted:
            logger.warning(f"[Events] Server ‘{guild.name}’ ({guild.id}) đã bị blacklist. Tự động rời...")
            try:
                # Thông báo trước khi rời (nếu có system channel)
                if guild.system_channel:
                    s = await async_get_guild_settings(str(guild.id))
                    embed = discord.Embed(
                        title=tr(s, "events.blacklist_title"),
                        description=tr(s, "events.blacklist_desc"),
                        color=0xED4245,
                    )
                    await guild.system_channel.send(embed=embed)
            except Exception:
                pass
            await guild.leave()
            return
        await self._cache_guild(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        await async_remove_guild(str(guild.id))

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        await self._cache_guild(after)

    async def _cache_guild(self, guild: discord.Guild):
        icon_url = str(guild.icon.url) if guild.icon else None
        await async_cache_guild(str(guild.id), guild.name, icon_url, guild.member_count)
        channels = [
            {"id": str(ch.id), "name": ch.name, "type": ch.type.value}
            for ch in guild.channels
        ]
        await async_cache_channels(str(guild.id), channels)

        roles = [
            {
                "id": str(r.id),
                "name": r.name,
                "color_hex": str(r.color),
                "position": r.position,
            }
            for r in guild.roles
        ]
        await async_cache_roles(str(guild.id), roles)

    # ─── Welcome ───────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        
        # 1. Auto Roles
        try:
            if await async_is_module_enabled(guild_id, "autoroles"):
                s = await async_get_guild_settings(guild_id)
                if int(s.get("autoroles_enabled", 0)):
                    import json
                    roles_str = s.get("autoroles_bot", "[]") if member.bot else s.get("autoroles_user", "[]")
                    role_ids = json.loads(roles_str)
                    
                    roles_to_add = []
                    for rid in role_ids:
                        r = member.guild.get_role(int(rid))
                        if r:
                            roles_to_add.append(r)
                    
                    if roles_to_add:
                        try:
                            await member.add_roles(*roles_to_add, reason="Auto Roles")
                        except Exception as e:
                            import logging
                            logging.getLogger("BotV2").warning(f"[Events] Auto Roles missing permissions for {member}: {e}")
        except Exception as e:
            import logging
            logging.getLogger("BotV2").error(f"[Events] Auto Roles error: {e}")

        # 2. Welcome Message
        if not await async_is_module_enabled(guild_id, "welcome_goodbye"):
            return

        s = await async_get_guild_settings(guild_id)
        channel_id = s.get("welcome_channel_id")
        if not channel_id:
            return

        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return

        message = fmt(s.get("welcome_message", "{user} đã tham gia!"), member)
        use_embed = bool(s.get("welcome_use_embed", 1))

        if use_embed:
            # Try to generate a banner card image first
            try:
                try:
                    from bot.card_generator import generate_welcome_card
                except (ImportError, ModuleNotFoundError):
                    from card_generator import generate_welcome_card
                buf = await generate_welcome_card(member, s.get("welcome_bg_url"))
                if buf:
                    file = discord.File(fp=buf, filename="welcome.png")
                    await channel.send(
                        content=message,
                        file=file,
                    )
                    return
            except Exception as e:
                import logging
                logging.getLogger("BotV2").warning(f"[Events] Welcome card error: {e}")

            # Fallback: standard embed
            color = hex_to_int(s.get("welcome_embed_color", "#57F287"))
            embed = discord.Embed(
                title=s.get("welcome_embed_title", tr(s, "events.welcome_title")),
                description=message,
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name=tr(s, "events.member_field"), value=str(member.name), inline=True)
            embed.add_field(name=tr(s, "events.id_field"),     value=f"`{member.id}`", inline=True)
            embed.add_field(
                name=tr(s, "events.created_at_field"),
                value=f"<t:{int(member.created_at.timestamp())}:D>",
                inline=True,
            )
            embed.add_field(
                name=tr(s, "events.member_number_field"),
                value=f"**{member.guild.member_count}**",
                inline=True,
            )
            if member.guild.icon:
                embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url)
            await channel.send(embed=embed)
        else:
            await channel.send(message)

    # ─── Goodbye ───────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        if not await async_is_module_enabled(guild_id, "welcome_goodbye"):
            return

        s = await async_get_guild_settings(guild_id)
        channel_id = s.get("goodbye_channel_id")
        if not channel_id:
            return

        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return

        message = fmt(s.get("goodbye_message", "{user_name} đã rời đi!"), member)
        use_embed = bool(s.get("goodbye_use_embed", 1))

        if use_embed:
            # Try to generate a banner card image first
            try:
                try:
                    from bot.card_generator import generate_goodbye_card
                except (ImportError, ModuleNotFoundError):
                    from card_generator import generate_goodbye_card
                buf = await generate_goodbye_card(member, s.get("goodbye_bg_url"))
                if buf:
                    file = discord.File(fp=buf, filename="goodbye.png")
                    await channel.send(
                        content=message,
                        file=file,
                    )
                    return
            except Exception as e:
                import logging
                logging.getLogger("BotV2").warning(f"[Events] Goodbye card error: {e}")

            # Fallback: standard embed
            color = hex_to_int(s.get("goodbye_embed_color", "#ED4245"))
            joined_at = member.joined_at
            duration = tr(s, "events.unknown_duration")
            if joined_at:
                days = (datetime.now(timezone.utc) - joined_at).days
                duration = tr(s, "events.days", days=days) if days > 0 else tr(s, "events.less_than_day")

            roles = [r.mention for r in member.roles if r.name != "@everyone"]
            no_roles_txt = tr(s, "events.no_roles")
            embed = discord.Embed(
                title=s.get("goodbye_embed_title", tr(s, "events.goodbye_title")),
                description=message,
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name=tr(s, "events.id_field"),       value=f"`{member.id}`", inline=True)
            embed.add_field(name=tr(s, "events.duration_field"), value=duration,        inline=True)
            embed.add_field(
                name=f"{tr(s, 'events.roles_field')} ({len(roles)})",
                value=", ".join(roles) if roles else no_roles_txt,
                inline=False,
            )
            if member.guild.icon:
                embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url)
            await channel.send(embed=embed)
        else:
            await channel.send(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))


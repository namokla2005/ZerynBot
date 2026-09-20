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
import time
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
try:
    from emojis import e, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, embed_title, clean_title



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

    # Cache channels/roles là dữ liệu nặng (mỗi guild có thể vài chục kênh/role).
    # Trước đây `on_ready` chạy lại TOÀN BỘ cho mọi guild mỗi lần ready — mà
    # discord.py bắn on_ready lại sau MỖI lần reconnect, nên mất mạng vài lần là
    # hàng trăm lượt ghi SQLite vô ích trên điện thoại.
    FULL_CACHE_TTL = 6 * 3600      # 6 giờ
    CHANNEL_REFRESH_DEBOUNCE = 10  # giây: gộp nhiều event liên tiếp

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_full_cache: dict = {}
        self._last_channel_refresh: dict = {}
        self._last_role_refresh: dict = {}

    # ─── Cache on startup ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            # TTL bên trong sẽ tự chuyển sang chế độ chỉ cập nhật meta nếu guild
            # vừa được cache đầy đủ < 6 giờ trước (trường hợp reconnect).
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
        await self._cache_guild(guild, force=True)  # guild mới → cache đầy đủ ngay

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        await async_remove_guild(str(guild.id))
        self._last_full_cache.pop(str(guild.id), None)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        # Chỉ meta (tên/icon/số member) thay đổi ở event này — không cần ghi lại
        # toàn bộ channels/roles.
        await self._cache_guild(after, meta_only=True)

    # ─── Channel / Role events → cache lại đúng phần vừa đổi ─────────────────
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._refresh_channels(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._refresh_channels(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        await self._refresh_channels(after.guild)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._refresh_roles(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._refresh_roles(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await self._refresh_roles(after.guild)

    async def _refresh_channels(self, guild: discord.Guild) -> None:
        """Cache lại danh sách kênh (debounce 10s/guild để tránh ghi dồn dập)."""
        guild_id = str(guild.id)
        now = time.time()
        if now - self._last_channel_refresh.get(guild_id, 0) < self.CHANNEL_REFRESH_DEBOUNCE:
            return
        self._last_channel_refresh[guild_id] = now
        try:
            await async_cache_channels(guild_id, self._serialize_channels(guild))
        except Exception as e:
            import logging
            logging.getLogger("BotV2").warning(f"[Events] Channel cache refresh error: {e}")

    async def _refresh_roles(self, guild: discord.Guild) -> None:
        """Cache lại danh sách role (debounce 10s/guild)."""
        guild_id = str(guild.id)
        now = time.time()
        if now - self._last_role_refresh.get(guild_id, 0) < self.CHANNEL_REFRESH_DEBOUNCE:
            return
        self._last_role_refresh[guild_id] = now
        try:
            await async_cache_roles(guild_id, self._serialize_roles(guild))
        except Exception as e:
            import logging
            logging.getLogger("BotV2").warning(f"[Events] Role cache refresh error: {e}")

    @staticmethod
    def _serialize_channels(guild: discord.Guild) -> list:
        return [
            {"id": str(ch.id), "name": ch.name, "type": ch.type.value}
            for ch in guild.channels
        ]

    @staticmethod
    def _serialize_roles(guild: discord.Guild) -> list:
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "color_hex": str(r.color),
                "position": r.position,
            }
            for r in guild.roles
        ]

    async def _cache_guild(
        self,
        guild: discord.Guild,
        *,
        force: bool = False,
        meta_only: bool = False,
    ) -> None:
        """Ghi cache guild. `meta_only` chỉ cập nhật bảng guild_meta."""
        guild_id = str(guild.id)
        now = time.time()

        if not meta_only and not force:
            # Đã cache đầy đủ gần đây (vd: reconnect) → chỉ cập nhật meta.
            if now - self._last_full_cache.get(guild_id, 0) < self.FULL_CACHE_TTL:
                meta_only = True

        icon_url = str(guild.icon.url) if guild.icon else None
        await async_cache_guild(guild_id, guild.name, icon_url, guild.member_count)

        if meta_only:
            return

        await async_cache_channels(guild_id, self._serialize_channels(guild))
        await async_cache_roles(guild_id, self._serialize_roles(guild))
        self._last_full_cache[guild_id] = now

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

        try:
            cid = int(channel_id)
        except (ValueError, TypeError):
            return
        channel = member.guild.get_channel(cid)
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
            w_title = s.get("welcome_embed_title")
            if not w_title:
                w_title = embed_title("zb_welcome", tr(s, "events.welcome_title"))
            else:
                w_title = embed_title("zb_welcome", w_title)
            embed = discord.Embed(
                title=w_title,
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

        try:
            cid = int(channel_id)
        except (ValueError, TypeError):
            return
        channel = member.guild.get_channel(cid)
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
            g_title = s.get("goodbye_embed_title")
            if not g_title:
                g_title = embed_title("zb_goodbye", tr(s, "events.goodbye_title"))
            else:
                g_title = embed_title("zb_goodbye", g_title)
            embed = discord.Embed(
                title=g_title,
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


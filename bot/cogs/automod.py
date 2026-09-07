"""
Cog: Automod
"""
import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("BotV2.AutoMod")

import json

import checks
import discord
from discord import app_commands
from discord.ext import commands

import config
from database import (
    async_add_automod_warning,
    async_get_automod_settings,
    async_get_guild_settings,
    async_is_module_enabled,
    async_update_automod_settings,
)
from i18n import tr

try:
    from emojis import clean_title, e, embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import embed_title


# ─── Helpers serialization overwrites (cho Anti-Raid lockdown) ─────────────────
def _ser_overwrite(overwrite):
    """PermissionOverwrite -> {perm: bool} (chỉ các quyền được set)."""
    if overwrite is None:
        return None
    data = {}
    for key, value in overwrite.items():
        if value is not None:
            data[str(key)] = bool(value)
    return data or None


def _deser_overwrite(data):
    if not data:
        return None
    return discord.PermissionOverwrite(**data)

# Extract domains from URLs
URL_PATTERN = re.compile(r'https?://(?:www\.)?([a-zA-Z0-9.-]+)\.[a-zA-Z]{2,}')
DISCORD_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/([a-zA-Z0-9-]+)', re.IGNORECASE)

GLOBAL_SAFE_DOMAINS = {
    "discord.com", "discord.gg", "discordapp.com", "discord.media",
    "youtube.com", "youtu.be",
    "facebook.com", "fb.com", "messenger.com",
    "google.com", "google.com.vn",
    "github.com",
    "tenor.com", "giphy.com",
    "twitter.com", "x.com",
    "instagram.com", "tiktok.com",
    "imgur.com", "reddit.com", "spotify.com",
    "twitch.tv", "steamcommunity.com", "roblox.com"
}

GLOBAL_BLACKLIST_KEYWORDS = [
    "discord-nitro", "free-nitro", "dlscord", "discorcl", "d1scord",
    "steam-nitro", "free-robux", "roblox-free", "steamcommunity-free",
    "discord-gift", "gift-discord", "nitro-gift", "boost-nitro"
]

class Automod(commands.Cog):
    """Bảo vệ server tự động (Automods)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Structure: { guild_id: { user_id: [timestamps] } }
        self.spam_cache = defaultdict(lambda: defaultdict(list))
        # Anti-Raid: { guild_id: [join timestamps] }
        self.join_cache = defaultdict(list)
        # Anti-Nuke: { guild_id: [(timestamp, kind)] }
        self.nuke_cache = defaultdict(list)
        # Guilds đang ở trạng thái lockdown (in-memory; persist qua DB raid_locked)
        self.raid_locked_guilds = set()
        # Lần cuối xử lý nuke để tránh lặp hành động
        self.nuke_last_handled = {}
        # Background task to clean up spam cache every 10 minutes to prevent RAM leak
        self._cache_cleanup_task = asyncio.create_task(self._cleanup_spam_cache())

    async def _cleanup_spam_cache(self):
        """Periodically clear stale spam cache entries to prevent memory leak."""
        while True:
            await asyncio.sleep(600)  # every 10 minutes
            now = time.time()
            for guild_id in list(self.spam_cache.keys()):
                for user_id in list(self.spam_cache[guild_id].keys()):
                    self.spam_cache[guild_id][user_id] = [
                        t for t in self.spam_cache[guild_id][user_id] if now - t < 5
                    ]
                    if not self.spam_cache[guild_id][user_id]:
                        del self.spam_cache[guild_id][user_id]
                if not self.spam_cache[guild_id]:
                    del self.spam_cache[guild_id]

    def cog_unload(self):
        self._cache_cleanup_task.cancel()

    async def _handle_violation(self, message: discord.Message, reason: str, settings: dict):
        guild = message.guild
        member = message.author
        guild_id = str(guild.id)
        s = await async_get_guild_settings(guild_id)
        
        try:
            await message.delete()
        except discord.Forbidden:
            pass # Bot doesn't have manage_messages permission

        warnings = await async_add_automod_warning(guild_id, str(member.id))
        
        if warnings == 1:
            try:
                # Public warning (Short & clean, no bad word exposed)
                embed = discord.Embed(
                    description=tr(s, "automod.warning_desc", user=member.mention),
                    color=config.COLOR_ERROR
                )
                msg = await message.channel.send(content=member.mention, embed=embed)
                
                try:
                    await msg.delete(delay=15.0)
                except Exception:
                    pass
                
                # Send DM with detailed reason
                dm_embed = discord.Embed(
                    title=embed_title("zb_warn", tr(s, "automod.dm_warning_title")),
                    description=tr(s, "automod.dm_warning_desc", guild=guild.name),
                    color=config.COLOR_ERROR
                )
                dm_embed.add_field(name=tr(s, "automod.dm_reason"), value=reason, inline=False)
                original_text = message.content[:1000] + ("..." if len(message.content) > 1000 else "")
                dm_embed.add_field(name=tr(s, "automod.dm_content"), value=f"```text\n{original_text}\n```", inline=False)
                
                try:
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
                    
                self.bot.dispatch('automod_action', guild, member, "Cảnh báo", reason, message.jump_url)
            except discord.Forbidden:
                pass
        else:
            # 2nd or more time: Timeout
            try:
                timeout_mins = int(settings.get("timeout_duration_minutes", 5) or 5)
                until = discord.utils.utcnow() + timedelta(minutes=timeout_mins)
                await member.timeout(until, reason=f"Automod: {reason}")
                
                # Public notification
                embed = discord.Embed(
                    description=tr(s, "automod.timeout_desc", user=member.mention, minutes=timeout_mins),
                    color=config.COLOR_ERROR
                )
                msg = await message.channel.send(embed=embed)
                try:
                    await msg.delete(delay=15.0)
                except Exception:
                    pass
                
                # Send DM
                dm_embed = discord.Embed(
                    title=embed_title("zb_timeout", tr(s, "automod.dm_timeout_title")),
                    description=tr(s, "automod.dm_timeout_desc", guild=guild.name),
                    color=config.COLOR_ERROR
                )
                dm_embed.add_field(name=tr(s, "automod.dm_reason"), value=reason, inline=False)
                dm_embed.add_field(name=tr(s, "automod.dm_penalty"), value=tr(s, "automod.dm_penalty_val", minutes=timeout_mins), inline=False)
                try:
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
                
                self.bot.dispatch('automod_action', guild, member, f"Timeout {timeout_mins} phút", reason, message.jump_url)
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.warning(f"[Automod] Error timeout member: {e}")

            # Send to Log Channel and Ping Role
            log_channel_id = settings.get("log_channel_id")
            if log_channel_id:
                channel = guild.get_channel(int(log_channel_id))
                if channel:
                    notify_role_id = settings.get("notify_role_id")
                    ping_role = f"<@&{notify_role_id}> " if notify_role_id else ""
                    
                    log_embed = discord.Embed(
                        title=embed_title("zb_cat_automod", tr(s, "automod.log_title")),
                        color=config.COLOR_ERROR,
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.add_field(name=tr(s, "automod.log_user"), value=f"{member.mention} (`{member.id}`)", inline=True)
                    log_embed.add_field(name=tr(s, "automod.log_channel"), value=message.channel.mention, inline=True)
                    log_embed.add_field(name=tr(s, "automod.dm_reason"), value=reason, inline=False)
                    log_embed.add_field(name=tr(s, "automod.dm_penalty"), value=f"Timeout {timeout_mins} phút", inline=False)
                    log_embed.add_field(name=tr(s, "automod.dm_content"), value=message.content[:1024] or "[No text content]", inline=False)
                    
                    try:
                        await channel.send(content=tr(s, "automod.log_notify_text", role=ping_role), embed=log_embed)
                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Immune users (Admin/Owner)
        if message.author == message.guild.owner or \
           message.author.guild_permissions.manage_messages or \
           message.author.guild_permissions.administrator:
            return
            
        guild_id = str(message.guild.id)
        if not await async_is_module_enabled(guild_id, "automods"):
            return
            
        settings = await async_get_automod_settings(guild_id)
        
        # Immune roles
        immune_roles = settings.get("immune_roles", [])
        if immune_roles:
            for role in message.author.roles:
                if str(role.id) in immune_roles:
                    return
                    
        content = message.content.lower()

        # 1. Spam check (5 messages in 5 seconds)
        spam_allowed_channels = settings.get("spam_allowed_channels", [])
        is_spam_allowed = str(message.channel.id) in spam_allowed_channels
        
        if settings.get("spam_enabled") and not is_spam_allowed:
            user_id = str(message.author.id)
            now = time.time()
            timestamps = self.spam_cache[guild_id][user_id]
            
            # Remove old timestamps (older than 5 seconds)
            timestamps = [t for t in timestamps if now - t < 5]
            timestamps.append(now)
            self.spam_cache[guild_id][user_id] = timestamps
            
            if len(timestamps) > 5:
                # Trigger spam
                self.spam_cache[guild_id][user_id] = [] # Reset to prevent loop
                return await self._handle_violation(message, "Spam (Gửi tin nhắn quá nhanh)", settings)

        # 2. Bad words check
        if settings.get("bad_words_enabled"):
            bad_words = settings.get("bad_words", [])
            for word in bad_words:
                if word.lower() in content:
                    return await self._handle_violation(message, f"Sử dụng từ cấm: {word}", settings)

        # 3. Links check
        if settings.get("links_enabled") and ("http://" in content or "https://" in content):
            whitelist = settings.get("whitelist_links", [])
            domains = URL_PATTERN.findall(content)
            
            violation_reason = None
            for domain in domains:
                domain_lower = domain.lower()

                # 3a. Check Whitelist (User + Global)
                is_whitelisted = False
                for w_link in whitelist:
                    w_link = w_link.lower().replace("https://", "").replace("http://", "").split("/")[0]
                    if domain_lower == w_link or domain_lower.endswith(f".{w_link}"):
                        is_whitelisted = True
                        break

                if not is_whitelisted:
                    for safe_domain in GLOBAL_SAFE_DOMAINS:
                        if domain_lower == safe_domain or domain_lower.endswith(f".{safe_domain}"):
                            is_whitelisted = True
                            break

                if is_whitelisted:
                    continue  # This link is safe, check next one

                # 3b. Check Global Blacklist (Fake/Scam) — highest priority
                for bad_kw in GLOBAL_BLACKLIST_KEYWORDS:
                    if bad_kw in domain_lower:
                        violation_reason = f"Gửi link giả mạo/lừa đảo: {domain}"
                        break

                if not violation_reason:
                    # 3c. Block unknown links
                    violation_reason = f"Gửi link không rõ nguồn gốc: {domain}"
                
                break  # Found a violating link, stop checking others

            if violation_reason:
                return await self._handle_violation(message, violation_reason, settings)

        # 4. Anti-Invite links check
        if settings.get("anti_invite_enabled"):
            invite_matches = DISCORD_INVITE_PATTERN.findall(message.content)
            if invite_matches:
                return await self._handle_violation(message, "Gửi link mời Discord server khác (Anti-Invite)", settings)

        # 5. Anti-CAPS check
        if settings.get("anti_caps_enabled") and len(message.content) > 10:
            letters = [c for c in message.content if c.isalpha()]
            if letters:
                uppercase_count = sum(1 for c in letters if c.isupper())
                ratio = uppercase_count / len(letters)
                if ratio > 0.7:
                    return await self._handle_violation(message, f"Spam chữ IN HOA ({int(ratio*100)}% Caps)", settings)

        # 6. Anti-Mention spam check
        if settings.get("anti_mentions_enabled"):
            max_mentions = int(settings.get("max_mentions", 5) or 5)
            total_mentions = len(message.mentions) + len(message.role_mentions)
            if total_mentions > max_mentions:
                return await self._handle_violation(message, f"Tag quá nhiều người/role ({total_mentions}/{max_mentions} tags)", settings)

    # ══════════════════════════════════════════════════════════════════════════
    # ─── ANTI-RAID (Lockdown khi join ồ ạt) ───────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not member.guild:
            return
        guild_id = str(member.guild.id)
        if not await async_is_module_enabled(guild_id, "automods"):
            return
        settings = await async_get_automod_settings(guild_id)
        if not settings.get("anti_raid_enabled"):
            return

        now = time.time()
        cache = self.join_cache[guild_id]
        cache.append(now)
        window = 60  # cửa sổ 60 giây
        self.join_cache[guild_id] = [t for t in cache if now - t <= window]

        threshold = int(settings.get("raid_join_per_window", 5) or 5)
        if len(self.join_cache[guild_id]) >= threshold:
            if guild_id in self.raid_locked_guilds:
                return
            await self._trigger_raid_lockdown(member.guild, settings, len(self.join_cache[guild_id]))

    async def _trigger_raid_lockdown(self, guild: discord.Guild, settings: dict, count: int):
        """Khi phát hiện join ồ ạt: thực hiện raid_action và ghi log."""
        guild_id = str(guild.id)
        action = settings.get("raid_action", "lockdown")

        if action == "verify":
            # Tự bật Verify Gate để chặn thành viên mới
            try:
                from database import async_upsert_verify_settings
                await async_upsert_verify_settings(guild_id, enabled=1, hide_channels=1)
            except Exception as exc:
                logger.warning(f"[AutoMod] raid verify action error: {exc}")

        # Luôn thực hiện lockdown cơ bản: chặn @everyone gửi tin
        snapshot = await self._lockdown_guild(guild)
        self.raid_locked_guilds.add(guild_id)
        await async_update_automod_settings(guild_id, raid_locked=1, raid_snapshot=snapshot)

        await self._log_automod(
            guild_id, settings, "Anti-Raid",
            f"🚨 Phát hiện **{count} lượt join** trong 60 giây.\n"
            f"**Hành động:** Lockdown (chặn @everyone gửi tin). Dùng `/automods raidunlock` để mở lại.",
        )

    async def _lockdown_guild(self, guild: discord.Guild) -> str:
        """Snapshot overwrites của @everyone rồi chặn gửi tin trên mọi kênh text."""
        guild_id = str(guild.id)
        def_role = guild.default_role
        snapshot = []
        for channel in guild.text_channels:
            try:
                current = channel.overwrites_for(def_role)
                snapshot.append({
                    "channel_id": str(channel.id),
                    "overwrite": _ser_overwrite(current),
                })
                await channel.set_permissions(def_role, send_messages=False, reason="Anti-Raid lockdown")
            except discord.Forbidden:
                logger.warning(f"[AutoMod] Missing perms to lockdown {channel.name}")
            except Exception as exc:
                logger.warning(f"[AutoMod] lockdown error on {channel.name}: {exc}")
        return json.dumps(snapshot, ensure_ascii=False)

    async def _unlock_guild(self, guild: discord.Guild, settings: dict) -> int:
        """Khôi phục overwrites của @everyone từ snapshot đã lưu."""
        guild_id = str(guild.id)
        try:
            snapshot = json.loads(settings.get("raid_snapshot") or "[]")
        except (json.JSONDecodeError, TypeError):
            snapshot = []
        def_role = guild.default_role
        restored = 0
        for entry in snapshot:
            channel = guild.get_channel(int(entry.get("channel_id", 0)))
            if channel is None:
                continue
            try:
                original = _deser_overwrite(entry.get("overwrite"))
                await channel.set_permissions(def_role, overwrite=original, reason="Anti-Raid unlock")
                restored += 1
            except discord.Forbidden:
                logger.warning(f"[AutoMod] Missing perms to unlock {channel.name}")
            except Exception as exc:
                logger.warning(f"[AutoMod] unlock error on {channel.name}: {exc}")
        self.raid_locked_guilds.discard(guild_id)
        await async_update_automod_settings(guild_id, raid_locked=0, raid_snapshot="[]")
        return restored

    # ══════════════════════════════════════════════════════════════════════════
    # ─── ANTI-NUKE (Chặn xoá role/kênh hàng loạt) ─────────────────────────────
    # ══════════════════════════════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._on_delete_event(channel.guild, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._on_delete_event(role.guild, "role_delete")

    async def _on_delete_event(self, guild: discord.Guild, kind: str):
        if not guild:
            return
        guild_id = str(guild.id)
        if not await async_is_module_enabled(guild_id, "automods"):
            return
        settings = await async_get_automod_settings(guild_id)
        if not settings.get("anti_nuke_enabled"):
            return

        now = time.time()
        cache = self.nuke_cache[guild_id]
        cache.append((now, kind))
        self.nuke_cache[guild_id] = [(t, k) for t, k in cache if now - t <= 10]

        threshold = 3  # xoá >= 3 object trong 10 giây
        if len(self.nuke_cache[guild_id]) >= threshold:
            last = self.nuke_last_handled.get(guild_id, 0)
            if now - last < 20:  # cooldown bảo vệ để không lặp hành động
                return
            self.nuke_last_handled[guild_id] = now
            await self._handle_nuke(guild, settings, len(self.nuke_cache[guild_id]))

    async def _handle_nuke(self, guild: discord.Guild, settings: dict, count: int):
        guild_id = str(guild.id)
        nuke_actions = settings.get("nuke_actions") or ["channel_delete", "role_delete", "guild_update"]

        actor = await self._find_nuke_actor(guild)
        desc = f"💥 Phát hiện **{count} object** bị xoá trong 10 giây (kênh/vai trò)."

        if actor:
            desc += f"\n**Thủ phạm:** {actor.mention} (`{actor.id}`)"
            try:
                await guild.ban(actor, reason=f"Anti-Nuke: mass {'/'.join(nuke_actions)}", delete_message_seconds=0)
                desc += "\n**Hành động:** ⛔ Đã ban."
            except discord.Forbidden:
                try:
                    await actor.timeout(timedelta(hours=24), reason="Anti-Nuke: mass deletion")
                    desc += "\n**Hành động:** ⏰ Đã timeout 24h (thiếu quyền ban)."
                except discord.Forbidden:
                    desc += "\n**Hành động:** ⚠️ Thiếu quyền ban/timeout."
            except Exception as exc:
                logger.warning(f"[AutoMod] nuke ban error: {exc}")
                desc += "\n**Hành động:** ⚠️ Lỗi khi ban."

        # Bảo vệ: chuyển sang lockdown để chặn thiệt hại tiếp
        if guild_id not in self.raid_locked_guilds:
            try:
                snapshot = await self._lockdown_guild(guild)
                self.raid_locked_guilds.add(guild_id)
                await async_update_automod_settings(guild_id, raid_locked=1, raid_snapshot=snapshot)
                desc += "\n**Bảo vệ:** 🔒 Đã chuyển sang lockdown. Dùng `/automods raidunlock` để mở lại."
            except Exception as exc:
                logger.warning(f"[AutoMod] nuke lockdown error: {exc}")

        await self._log_automod(guild_id, settings, "Anti-Nuke", desc)

    async def _find_nuke_actor(self, guild: discord.Guild) -> discord.User | None:
        """Tìm người xoá gần nhất từ audit log (kênh/vai trò)."""
        now = discord.utils.utcnow()
        for action in (discord.AuditLogAction.channel_delete, discord.AuditLogAction.role_delete):
            try:
                async for entry in guild.audit_logs(limit=5, action=action):
                    if entry.user and not entry.user.bot and entry.created_at and \
                       (now - entry.created_at).total_seconds() < 30:
                        return entry.user
            except discord.Forbidden:
                continue
            except Exception as exc:
                logger.warning(f"[AutoMod] audit_log fetch error: {exc}")
        return None

    async def _log_automod(self, guild_id: str, settings: dict, title: str, desc: str):
        log_channel_id = settings.get("log_channel_id")
        if not log_channel_id:
            return
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        channel = guild.get_channel(int(log_channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title=embed_title("zb_cat_automod", f"🛡️ {title}"),
            description=desc,
            color=config.COLOR_ERROR,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    # ─── Commands ──────────────────────────────────────────────────────────────

    @commands.hybrid_group(name="automods", description="Quản lý hệ thống tự động bảo vệ (Automods)")
    @app_commands.default_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def automods(self, ctx: commands.Context):
        pass

    @automods.command(name="show", description="Xem cấu hình Automods hiện tại")
    async def show(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        is_active = await async_is_module_enabled(guild_id, "automods")
        settings = await async_get_automod_settings(guild_id)
        s = await async_get_guild_settings(guild_id)
        
        status_str = tr(s, "automod.active") if is_active else tr(s, "automod.inactive")
        
        embed = discord.Embed(
            title=embed_title("zb_cat_automod", tr(s, "automod.show_title", guild=ctx.guild.name)),
            description=tr(s, "automod.show_desc", status=status_str),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Modules
        on_txt = tr(s, "automod.on")
        off_txt = tr(s, "automod.off")
        spam = on_txt if settings.get("spam_enabled") else off_txt
        bw = on_txt if settings.get("bad_words_enabled") else off_txt
        lnk = on_txt if settings.get("links_enabled") else off_txt
        inv = on_txt if settings.get("anti_invite_enabled") else off_txt
        caps = on_txt if settings.get("anti_caps_enabled") else off_txt
        ment = on_txt if settings.get("anti_mentions_enabled") else off_txt
        raid = on_txt if settings.get("anti_raid_enabled") else off_txt
        nuke = on_txt if settings.get("anti_nuke_enabled") else off_txt
        raid_action = settings.get("raid_action", "lockdown")

        embed.add_field(
            name=tr(s, "automod.sec_features"),
            value=f"**{tr(s, 'automod.feat_spam')}:** {spam} | **{tr(s, 'automod.feat_badwords')}:** {bw} | **{tr(s, 'automod.feat_links')}:** {lnk}\n"
                  f"**{tr(s, 'automod.feat_invite')}:** {inv} | **{tr(s, 'automod.feat_caps')}:** {caps} | **{tr(s, 'automod.feat_mentions')}:** {ment}\n"
                  f"**🚨 Anti-Raid:** {raid} | **💥 Anti-Nuke:** {nuke}",
            inline=False
        )

        if settings.get("anti_raid_enabled") or settings.get("anti_nuke_enabled"):
            raid_locked = settings.get("raid_locked")
            embed.add_field(
                name="🚨 Bảo vệ Server",
                value=f"**Raid Action:** `{raid_action}` | **Ngưỡng Join:** {settings.get('raid_join_per_window', 5)}/60s\n"
                      f"**Trạng thái:** {'🔒 Đang lockdown' if raid_locked else '🟢 Bình thường'}",
                inline=False,
            )
        
        # Filters
        bw_list = settings.get("bad_words", [])
        bl_list = settings.get("blacklist_links", [])
        wl_list = settings.get("whitelist_links", [])
        
        embed.add_field(
            name=tr(s, "automod.sec_filters"),
            value=f"{tr(s, 'automod.bad_words_cnt', cnt=len(bw_list))}\n"
                  f"{tr(s, 'automod.bl_links_cnt', cnt=len(bl_list))}\n"
                  f"{tr(s, 'automod.wl_links_cnt', cnt=len(wl_list))}",
            inline=False
        )
        
        # Logs
        none_txt = tr(s, "automod.none")
        log_ch = f"<#{settings.get('log_channel_id')}>" if settings.get("log_channel_id") else none_txt
        notif_role = f"<@&{settings.get('notify_role_id')}>" if settings.get("notify_role_id") else none_txt
        
        embed.add_field(
            name=tr(s, "automod.sec_notif"),
            value=f"{tr(s, 'automod.log_ch_label', ch=log_ch)}\n"
                  f"{tr(s, 'automod.role_tag_label', role=notif_role)}",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @automods.command(name="raidlock", description="Khoá server (lockdown) để chặn raid/nuke")
    async def raidlock(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        settings = await async_get_automod_settings(guild_id)

        if guild_id in self.raid_locked_guilds or settings.get("raid_locked"):
            await ctx.send("ℹ️ Server đang ở trạng thái lockdown.", ephemeral=True)
            return

        snapshot = await self._lockdown_guild(ctx.guild)
        self.raid_locked_guilds.add(guild_id)
        await async_update_automod_settings(guild_id, raid_locked=1, raid_snapshot=snapshot)
        await ctx.send("🔒 Đã chuyển server sang **lockdown** (chặn @everyone gửi tin). Dùng `/automods raidunlock` để mở lại.", ephemeral=True)

    @automods.command(name="raidunlock", description="Mở khóa server sau lockdown, khôi phục overwrites")
    async def raidunlock(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        settings = await async_get_automod_settings(guild_id)

        restored = await self._unlock_guild(ctx.guild, settings)
        await ctx.send(
            f"🔓 Đã mở khoá server. Khôi phục overwrite cho {restored} kênh.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Automod(bot))


"""
Cog: Automod
"""
import sys, os, time, re
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import (
    async_is_module_enabled,
    async_get_automod_settings,
    async_add_automod_warning,
    set_module
)
from bot import checks

# Extract domains from URLs
URL_PATTERN = re.compile(r'https?://(?:www\.)?([a-zA-Z0-9.-]+)\.[a-zA-Z]{2,}')

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
        
        try:
            await message.delete()
        except discord.Forbidden:
            pass # Bot doesn't have manage_messages permission

        warnings = await async_add_automod_warning(guild_id, str(member.id))
        
        if warnings == 1:
            try:
                # Public warning (Short & clean, no bad word exposed)
                embed = discord.Embed(
                    description=f"⚠️ {member.mention}, bạn đã vi phạm quy định của máy chủ. Lần vi phạm tiếp theo sẽ bị **Timeout**.",
                    color=config.COLOR_ERROR
                )
                msg = await message.channel.send(content=member.mention, embed=embed)
                
                try:
                    await msg.delete(delay=15.0)
                except:
                    pass
                
                # Send DM with detailed reason
                dm_embed = discord.Embed(
                    title="⚠️ Cảnh báo Automod",
                    description=f"Bạn đã vi phạm nội quy tại server **{guild.name}**.",
                    color=config.COLOR_ERROR
                )
                dm_embed.add_field(name="Lý do", value=reason, inline=False)
                original_text = message.content[:1000] + ("..." if len(message.content) > 1000 else "")
                dm_embed.add_field(name="Nội dung vi phạm", value=f"```text\n{original_text}\n```", inline=False)
                
                try:
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
            except discord.Forbidden:
                pass
        else:
            # 2nd or more time: Timeout for 5 mins
            try:
                until = discord.utils.utcnow() + timedelta(minutes=5)
                await member.timeout(until, reason=f"Automod: {reason}")
                
                # Public notification
                embed = discord.Embed(
                    description=f"⛔ {member.mention} đã bị **Timeout 5 phút** do liên tục vi phạm quy định.",
                    color=config.COLOR_ERROR
                )
                msg = await message.channel.send(embed=embed)
                try:
                    await msg.delete(delay=15.0)
                except:
                    pass
                
                # Send DM
                dm_embed = discord.Embed(
                    title="⛔ Hình phạt Automod",
                    description=f"Bạn đã bị Timeout tại server **{guild.name}**.",
                    color=config.COLOR_ERROR
                )
                dm_embed.add_field(name="Lý do", value=reason, inline=False)
                dm_embed.add_field(name="Hình phạt", value="Bị cấm chat & câm voice trong 5 phút.", inline=False)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[Automod] Error timeout member: {e}")

            # Send to Log Channel and Ping Role
            log_channel_id = settings.get("log_channel_id")
            if log_channel_id:
                channel = guild.get_channel(int(log_channel_id))
                if channel:
                    notify_role_id = settings.get("notify_role_id")
                    ping_text = f"<@&{notify_role_id}> " if notify_role_id else ""
                    
                    log_embed = discord.Embed(
                        title="🛡️ Automod Kích Hoạt",
                        color=config.COLOR_ERROR,
                        timestamp=datetime.now(timezone.utc)
                    )
                    log_embed.add_field(name="Người dùng", value=f"{member.mention} (`{member.id}`)", inline=True)
                    log_embed.add_field(name="Kênh", value=message.channel.mention, inline=True)
                    log_embed.add_field(name="Lý do", value=reason, inline=False)
                    log_embed.add_field(name="Hình phạt", value="Timeout 5 phút", inline=False)
                    log_embed.add_field(name="Nội dung tin nhắn", value=message.content[:1024] or "[Không có nội dung text]", inline=False)
                    
                    try:
                        await channel.send(content=f"{ping_text}Người dùng vi phạm quy định!", embed=log_embed)
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
        
        status_str = "🟢 **Đang Hoạt Động**" if is_active else "🔴 **Đã Tắt**"
        
        embed = discord.Embed(
            title=f"🛡️ Automods — {ctx.guild.name}",
            description=f"Trạng thái: {status_str}\n*(Để tuỳ chỉnh chi tiết, vui lòng dùng Dashboard)*",
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Modules
        spam = "✅ Bật" if settings.get("spam_enabled") else "❌ Tắt"
        bw = "✅ Bật" if settings.get("bad_words_enabled") else "❌ Tắt"
        lnk = "✅ Bật" if settings.get("links_enabled") else "❌ Tắt"
        
        embed.add_field(
            name="⚙️ Tính Năng",
            value=f"**Chống Spam:** {spam}\n**Lọc Từ Cấm:** {bw}\n**Lọc Link Fake:** {lnk}",
            inline=False
        )
        
        # Filters
        bw_list = settings.get("bad_words", [])
        bl_list = settings.get("blacklist_links", [])
        wl_list = settings.get("whitelist_links", [])
        
        embed.add_field(
            name="📝 Bộ Lọc",
            value=f"**Từ cấm:** {len(bw_list)} từ\n**Blacklist Link:** {len(bl_list)} link\n**Whitelist Link:** {len(wl_list)} link",
            inline=False
        )
        
        # Logs
        log_ch = f"<#{settings.get('log_channel_id')}>" if settings.get("log_channel_id") else "*Không có*"
        notif_role = f"<@&{settings.get('notify_role_id')}>" if settings.get("notify_role_id") else "*Không có*"
        
        embed.add_field(
            name="📢 Thông Báo",
            value=f"**Kênh Log:** {log_ch}\n**Role Tag (Lần 2):** {notif_role}",
            inline=False
        )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Automod(bot))

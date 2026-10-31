"""
Cog: Automod
"""
import asyncio
import logging
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

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
    from bot.emojis import clean_title, e, embed_title


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
URL_PATTERN = re.compile(r'https?://((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})')
# Domain trần (không scheme) — Discord tự linkify `discord-nitro.com/claim`,
# nên automod cũng phải thấy nó. Lookbehind @ để không bắt domain trong email.
BARE_DOMAIN_PATTERN = re.compile(r'(?<![\w@])((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})(?![\w])')
# URL đầy đủ (gồm path/query) để bóc hostname bằng urlsplit và loại khỏi
# vùng quét domain trần; nếu không, `.../image.png` bị coi là domain `.png`.
URL_FULL_PATTERN = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
# Domain trần có thể kèm path (`example.com/image.png`): chỉ lấy group 1 làm host,
# nuốt luôn path để filename trong path không bị quét thành domain riêng.
BARE_URL_PATTERN = re.compile(
    r'(?<![\w@])((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,})(?:/[^\s<>"\']*)?',
    re.IGNORECASE,
)
# Đuôi file phổ biến cũng là TLD hợp lệ (.png, .zip, .mov, .md...). Chỉ dùng để
# bỏ qua domain trần trông như filename; URL có scheme và blacklist/global keyword
# vẫn được xét trước.
FILE_EXTENSIONS = frozenset({
    "png", "jpg", "jpeg", "jfif", "gif", "webp", "apng", "avif", "jxl", "bmp",
    "svg", "ico", "tif", "tiff", "heic", "mp4", "mov", "webm", "mkv", "avi",
    "m4v", "wmv", "flv", "mpeg", "mpg", "3gp", "3g2", "mp3", "m4a", "m4b",
    "m4p", "wav", "flac", "ogg", "opus", "aac", "wma", "pdf", "doc", "docx",
    "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "csv", "md", "json", "xml",
    "html", "css", "js", "ts", "zip", "rar", "7z", "tar", "gz", "bz2", "xz",
    "iso", "img", "bin", "apk", "exe", "msi", "dmg", "pkg", "deb", "rpm",
    "py", "java", "c", "cpp", "h", "cs", "go", "rs", "php", "rb", "sh", "bat",
    "ps1", "vtt", "srt", "ass", "sub", "epub", "mobi", "azw3", "ttf", "otf",
    "woff", "woff2",
})
DISCORD_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/([a-zA-Z0-9-]+)', re.IGNORECASE)

GLOBAL_SAFE_DOMAINS = {
    "discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discord.media",
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

# ─── Chuẩn hóa văn bản trước khi so khớp (chống bypass bằng Unicode) ──────────
_ZERO_WIDTH_RE = re.compile(r"[​‌‍⁠﻿­]")


def normalize_scan_text(text: str) -> str:
    """NFKC -> bỏ zero-width -> folding ký tự giả Latin -> lower.

    Ba lớp bypass khác nhau, mỗi lớp cần một bước riêng:
      - zero-width (`free​nitro`) -> bị cắt bằng _ZERO_WIDTH_RE.
      - fullwidth/ligature (`ｎｉｔｒｏ`) -> NFKC quy về ASCII.
      - homoglyph Cyrillic (`dљscord`) -> KHÔNG được NFKC xử lý (NFKC không phải
        bảng confusables), nên cần HOSTILE_LOOKALIKES riêng. Chỉ cần một bảng nhỏ các
        ký tự hay dùng trong từ khóa lừa đảo, đủ cho 'discord-nitro'/'freenitro'.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = unicodedata.normalize("NFKD", text)
    # Bỏ dấu combining: `free\u0301-nitro` phải khớp `free-nitro`.
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _ZERO_WIDTH_RE.sub("", text).lower()
    return text.translate(HOSTILE_LOOKALIKES)


# Bảng tra ký tự ngoài Latin bị nhìn nhầm thành chữ Latin hay dùng trong từ khóa scam.
HOSTILE_LOOKALIKES = {ord(c): ord(t) for c, t in [
    ("а", "a"), ("б", "b"), ("с", "c"), ("д", "d"), ("е", "e"), ("f", "f"),
    ("ɡ", "g"), ("і", "i"), ("ј", "j"), ("к", "k"), ("м", "m"), ("о", "o"),
    ("р", "p"), ("т", "t"), ("s", "s"), ("v", "v"), ("ѕ", "s"), ("х", "x"),
    ("у", "y"), ("ԁ", "d"), ("ԏ", "y"), ("օ", "o"), ("ɑ", "a"), ("σ", "o"),
    ("‐", "-"), ("‑", "-"), ("‒", "-"), ("–", "-"), ("—", "-"), ("―", "-"),
    ("−", "-"), ("。", "."), ("．", "."),
]}


def message_scan_text(message) -> str:
    """Mọi phần văn bản của message mà automod PHẢI xét tới.

    Trước đây chỉ `message.content.lower()` được dùng, nên nhét link lừa đảo vào embed
    (title/description/field/footer/author/url) hoặc gửi sticker có tên chứa từ khóa là
    qua mặt hoàn toàn mà không cần lách Unicode.
    """
    parts = [message.content or ""]
    for emb in getattr(message, "embeds", None) or []:
        parts += [getattr(emb, "title", None) or "", getattr(emb, "description", None) or "",
                  getattr(emb, "url", None) or ""]
        for field in getattr(emb, "fields", None) or []:
            parts += [getattr(field, "name", None) or "", getattr(field, "value", None) or ""]
        footer = getattr(emb, "footer", None)
        if footer is not None:
            parts.append(getattr(footer, "text", None) or "")
        author = getattr(emb, "author", None)
        if author is not None:
            parts.append(getattr(author, "name", None) or "")
    for st in getattr(message, "stickers", None) or []:
        parts += [getattr(st, "name", None) or "", getattr(st, "description", None) or ""]
    poll = getattr(message, "poll", None)
    if poll is not None:
        parts.append(getattr(poll, "question", None) or "")
        for answer in getattr(poll, "answers", None) or []:
            parts.append(getattr(answer, "text", None) or "")
    for att in getattr(message, "attachments", None) or []:
        parts.append(getattr(att, "url", None) or "")
    return normalize_scan_text(chr(10).join(parts))


def _looks_like_filename(domain: str) -> bool:
    """`image.png` / `file.zip` trông như domain vì đuôi file cũng là TLD."""
    return "." in domain and domain.rsplit(".", 1)[-1].lower() in FILE_EXTENSIONS


def extract_domains(text: str) -> list[tuple[str, str]]:
    """Trả [(hostname, "url"|"bare")] — parse host, KHÔNG quét filename trong path.

    - URL có scheme: dùng urlsplit.hostname để xử lý cả userinfo/port
      (`https://discord.com@evil.example` phải là evil.example, không phải discord.com).
    - Domain trần: BARE_URL_PATTERN nuốt luôn path, nên `example.com/image.png`
      chỉ trả example.com; `.../image.png` không bao giờ thành domain riêng.
    """
    text = text or ""
    found: list[tuple[str, str]] = []

    for match in URL_FULL_PATTERN.finditer(text):
        raw = match.group(0).rstrip(".,;:!?)]}'\"")
        try:
            host = urlsplit(raw).hostname
        except ValueError:
            host = None
        if host:
            found.append((host.lower().rstrip("."), "url"))

    bare_text = URL_FULL_PATTERN.sub(" ", text)
    for match in BARE_URL_PATTERN.finditer(bare_text):
        host = (match.group(1) or "").lower().rstrip(".")
        if host:
            found.append((host, "bare"))

    # Giữ source "url" nếu cùng host xuất hiện cả dạng URL lẫn bare.
    deduped: dict[str, str] = {}
    for host, source in found:
        if host not in deduped or (source == "url" and deduped[host] == "bare"):
            deduped[host] = source
    return list(deduped.items())


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

    async def _reason_lang(self, guild) -> dict:
        """Guild settings — thu duyet duy nhat mang key `language`.

        `settings` cua automod (async_get_automod_settings) KHONG co `language`, nen
        dung no trong tr() khien ngon ngu cua server bi bo qua im lang — server en/zh
        nhan mai ly do tieng Viet.

        PHAI nuot loi: day nam tren duong xu ly vi pham, mot loi DB ném exception ra
        se lam chet toan bo quy tắc automod cua tin nhan do (bo loc bi mu).
        """
        if guild is None:
            return {}
        try:
            return await async_get_guild_settings(str(guild.id))
        except Exception:
            return {}

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
                    
                # P2: dispatch KEY ổn định ("warn") thay vì chuỗi đã dịch — trước đây
                # stats.py phải đoán ngôn ngữ ("Cảnh báo"/"Warn"/"禁言"...) nên thêm
                # locale mới là biểu đồ thống kê vỡ.
                self.bot.dispatch('automod_action', guild, member, "warn", reason, message.jump_url)
            except discord.Forbidden:
                pass
        else:
            # 2nd or more time: Timeout
            # Parse AN TOÀN trước khối try: nếu `timeout_duration_minutes` bị đặt thành
            # chuỗi rác thì `timeout_mins` sẽ không được gán, và khối log bên dưới
            # (dùng f"Timeout {timeout_mins} phút") sẽ nổ NameError.
            try:
                timeout_mins = int(settings.get("timeout_duration_minutes", 5) or 5)
            except (TypeError, ValueError):
                timeout_mins = 5
            try:
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
                
                self.bot.dispatch('automod_action', guild, member, "timeout", reason, message.jump_url)
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.warning(f"[Automod] Error timeout member: {e}")

            # Send to Log Channel and Ping Role
            log_channel_id = settings.get("log_channel_id")
            if log_channel_id:
                try:
                    channel = guild.get_channel(int(log_channel_id))
                except (TypeError, ValueError):
                    channel = None
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
                    log_embed.add_field(name=tr(s, "automod.dm_penalty"), value=tr(s, "automod.timeout_phut", timeout_mins=timeout_mins), inline=False)
                    log_embed.add_field(name=tr(s, "automod.dm_content"), value=message.content[:1024] or "[No text content]", inline=False)
                    
                    try:
                        await channel.send(content=tr(s, "automod.log_notify_text", role=ping_role), embed=log_embed)
                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        settings = await self._automod_gate(message)
        if settings is None:
            return

        # `guild_id` duoc nhanh spam ben duoi dung de danh chiem spam_cache; trc day no
        # duoc gan o phan "immune users" da duoc _automod_gate thau the — xoa trung
        # khai bao ma khong di chuyen gan la NameError moi tin nhan trong kenh co spam.
        guild_id = str(message.guild.id)
        content = message_scan_text(message)

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
                return await self._handle_violation(message, tr(await self._reason_lang(message.guild), "automod.spam_gui_tin_nhan_qua"), settings)

        if await self._check_text_rules(message, settings, content):
            return


        # 5. Anti-CAPS check
        if settings.get("anti_caps_enabled") and len(message.content) > 10:
            letters = [c for c in message.content if c.isalpha()]
            if letters:
                uppercase_count = sum(1 for c in letters if c.isupper())
                ratio = uppercase_count / len(letters)
                if ratio > 0.7:
                    return await self._handle_violation(message, tr(await self._reason_lang(message.guild), "automod.spam_chu_in_hoa_caps", p1=int(ratio * 100)), settings)

        # 6. Anti-Mention spam check
        if settings.get("anti_mentions_enabled"):
            max_mentions = int(settings.get("max_mentions", 5) or 5)
            total_mentions = len(message.mentions) + len(message.role_mentions)
            if total_mentions > max_mentions:
                return await self._handle_violation(message, tr(await self._reason_lang(message.guild), "automod.tag_qua_nhieu_nguoi_role", total_mentions=total_mentions, max_mentions=max_mentions), settings)

    async def _automod_gate(self, message: discord.Message):
        """Trả về settings nếu message này thuộc diện automod phải xét, ngược lại None.

        Gom chung cho `on_message` và `on_message_edit` để hai đường không thể lệch
        nhau (free pass cho tin nhắn đã sửa, hoặc quên bỏ qua admin/m kênh khác).
        """
        if message.author.bot or not message.guild:
            return None
        author = message.author
        is_member = isinstance(author, discord.Member)
        if is_member:
            if (author == message.guild.owner
                    or author.guild_permissions.manage_messages
                    or author.guild_permissions.administrator):
                return None
        guild_id = str(message.guild.id)
        if not await async_is_module_enabled(guild_id, "automods"):
            return None
        settings = await async_get_automod_settings(guild_id)
        immune_roles = settings.get("immune_roles", [])
        if immune_roles and is_member:
            for role in author.roles:
                if str(role.id) in immune_roles:
                    return None
        return settings

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Luật văn bản cũng phải chạy khi EDIT nội dung.

        Before: chỉ có `on_message`, nênmodus operandi thực tế của scam là gửi một tin
        vô hại rồi edit thành link lừa đảo — automod không bao giờ nhìn thấy gì.
        """
        if after.guild is None:
            return
        same_text = normalize_scan_text(before.content or "") == normalize_scan_text(after.content or "")
        if same_text and not after.embeds and not after.stickers:
            return
        settings = await self._automod_gate(after)
        if settings is None:
            return
        if await self._check_text_rules(after, settings, message_scan_text(after)):
            return

        # Edit cũng phải chịu anti-caps/anti-mentions (spam không đếm lại để tránh
        # một tin nhắn bị sửa nhiều lần thành spam oan).
        if settings.get("anti_caps_enabled") and len(after.content) > 10:
            letters = [c for c in after.content if c.isalpha()]
            if letters:
                ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if ratio > 0.7:
                    await self._handle_violation(
                        after,
                        tr(await self._reason_lang(after.guild), "automod.spam_chu_in_hoa_caps", p1=int(ratio * 100)),
                        settings,
                    )
                    return
        if settings.get("anti_mentions_enabled"):
            max_mentions = int(settings.get("max_mentions", 5) or 5)
            total_mentions = len(after.mentions) + len(after.role_mentions)
            if total_mentions > max_mentions:
                await self._handle_violation(
                    after,
                    tr(await self._reason_lang(after.guild), "automod.tag_qua_nhieu_nguoi_role", total_mentions=total_mentions, max_mentions=max_mentions),
                    settings,
                )
                return

    async def _check_text_rules(self, message: discord.Message, settings: dict, content: str) -> bool:
        """Chạy các luật dựa trên NỘI DUNG VĂN BẢN. Trả về True nếu đã xử lý vi phạm.

        Tách riêng để `on_message` và `on_message_edit` dùng chung một luật: trước đây
        chỉ có `on_message`, nên gửi tin nhắn vô hại rồi EDIT thêm link/từ cấm là qua mặt
        automod hoàn toàn. `content` là văn bản đã chuẩn hóa (xem message_scan_text) gồm cả
        embed và sticker — những thứ không nằm trong message.content.
        """
        # 2. Bad words check
        if settings.get("bad_words_enabled"):
            bad_words = settings.get("bad_words", [])
            for word in bad_words:
                if word.lower() in content:
                    await self._handle_violation(message, tr(await self._reason_lang(message.guild), "automod.su_dung_tu_cam", word=word), settings)
                    return True

        # 3. Links check — luôn chạy khi bật, kể cả domain trần không scheme.
        if settings.get("links_enabled"):
            whitelist = settings.get("whitelist_links", [])
            domains = extract_domains(content)

            violation_reason = None
            blacklist = settings.get("blacklist_links", [])
            for domain, source in domains:
                # Bo "www." de so khop voi whitelist luu dang tran domain
                # (`youtube.com`), khong phai `www.youtube.com`.
                domain_lower = domain.lower()
                if domain_lower.startswith("www."):
                    domain_lower = domain_lower[4:]

                # 3.0 Blacklist của server — ưu tiên CAO NHẤT.
                # Trước đây `blacklist_links` được dashboard lưu nhưng chưa bao giờ
                # dùng để chặn: domain bị cấm vẫn qua được nếu nằm trong whitelist
                # hoặc trong danh sách global-safe.
                for b_link in blacklist:
                    b_domain = str(b_link).lower().replace("https://", "").replace("http://", "").split("/")[0].strip()
                    if b_domain and (domain_lower == b_domain or domain_lower.endswith(f".{b_domain}")):
                        violation_reason = f"Gửi link nằm trong Blacklist: {domain}"
                        break
                if violation_reason:
                    break

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

                # 3b. Check Global Blacklist (Fake/Scam) — highest priority.
                # Chạy TRƯỚC file-extension skip để `discord-nitro.zip` vẫn bị chặn.
                for bad_kw in GLOBAL_BLACKLIST_KEYWORDS:
                    if bad_kw in domain_lower:
                        violation_reason = f"Gửi link giả mạo/lừa đảo: {domain}"
                        break
                if violation_reason:
                    break

                # 3c. Token trần trông như filename (`image.png`, `file.zip`) không
                # phải link. Chỉ áp dụng cho bare token; URL có scheme vẫn bị xét
                # hostname như bình thường.
                if source == "bare" and _looks_like_filename(domain_lower):
                    continue

                # 3d. Block unknown links
                violation_reason = f"Gửi link không rõ nguồn gốc: {domain}"
                break  # Found a violating link, stop checking others

            if violation_reason:
                await self._handle_violation(message, violation_reason, settings)
                return True

        # 4. Anti-Invite links check
        if settings.get("anti_invite_enabled"):
            invite_matches = DISCORD_INVITE_PATTERN.findall(content)
            if invite_matches:
                await self._handle_violation(message, tr(await self._reason_lang(message.guild), "automod.gui_link_moi_discord_server"), settings)
                return True
        return False

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
            if guild_id in self.raid_locked_guilds or settings.get("raid_locked"):
                return
            await self._trigger_raid_lockdown(member.guild, settings, len(self.join_cache[guild_id]))

    async def _trigger_raid_lockdown(self, guild: discord.Guild, settings: dict, count: int):
        """Khi phát hiện join ồ ạt: thực hiện raid_action và ghi log."""
        guild_id = str(guild.id)
        if int(settings.get("raid_locked") or 0) or guild_id in self.raid_locked_guilds:
            # Đã lockdown từ trước (kể cả sau restart): không snapshot lại, vì
            # snapshot mới sẽ ghi đè trạng thái ĐÃ KHOÁ và làm mất bản gốc.
            self.raid_locked_guilds.add(guild_id)
            return
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
            tr(await self._reason_lang(guild), "automod.phat_hien_luot_join_trong", count=count),
        )

    async def _lockdown_guild(self, guild: discord.Guild) -> str:
        """Snapshot overwrites của @everyone rồi chặn gửi tin trên mọi kênh text."""
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

    async def _unlock_guild(self, guild: discord.Guild, settings: dict) -> tuple[int, int]:
        """Khôi phục overwrites của @everyone từ snapshot đã lưu."""
        guild_id = str(guild.id)
        raw = settings.get("raid_snapshot") or "[]"
        if isinstance(raw, list):
            snapshot = raw
        else:
            try:
                snapshot = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                snapshot = []
        if not isinstance(snapshot, list):
            snapshot = []
        def_role = guild.default_role
        restored = 0
        failed = 0
        for entry in snapshot:
            if not isinstance(entry, dict):
                failed += 1
                continue
            try:
                channel_id = int(entry.get("channel_id", 0))
            except (TypeError, ValueError):
                failed += 1
                continue
            channel = guild.get_channel(channel_id)
            if channel is None:
                continue
            try:
                original = _deser_overwrite(entry.get("overwrite"))
                await channel.set_permissions(def_role, overwrite=original, reason="Anti-Raid unlock")
                restored += 1
            except discord.Forbidden:
                failed += 1
                logger.warning(f"[AutoMod] Missing perms to unlock {channel.name}")
            except Exception as exc:
                failed += 1
                logger.warning(f"[AutoMod] unlock error on {channel.name}: {exc}")

        if failed:
            # Còn kênh chưa mở được: giữ lockdown + snapshot để lần sau thử lại,
            # tránh trường hợp báo "đã mở khoá" trong khi kênh vẫn bị chặn.
            self.raid_locked_guilds.add(guild_id)
            await async_update_automod_settings(
                guild_id, raid_locked=1,
                raid_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            return restored, failed

        self.raid_locked_guilds.discard(guild_id)
        await async_update_automod_settings(guild_id, raid_locked=0, raid_snapshot="[]")
        return restored, 0

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

        # Ngưỡng 5 object/10 giây: 3 là quá nhạy với server có automod/tempvoice
        # tự dọn kênh (từng gây lockdown oan).
        threshold = int(settings.get("nuke_threshold", 5) or 5)
        if len(self.nuke_cache[guild_id]) >= threshold:
            last = self.nuke_last_handled.get(guild_id, 0)
            if now - last < 20:  # cooldown bảo vệ để không lặp hành động
                return
            self.nuke_last_handled[guild_id] = now
            kinds = {k for _, k in self.nuke_cache[guild_id]}
            await self._handle_nuke(guild, settings, len(self.nuke_cache[guild_id]), kinds)

    async def _handle_nuke(self, guild: discord.Guild, settings: dict, count: int, kinds: set = None):
        guild_id = str(guild.id)
        nuke_actions = settings.get("nuke_actions") or ["channel_delete", "role_delete", "guild_update"]

        actor = await self._find_nuke_actor(guild, kinds)

        # Tránh false-positive: Nếu do bot xoá (tempvoice, verify clean) hoặc không tìm thấy thủ phạm
        if not actor or actor.bot:
            logger.info(f"[AutoMod] Bỏ qua anti-nuke cho guild {guild.name} ({guild_id}): actor={actor} (bot hoặc không xác định)")
            return

        # Miễn trừ chủ server / Admin / role trong `bot_admin_roles`: những người này
        # dọn kênh hợp lệ — ban họ sẽ phá server (và không thể hoàn tác dễ dàng).
        if await self._is_nuke_actor_exempt(guild, actor, settings):
            logger.info(f"[AutoMod] Anti-nuke: {actor} ({actor.id}) thuộc nhóm được miễn trừ — chỉ ghi log.")
            gs = await self._reason_lang(guild)
            await self._log_automod(
                guild_id, settings, tr(gs, "automod.anti_nuke_mien_tru"),
                tr(gs, "automod.object_bi_xoa_trong_giay", count=count, mention=actor.mention, p5=actor.id)
            )
            return

        desc = f"💥 Phát hiện **{count} object** bị xoá trong 10 giây (kênh/vai trò)."
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
        if guild_id not in self.raid_locked_guilds and not settings.get("raid_locked"):
            try:
                snapshot = await self._lockdown_guild(guild)
                self.raid_locked_guilds.add(guild_id)
                await async_update_automod_settings(guild_id, raid_locked=1, raid_snapshot=snapshot)
                desc += "\n**Bảo vệ:** 🔒 Đã chuyển sang lockdown. Dùng `/automods raidunlock` để mở lại."
            except Exception as exc:
                logger.warning(f"[AutoMod] nuke lockdown error: {exc}")

        await self._log_automod(guild_id, settings, "Anti-Nuke", desc)

    async def _is_nuke_actor_exempt(self, guild: discord.Guild, actor, settings: dict) -> bool:
        """Chủ server / Administrator / role trong `bot_admin_roles` → không xử lý."""
        if actor.id == guild.owner_id:
            return True

        member = guild.get_member(actor.id) if hasattr(guild, "get_member") else None
        if member is None:
            return False

        if member.guild_permissions.administrator:
            return True

        try:
            guild_settings = await async_get_guild_settings(str(guild.id))
        except Exception:
            guild_settings = {}
        raw_admin = guild_settings.get("bot_admin_roles") or "[]"
        try:
            admin_roles = set(raw_admin if isinstance(raw_admin, list) else json.loads(raw_admin))
        except Exception:
            admin_roles = set()

        raw_immune = settings.get("immune_roles") or []
        try:
            immune_roles = set(raw_immune if isinstance(raw_immune, list) else json.loads(raw_immune))
        except Exception:
            immune_roles = set()

        allowed = {str(r) for r in admin_roles} | {str(r) for r in immune_roles}
        if allowed & {str(r.id) for r in member.roles}:
            return True
        return False

    async def _find_nuke_actor(self, guild: discord.Guild, kinds: set = None) -> discord.User | None:
        """Tìm người xoá gần nhất từ audit log, CHỈ với loại object vừa bị xoá.

        Trước đây hàm này luôn thử cả `channel_delete` lẫn `role_delete` với cửa sổ
        30 giây, nên một lần xoá kênh hợp lệ của admin có thể bị gán cho bất kỳ
        ai vừa xoá role trong 30 giây trước đó.
        """
        now = discord.utils.utcnow()
        mapping = {
            "channel_delete": discord.AuditLogAction.channel_delete,
            "role_delete": discord.AuditLogAction.role_delete,
        }
        actions = [mapping[k] for k in (kinds or mapping.keys()) if k in mapping]
        for action in actions:
            try:
                async for entry in guild.audit_logs(limit=10, action=action):
                    if entry.user and entry.created_at and \
                       (now - entry.created_at).total_seconds() < 10:
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
    @app_commands.default_permissions(manage_guild=True)
    @checks.is_bot_admin()
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
                name=tr(s, "automod.bao_ve_server"),
                value=tr(s, "automod.raid_action_nguong_join_60s", raid_action=raid_action, get=settings.get('raid_join_per_window', 5), p5=tr(s, 'automod.dang_lockdown') if raid_locked else tr(s, 'automod.binh_thuong')),
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
    @app_commands.default_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def raidlock(self, ctx: commands.Context):
        gs = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else None
        guild_id = str(ctx.guild.id)
        settings = await async_get_automod_settings(guild_id)

        if guild_id in self.raid_locked_guilds or settings.get("raid_locked"):
            await ctx.send(tr(gs, "automod.server_dang_o_trang_thai"), ephemeral=True)
            return

        snapshot = await self._lockdown_guild(ctx.guild)
        self.raid_locked_guilds.add(guild_id)
        await async_update_automod_settings(guild_id, raid_locked=1, raid_snapshot=snapshot)
        await ctx.send(tr(gs, "automod.da_chuyen_server_sang_lockdown"), ephemeral=True)

    @automods.command(name="raidunlock", description="Mở khóa server sau lockdown, khôi phục overwrites")
    @app_commands.default_permissions(manage_guild=True)
    @checks.is_bot_admin()
    async def raidunlock(self, ctx: commands.Context):
        gs = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else None
        guild_id = str(ctx.guild.id)
        settings = await async_get_automod_settings(guild_id)

        restored, failed = await self._unlock_guild(ctx.guild, settings)
        if failed:
            await ctx.send(
                tr(gs, "automod.mo_khoa_chua_tron_ven", restored=restored),
                ephemeral=True,
            )
        else:
            await ctx.send(
                tr(gs, "automod.da_mo_khoa_server_khoi", restored=restored),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Automod(bot))


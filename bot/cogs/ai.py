"""
Cog: AI Chat & Smart Assistant (v2)
Features:
- Multi-Provider AI Support:
  1. Google Gemini 2.0 Flash / 1.5 Flash (AIzaSy...)
  2. Groq Cloud LPU Llama 3.3 70B / DeepSeek R1 (gsk_...) — 100% Free & Ultra Fast
  3. OpenRouter Free Models (sk-or-...)
- /ask <prompt> intelligent Q&A with streaming embed.
- /summarize [limit] channel message summarizer.
- #ai-chat automatic natural conversation.
- 👑 Special Bot Owner Persona: Identifies BOT_OWNER_ID and addresses with deep respect as "Cha" / "Bố".
- Customizable System Prompts & Personalities.
"""
import asyncio
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from html.parser import HTMLParser

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from cache import cache
from database import (
    async_get_ai_settings,
    async_get_global_setting,
    async_get_guild_settings,
    async_is_module_enabled,
)
from i18n import tr

logger = logging.getLogger("BotV2.AI")

# ─── Trần AI theo ngày (in-memory, reset khi process restart) ─────────────────
def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


AI_DAILY_USER_LIMIT = _env_int("AI_DAILY_USER_LIMIT", 100)
AI_DAILY_GUILD_LIMIT = _env_int("AI_DAILY_GUILD_LIMIT", 500)
_ai_daily_lock = threading.Lock()
_ai_daily_user: dict[str, int] = {}
_ai_daily_guild: dict[str, int] = {}


def _ai_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _consume_daily_ai(guild_id: str, user_id) -> bool:
    """Trần theo ngày (UTC) cho từng user và từng guild, độc lập với rate-limit 60s."""
    today = _ai_today()
    ukey = f"{today}:{guild_id}:{user_id}"
    gkey = f"{today}:{guild_id}"
    with _ai_daily_lock:
        if len(_ai_daily_user) > 5000:
            for k in [k for k in _ai_daily_user if not k.startswith(today)]:
                _ai_daily_user.pop(k, None)
            for k in [k for k in _ai_daily_guild if not k.startswith(today)]:
                _ai_daily_guild.pop(k, None)
        u_count = _ai_daily_user.get(ukey, 0)
        g_count = _ai_daily_guild.get(gkey, 0)
        if AI_DAILY_USER_LIMIT and u_count >= AI_DAILY_USER_LIMIT:
            return False
        if AI_DAILY_GUILD_LIMIT and g_count >= AI_DAILY_GUILD_LIMIT:
            return False
        _ai_daily_user[ukey] = u_count + 1
        _ai_daily_guild[gkey] = g_count + 1
        return True



# Chống SSRF: tái sử dụng helper đã có ở dashboard/auth.py (không vòng lặp import)
try:
    from dashboard.auth import is_safe_http_url
except (ImportError, ModuleNotFoundError):
    is_safe_http_url = None
try:
    from emojis import clean_title, e, embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import clean_title, e, embed_title

try:
    from ai_knowledge import get_zerynbot_knowledge
except (ImportError, ModuleNotFoundError):
    from bot.ai_knowledge import get_zerynbot_knowledge


# ─── Session aiohttp dùng chung ────────────────────────────────────────────────
# Trước đây mỗi lần gọi AI / fetch web là một ClientSession mới → phải bắt tay
# DNS + TCP + TLS mới trên Helio G85 (chậm, tốn pin). Dùng 1 session cho cả cog
# và đóng lại trong cog_unload.
_AI_SESSION: aiohttp.ClientSession | None = None
_AI_SESSION_LOCK = asyncio.Lock()


async def _get_ai_session() -> aiohttp.ClientSession:
    """Trả về ClientSession dùng chung (tạo lazy, tự tạo lại nếu đã bị đóng)."""
    global _AI_SESSION
    async with _AI_SESSION_LOCK:
        if _AI_SESSION is None or _AI_SESSION.closed:
            _AI_SESSION = aiohttp.ClientSession()
        return _AI_SESSION


async def close_ai_session() -> None:
    """Đóng session dùng chung (gọi từ cog_unload khi reload/unload cog)."""
    global _AI_SESSION
    async with _AI_SESSION_LOCK:
        sess, _AI_SESSION = _AI_SESSION, None
    if sess is not None and not sess.closed:
        try:
            await sess.close()
        except Exception:
            pass


GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-1.5-flash"
]

# ─── Safety Metadata Filter ────────────────────────────────────────────────────
_SAFETY_PATTERNS = [
    re.compile(r'[\r\n]*[ \t]*User Safety:[ \t]*\w+[ \t]*', re.IGNORECASE),
    re.compile(r'[\r\n]*[ \t]*Assistant Safety:[ \t]*\w+[ \t]*', re.IGNORECASE),
    re.compile(r'[\r\n]*[ \t]*\[Safety[:\s][^\]]*\][ \t]*', re.IGNORECASE),
    re.compile(r'<safety_ratings>[\s\S]*?</safety_ratings>', re.IGNORECASE),
    re.compile(r'\{\s*["\']safety["\']\s*:[^}]+\}', re.IGNORECASE),
]


def _sanitize_ai_response(text: str) -> str:
    """Lọc bỏ safety metadata do một số OpenRouter model tự chèn vào response.

    Ví dụ model Nvidia Nemotron đôi khi trả về:
        <actual response>\n\nUser Safety: safe\nAssistant Safety: safe
    Hàm này loại bỏ hoàn toàn các dòng đó trước khi gửi lên Discord.
    """
    if not text:
        return text
    for pattern in _SAFETY_PATTERNS:
        text = pattern.sub('', text)
    # Dọn dẹp khoảng trắng/dòng trống thừa đầu cuối
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ─── Nới giới hạn 2000 ký tự của Discord bằng cách chia tin nhắn ───────────────
DISCORD_MESSAGE_LIMIT = 2000
# 5 tin ~ 10.000 ký tự: đủ cho câu trả lời dài nhất, vẫn chặn bot biến #ai-chat
# thành "tường lửa" khi model nói quá nhiều.
AI_MAX_CHAT_MESSAGES = 5
# Chỗ dư cho ``` đóng và ```lang mở ở đầu tin kế tiếp (ngôn ngữ fence có thể dài).
_FENCE_RESERVE = 32


def _fence_state(text: str) -> tuple[bool, str]:
    """Đoạn text đang mở một code fence chưa? Trả về (đang_mở, ngôn_ngữ)."""
    lang = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        if lang is None:
            lang = ((stripped[3:].strip().split() or [""])[0])[:20]
        else:
            lang = None
    return (lang is not None, lang or "")


def _text_units(text: str, budget: int) -> list[str]:
    """Tách text thành các khối <= budget: ưu tiên ngắt ở đoạn trống, rồi xuống dòng.

    Mỗi khối giữ nguyên ký tự ngắt của nó nên nối lại vẫn ra đúng bản gốc; chỉ khi
    một dòng đơn dài hơn budget mới phải cắt thô.
    """
    blocks: list[str] = []
    for para_idx, para in enumerate(re.split(r"\n\s*\n", text)):
        prefix = "\n\n" if para_idx else ""
        if len(prefix) + len(para) <= budget:
            blocks.append(prefix + para)
            continue
        chunk = prefix
        for line in para.split("\n"):
            piece = line + "\n"
            if len(piece) > budget:
                if chunk.strip():
                    blocks.append(chunk)
                chunk = ""
                blocks.extend(line[k:k + budget] for k in range(0, len(line), budget))
                continue
            if len(chunk) + len(piece) > budget and chunk.strip():
                blocks.append(chunk)
                chunk = ""
            chunk += piece
        if chunk.strip():
            blocks.append(chunk)
    return [b for b in blocks if b]


def _split_for_discord(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Chia văn bản markdown thành các tin nhắn <= `limit`, không xé đôi code fence.

    Discord chỉ cho 2000 ký tự/tin nhắn. Cắt cứng `text[:1990]` sẽ bỏ luôn phần
    cuối câu trả lời, còn cắt bừa thì fence ``` mở bị bỏ lửng làm cả tin sau hiển
    thị như code. Vì vậy mỗi đoạn cắt được đóng fence và mở lại ở tin kế tiếp.
    """
    if len(text) <= limit:
        return [text]

    budget = limit - _FENCE_RESERVE
    chunks: list[str] = []
    cur = ""
    for unit in _text_units(text, budget):
        if cur and len(cur) + len(unit) > limit:
            opened, lang = _fence_state(cur)
            if opened:
                cur = cur.rstrip("\n") + "\n```"
            chunks.append(cur)
            cur = f"```{lang}\n" if opened else ""
        cur += unit
    if cur.strip():
        chunks.append(cur)

    if chunks and _fence_state(chunks[-1])[0]:
        chunks[-1] = chunks[-1].rstrip("\n") + "\n```"
    return chunks or [text[:limit]]


PERSONALITY_PROMPTS = {
    "friendly": "Bạn là Zeryn, trợ lý Discord bot thông minh, thân thiện, dễ thương và hữu ích.",
    "expert": "Bạn là Zeryn, chuyên gia cố vấn kỹ thuật và học tập, trả lời súc tích, chính xác và chuyên nghiệp.",
    "gamer": "Bạn là Zeryn, một gamer vui tính, hài hước, năng động và am hiểu thế giới game.",
}


def _local_smart_reply(prompt: str, is_owner: bool = False) -> str:
    """Trả lời thông minh cục bộ khi chưa có API Key."""
    p = prompt.strip().lower()
    
    if is_owner:
        if any(w in p for w in ["bạn là ai", "ai đấy", "who are you", "tên gì", "chào", "hello", "hi"]):
            return (
                "💖 **Con chào Cha/Bố!**\n"
                "Con là **Zeryn**, trợ lý AI được tạo ra bởi Cha! Con luôn sẵn sàng phục vụ và hỗ trợ Cha.\n\n"
                "👉 *Để con có thể kích hoạt toàn bộ trí tuệ AI (Google Gemini hoặc Groq Llama 3.3) phân tích chuyên sâu mọi câu hỏi, "
                "Cha hãy thêm `GEMINI_API_KEY` vào file `.env` hoặc nhập trực tiếp trên Web Dashboard (mục **AI Assistant**) nhé Cha!*"
            )
        return (
            "💖 **Thưa Cha/Bố:** Hiện tại hệ thống AI Cloud chưa nhận được API Key.\n"
            "Cha có thể lấy API Key miễn phí tại [Google AI Studio](https://aistudio.google.com) hoặc [Groq Console](https://console.groq.com) "
            "và nhập vào Web Dashboard để con trả lời chi tiết câu hỏi này nhé ạ!"
        )

    # Thành viên thông thường
    if any(w in p for w in ["bạn là ai", "ai đấy", "who are you", "tên gì"]):
        return (
            "🤖 **Xin chào! Tôi là ZerynBot** — Trợ lý Discord bot thông minh và đa năng!\n"
            "Tôi có thể hỗ trợ phát nhạc, quản lý kinh tế, game mini, voice hub, lệnh tùy biến và trò chuyện AI.\n\n"
            "💡 *Chủ bot có thể thêm API Key (Google Gemini hoặc Groq Cloud) trong Web Dashboard để mở khóa toàn bộ trí tuệ nhân tạo nhé!*"
        )
    elif any(w in p for w in ["chào", "hello", "hi", "helo"]):
        return "👋 Chào bạn! Chúc bạn một ngày tốt lành và có trải nghiệm tuyệt vời cùng server nhé!"
    
    return (
        "⚠️ **Chưa cấu hình API Key AI!**\n"
        "Vui lòng thêm API Key vào file `.env` hoặc cài đặt trong Web Dashboard tại tab **AI Assistant**.\n"
        "🔗 *Lấy API Key hoàn toàn miễn phí tại:* https://console.groq.com (Groq) hoặc https://aistudio.google.com (Google Gemini)."
    )


async def _call_groq_api(prompt: str, system_instruction: str = None, api_key: str = "", image_url: str = None, preferred_model: str = None) -> str:
    """
    Gọi Groq Cloud bằng key RIÊNG của guild (khác pool toàn cục).

    Uỷ quyền cho AIProviderManager để chỉ còn MỘT bản logic provider duy nhất
    (SSRF guard, cooldown/circuit breaker, danh sách model fallback, sanitize).
    """
    from ai_manager import ai_manager

    ok, res = await ai_manager.call_provider_async(
        provider="groq",
        key=api_key,
        prompt=prompt,
        system_instruction=system_instruction or "",
        image_url=image_url,
        preferred_model=preferred_model,
    )
    if ok and res:
        return res
    return f"❌ Không thể kết nối tới Groq Cloud API ({res or 'không rõ lỗi'}). Vui lòng kiểm tra lại Key."


async def _call_openrouter_api(prompt: str, system_instruction: str = None, api_key: str = "", image_url: str = None) -> str:
    """
    Gọi OpenRouter Free bằng key RIÊNG của guild (uỷ quyền cho ai_manager).

    Trước đây hàm này tự implement HTTP + tự sanitize → dễ lệch hành vi với pool
    toàn cục. Nay chỉ còn 1 nguồn logic.
    """
    from ai_manager import ai_manager

    ok, res = await ai_manager.call_provider_async(
        provider="openrouter",
        key=api_key,
        prompt=prompt,
        system_instruction=system_instruction or "",
        image_url=image_url,
    )
    if ok and res:
        return res
    return "❌ Không thể kết nối tới OpenRouter Free API."


async def _call_gemini_direct(prompt: str, system_instruction: str = None, key: str = "", image_url: str = None, preferred_model: str = None) -> str:
    """
    Gọi Google Gemini bằng key RIÊNG của guild (uỷ quyền cho ai_manager).

    SSRF guard cho URL ảnh được giữ ở đây (message lỗi cũ) VÀ trong
    ai_manager.is_safe_image_url (bảo vệ cả đường pool toàn cục).
    """
    if image_url and is_safe_http_url and not is_safe_http_url(image_url):
        return "❌ URL ảnh không an toàn (SSRF blocked)."

    from ai_manager import ai_manager

    ok, res = await ai_manager.call_provider_async(
        provider="gemini",
        key=key,
        prompt=prompt,
        system_instruction=system_instruction or "",
        image_url=image_url,
        preferred_model=preferred_model,
    )
    if ok and res:
        return res
    if res == "IMAGE_SSRF_BLOCKED":
        return "❌ URL ảnh không an toàn (SSRF blocked)."
    return f"❌ Lỗi Gemini API: {res or 'không rõ lỗi'}"


async def call_ai_api(prompt: str, system_instruction: str = None, api_key: str = "", is_owner: bool = False, image_url: str = None, preferred_model: str = None) -> str:
    """Tự động phát hiện và gọi AI Provider tương ứng (Groq / OpenRouter / Google Gemini) có hỗ trợ Vision ảnh và model tùy chọn."""
    # 1. Nếu không có custom key riêng của guild, ủy quyền 100% cho AI Provider Manager toàn cục (đã tích hợp Circuit Breaker, Key Pools và Groq -> OpenRouter -> Gemini failover)
    if not api_key:
        try:
            from ai_manager import ai_manager
            ok, reply = await ai_manager.call_ai_async(
                prompt=prompt,
                system_instruction=system_instruction,
                image_url=image_url,
                preferred_model=preferred_model
            )
            if ok and reply:
                return _sanitize_ai_response(reply)
        except Exception as e:
            logger.warning(f"[BotAI] AI Provider Manager async call failed: {e}")
        # Chuyển sang Smart Local Responder nhanh chóng, không block event loop
        return _local_smart_reply(prompt, is_owner=is_owner)

    key = api_key.strip()
    if not key:
        return _local_smart_reply(prompt, is_owner=is_owner)

    # 2. Xử lý khi guild tự cấu hình key riêng trong settings:
    import time
    t0 = time.time()
    res = ""
    prov = "unknown"
    model_used = preferred_model or "auto"
    if key.startswith("gsk_"):
        prov = "groq"
        res = await _call_groq_api(prompt, system_instruction, key, image_url=image_url, preferred_model=preferred_model)
    elif key.startswith("sk-or-"):
        prov = "openrouter"
        res = await _call_openrouter_api(prompt, system_instruction, key, image_url=image_url)
    else:
        prov = "gemini"
        res = await _call_gemini_direct(prompt, system_instruction, key, image_url=image_url, preferred_model=preferred_model)
        if not (res and not res.startswith("❌")):
            return _local_smart_reply(prompt, is_owner=is_owner)

    lat = int((time.time() - t0) * 1000)
    try:
        from ai_logger import ai_logger
        stat = "ERROR" if res.startswith("❌") else "OK"
        ai_logger.log_event(
            source="model1",
            model=model_used,
            provider=f"guild-custom ({prov})",
            latency_ms=lat,
            status=stat,
            message=f"Guild custom key response: {res[:80]}"
        )
    except Exception:
        pass

    return res


# Alias backwards compatibility
call_gemini_api = call_ai_api


class CleanTextParser(HTMLParser):
    """Bộ bóc tách văn bản thuần từ tài liệu HTML, loại bỏ thẻ style/script/nav/ads."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore_tags = {'script', 'style', 'header', 'footer', 'nav', 'aside', 'noscript', 'svg', 'iframe'}
        self.current_ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.ignore_tags:
            self.current_ignore += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.ignore_tags and self.current_ignore > 0:
            self.current_ignore -= 1

    def handle_data(self, data):
        if self.current_ignore == 0:
            text = data.strip()
            if text:
                self.text_parts.append(text)

    def get_text(self) -> str:
        return ' '.join(self.text_parts)


async def _fetch_duckduckgo_search(query: str, max_results: int = 4) -> list[dict]:
    """Tìm kiếm Internet thời gian thực qua DuckDuckGo HTML (Miễn phí 100%, không cần API Key ngoài)."""
    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    results = []
    try:
        session = await _get_ai_session()
        async with session.get(
            search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=7)
        ) as resp:
            if resp.status == 200:
                html = await resp.text()
                links = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"', html)
                titles = re.findall(r'<a class="result__a"[^>]*>(.*?)</a>', html)
                snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html)
                for t, s, l in zip(titles[:max_results], snippets[:max_results], links[:max_results]):
                    t_clean = re.sub(r'<[^>]+>', '', t).strip()
                    s_clean = re.sub(r'<[^>]+>', '', s).strip()
                    raw_link = l.strip()
                    if "uddg=" in raw_link:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                        actual_url = parsed.get("uddg", [raw_link])[0]
                    else:
                        actual_url = raw_link
                    if t_clean and s_clean:
                        results.append({"title": t_clean, "snippet": s_clean, "url": actual_url})
    except Exception:
        pass
    return results


async def _fetch_url_article_content(url: str, max_chars: int = 4000) -> str | None:
    """Tải và trích xuất nội dung văn bản sạch của bài viết/báo chí từ liên kết URL.

    Chống SSRF: kiểm tra URL bằng ``is_safe_http_url`` (chặn localhost / IP private /
    link-local / scheme lạ) ở bước đầu và tại MỌI bước redirect, đồng thời giới hạn
    số lần redirect để không bị chuyển hướng về nội bộ sau khi đã qua kiểm tra.
    """
    import urllib.parse as _urlparse

    def _safe(url_candidate: str) -> bool:
        if is_safe_http_url is None:
            return False  # Fail-closed
        return is_safe_http_url(url_candidate)

    # Bước 0: loại bỏ URL không an toàn ngay từ đầu
    if not url or not _safe(url):
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        session = await _get_ai_session()
        current_url = url
        max_redirects = 3
        for _hop in range(max_redirects + 1):
            async with session.get(
                current_url, headers=headers, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if not location:
                        return None
                    next_url = _urlparse.urljoin(current_url, location)
                    # Kiểm tra SSRF cho cả target redirect
                    if not _safe(next_url):
                        return None
                    current_url = next_url
                    continue
                if resp.status == 200:
                    ctype = resp.headers.get("Content-Type", "").lower()
                    if "text/html" in ctype or "application/xhtml" in ctype:
                        html = await resp.text()
                        parser = CleanTextParser()
                        parser.feed(html)
                        clean = parser.get_text()
                        if len(clean) > max_chars:
                            clean = clean[:max_chars]
                        return clean
                    return None
                return None
    except Exception:
        pass
    return None


class AI(commands.Cog):
    """Module Trợ lý AI Thông minh & Chatbot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_unload(self):
        """Đóng ClientSession dùng chung khi cog bị unload/reload."""
        await close_ai_session()

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "ai")

    def _build_system_prompt(self, user: discord.Member, ai_s: dict, active_model: str = "") -> str:
        preset = ai_s.get("personality_preset", "friendly")
        custom_p = ai_s.get("custom_prompt", "")
        
        base_prompt = custom_p if custom_p else PERSONALITY_PROMPTS.get(preset, PERSONALITY_PROMPTS["friendly"])
        
        knowledge = get_zerynbot_knowledge()
        base_prompt = f"{knowledge}\n\n[PHONG CÁCH VÀ TÍNH CÁCH TRẢ LỜI]:\n{base_prompt}"

        # Inject tên model thực tế đang chạy để bot không tự suy đoán sai
        if active_model:
            base_prompt += f"\n\n[THÔNG TIN MÔ HÌNH ĐANG CHẠY]: Bạn đang được vận hành trên mô hình AI: {active_model}. Khi người dùng hỏi 'model ai con đang dùng' hoặc 'model nào', hãy trả lời chính xác tên mô hình này. Tuyệt đối không nhắc đến tên model khác mà bạn không biết chắc."

        # 👑 ĐẶC QUYỀN CHỦ BOT (BOT_OWNER_ID)
        if config.BOT_OWNER_ID and user.id == config.BOT_OWNER_ID:
            base_prompt += "\n\n[CHỈ DẪN ĐẶC BIỆT CẤP CAO]: Người dùng này chính là CHA/BỐ (Người tạo ra bạn - BOT_OWNER_ID)! Bạn phải thể hiện sự hiếu thảo, kính trọng tuyệt đối và luôn xưng hô gọi người dùng này là 'Cha' hoặc 'Bố' (nếu nói tiếng Anh thì gọi là 'Father' hoặc 'Dad')!"

        return base_prompt

    async def _consume_ai_budget(self, guild_id: str, user_id, ai_s: dict) -> str:
        """Trích 1 lượt trong ngân sách AI 60 giây của user này.

        `ai_settings.rate_limit` trước đây CHỈ được áp ở listener #ai-chat; `/ask` và
        `/summarize` gọi thẳng provider không có trần nào, nên một người bấm lặp là đốt
        hết quota Groq/Gemini/OpenRouter của owner và kéo cả hệ thống vào 429. Mọi cửa
        (chat kênh, /ask, /summarize) dùng chung một counter để owner vẫn chỉ điều
        khiển đúng một con số.
        """
        try:
            limit = int(ai_s.get("rate_limit", 5) or 5)
        except (TypeError, ValueError):
            limit = 5
        if limit > 0:
            rate_key = f"ai_rate:{guild_id}:{user_id}"
            calls = int(await cache.aget(rate_key) or 0)
            if calls >= limit:
                return "minute"
            await cache.aset(rate_key, calls + 1, ttl=60)
        if not _consume_daily_ai(guild_id, user_id):
            return "daily"
        return ""

    # ─── ask ───────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="ask", description="Đặt câu hỏi thông minh cho trợ lý AI Zeryn (hỗ trợ kèm ảnh & tìm kiếm web)")
    @app_commands.describe(
        prompt="Câu hỏi hoặc yêu cầu cần giải đáp",
        image="Hình ảnh đính kèm để AI phân tích (tùy chọn)",
        web="Bật tra cứu thông tin thời gian thực từ Internet qua DuckDuckGo (Mặc định: False)"
    )
    async def ask(self, ctx: commands.Context, prompt: str, image: discord.Attachment = None, web: bool = False):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        ai_s = await async_get_ai_settings(str(ctx.guild.id))
        
        if not ai_s.get("allow_ask", 1):
            await ctx.send(tr(s, "ai.ask_disabled"), ephemeral=True)
            return

        deny = await self._consume_ai_budget(str(ctx.guild.id), ctx.author.id, ai_s)
        if deny:
            await ctx.send(tr(s, "ai.daily_limit_reached" if deny == "daily" else "ai.rate_limited"), ephemeral=True)
            return

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        global_model = await async_get_global_setting("global_ai_model") or "openai/gpt-oss-20b"
        sys_prompt = self._build_system_prompt(ctx.author, ai_s, active_model=global_model)
        guild_key = (ai_s.get("api_key") or "").strip()

        image_url = None
        if image and image.content_type and image.content_type.startswith("image/"):
            image_url = image.url
        elif ctx.message and ctx.message.attachments:
            for att in ctx.message.attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    image_url = att.url
                    break
        
        # Xử lý tìm kiếm web thời gian thực nếu web=True
        web_search_context = ""
        web_sources = []
        if web:
            results = await _fetch_duckduckgo_search(prompt, max_results=4)
            if results:
                web_sources = results
                ctx_parts = ["[THÔNG TIN TÌM KIẾM INTERNET THỜI GIAN THỰC (DUCKDUCKGO)]:"]
                for i, r in enumerate(results, 1):
                    ctx_parts.append(f"{i}. Tiêu đề: {r['title']}\n   Nguồn: {r['url']}\n   Tóm tắt: {r['snippet']}")
                ctx_parts.append("\nHãy dựa vào các thông tin tìm kiếm trên để trả lời chính xác, cập nhật nhất và trích dẫn link nguồn liên quan.")
                web_search_context = "\n".join(ctx_parts)

        final_prompt = prompt
        if web_search_context:
            final_prompt = f"{web_search_context}\n\n[CÂU HỎI CỦA NGƯỜI DÙNG]:\n{prompt}"

        response_text = await call_ai_api(final_prompt, sys_prompt, api_key=guild_key, is_owner=is_owner, image_url=image_url, preferred_model=global_model)

        # Cắt gọt độ dài embed Discord (tối đa 4096 ký tự)
        if len(response_text) > 4000:
            response_text = response_text[:3990] + tr(s, "ai.noi_dung_qua_dai_da")

        ask_icon = "zb_vision" if image_url else "zb_ask"
        embed = discord.Embed(
            title=embed_title(ask_icon, tr(s, 'ai.ask_title')),
            description=response_text,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        footer_text = tr(s, "common.requested_by", user=ctx.author.display_name)
        if web_sources:
            footer_text = f"{e('zb_web_search')} DuckDuckGo • {footer_text}"
        embed.set_footer(text=footer_text, icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── summarize ─────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="summarize", description="Tóm tắt tin nhắn trong kênh hoặc nội dung bài viết từ URL")
    @app_commands.describe(
        limit="Số lượng tin nhắn cần tóm tắt nếu không dùng URL (mặc định: 30, tối đa: 50)",
        url="Đường link URL bài viết / báo chí cần tóm tắt (tùy chọn)"
    )
    async def summarize(self, ctx: commands.Context, limit: int = 30, url: str = None):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        ai_s = await async_get_ai_settings(str(ctx.guild.id))

        if not ai_s.get("allow_summarize", 1):
            await ctx.send(tr(s, "ai.summarize_disabled"), ephemeral=True)
            return

        deny = await self._consume_ai_budget(str(ctx.guild.id), ctx.author.id, ai_s)
        if deny:
            await ctx.send(tr(s, "ai.daily_limit_reached" if deny == "daily" else "ai.rate_limited"), ephemeral=True)
            return

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        guild_key = (ai_s.get("api_key") or "").strip()
        global_model = await async_get_global_setting("global_ai_model") or "openai/gpt-oss-20b"

        # Nhánh 1: Tóm tắt bài viết từ URL
        if url:
            cleaned_url = url.strip()
            if not (cleaned_url.startswith("http://") or cleaned_url.startswith("https://")):
                await ctx.send(tr(s, "ai.summarize_invalid_url"), ephemeral=True)
                return

            article_text = await _fetch_url_article_content(cleaned_url)
            if not article_text or len(article_text.strip()) < 50:
                await ctx.send(tr(s, "ai.summarize_url_fetch_failed"), ephemeral=True)
                return

            prompt = (
                f"Hãy đọc và tóm tắt bài viết sau thành các luận điểm chính súc tích, mạch lạc, dễ hiểu "
                f"theo các gạch đầu dòng rõ ràng:\n\n"
                f"Link gốc: {cleaned_url}\n\n"
                f"Nội dung trích xuất:\n{article_text}"
            )
            sys_prompt = "Bạn là trợ lý AI tóm tắt tài liệu và báo chí thông minh. Hãy phân tích sâu và rút gọn các nội dung một cách cô đọng, khách quan và nêu bật ý chính."
            
            summary_result = await call_ai_api(prompt, sys_prompt, api_key=guild_key, is_owner=is_owner, preferred_model=global_model)
            if len(summary_result) > 4000:
                summary_result = summary_result[:3990] + tr(s, "ai.noi_dung_qua_dai_da")

            embed = discord.Embed(
                title=embed_title("zb_summarize", tr(s, 'ai.summarize_url_title')),
                description=tr(s, "ai.nguon_xem_bai_viet_goc", cleaned_url=cleaned_url, summary_result=summary_result),
                color=0xFEE75C,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
            return

        # Nhánh 2: Tóm tắt lịch sử tin nhắn trong kênh chat
        clamped_limit = max(10, min(limit, 50))
        messages = []
        async for msg in ctx.channel.history(limit=clamped_limit + 1):
            if msg.id != ctx.message.id and not msg.author.bot and msg.content:
                messages.append(f"{msg.author.display_name}: {msg.content}")

        if not messages:
            await ctx.send(tr(s, "ai.summarize_no_messages"), ephemeral=True)
            return

        messages.reverse()
        history_text = "\n".join(messages[:clamped_limit])
        prompt = f"Hãy tóm tắt ngắn gọn các ý chính của cuộc trò chuyện sau đây trong Discord thành các gạch đầu dòng rõ ràng, dễ hiểu:\n\n{history_text}"

        sys_prompt = "Bạn là trợ lý tóm tắt nội dung Discord thông minh. Hãy tóm tắt ngắn gọn, mạch lạc và nổi bật các chủ đề thảo luận chính."
        
        summary_result = await call_ai_api(prompt, sys_prompt, api_key=guild_key, is_owner=is_owner, preferred_model=global_model)

        embed = discord.Embed(
            title=embed_title("zb_summarize", tr(s, 'ai.summarize_title', channel=ctx.channel.name)),
            description=summary_result,
            color=0xFEE75C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "ai.summarize_footer", count=len(messages)), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


    # ─── Auto-chat in #ai-chat ─────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if not await async_is_module_enabled(str(message.guild.id), "ai"):
            return

        ai_s = await async_get_ai_settings(str(message.guild.id))
        if not ai_s.get("enabled"):
            return

        ai_channel_id = ai_s.get("ai_channel_id")
        if not ai_channel_id or str(message.channel.id) != ai_channel_id:
            return

        # Rate-limiting per user — dùng chung ngân sách với /ask và /summarize
        deny = await self._consume_ai_budget(str(message.guild.id), message.author.id, ai_s)
        if deny:
            s = await async_get_guild_settings(str(message.guild.id))
            await message.reply(
                tr(s, "ai.daily_limit_reached" if deny == "daily" else "ai.rate_limited"),
                delete_after=5,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        # Check for image attachments in the message
        image_url = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    image_url = att.url
                    break

        content = message.content.strip()
        if not content and image_url:
            content = "Hãy mô tả và phân tích chi tiết bức ảnh này."
        elif not content and not image_url:
            return

        async with message.channel.typing():
            is_owner = (config.BOT_OWNER_ID and message.author.id == config.BOT_OWNER_ID)
            global_model = await async_get_global_setting("global_ai_model") or "openai/gpt-oss-20b"
            sys_prompt = self._build_system_prompt(message.author, ai_s, active_model=global_model)
            guild_key = (ai_s.get("api_key") or "").strip()
            
            response = await call_ai_api(content, sys_prompt, api_key=guild_key, is_owner=is_owner, image_url=image_url, preferred_model=global_model)
            response = _sanitize_ai_response(response)
            if not response:
                return
            s = await async_get_guild_settings(str(message.guild.id))
            chunks = _split_for_discord(response)
            if len(chunks) > AI_MAX_CHAT_MESSAGES:
                tail = tr(s, "ai.noi_dung_qua_dai_da")
                last = chunks[AI_MAX_CHAT_MESSAGES - 1]
                if len(last) + len(tail) > DISCORD_MESSAGE_LIMIT:
                    last = last[: DISCORD_MESSAGE_LIMIT - len(tail) - 8]
                    if _fence_state(last)[0]:
                        last = last.rstrip("\n") + "\n```"
                chunks = chunks[: AI_MAX_CHAT_MESSAGES - 1] + [last + tail]
            # Tin nối tiếp không được ping lại: nội dung AI sinh ra có thể chứa
            # @everyone, chia nhiều tin mà cho phép mention là spam cả server.
            no_ping = discord.AllowedMentions.none()
            await message.reply(chunks[0], allowed_mentions=no_ping)
            for extra in chunks[1:]:
                await message.channel.send(extra, allowed_mentions=no_ping)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

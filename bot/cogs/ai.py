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
import os
import re
import sys
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

# Chống SSRF: tái sử dụng helper đã có ở dashboard/auth.py (không vòng lặp import)
try:
    from dashboard.auth import is_safe_http_url
except (ImportError, ModuleNotFoundError):
    is_safe_http_url = None
try:
    from emojis import clean_title, e, embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import clean_title, e, embed_title

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

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
    """Gọi Groq Cloud API (Miễn phí 100%, siêu nhanh, hỗ trợ Vision ảnh)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    if image_url:
        # Multimodal Vision message format cho Groq
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or "Hãy mô tả và phân tích bức ảnh này."},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
        models = [
            "groq/compound", "groq/groq/compound",
            "qwen/qwen3.8-27b", "groq/qwen/qwen3.8-27b",
            "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"
        ]
    else:
        messages.append({"role": "user", "content": prompt})
        models = []
        if preferred_model:
            models.append(preferred_model)
            if preferred_model.startswith("groq/"):
                models.append(preferred_model.replace("groq/", "", 1))
            else:
                models.append(f"groq/{preferred_model}")

        for m in [
            "qwen/qwen3.8-27b",
            "groq/qwen/qwen3.8-27b",
            "qwen/qwen3.6-27b",
            "groq/qwen/qwen3.6-27b",
            "openai/gpt-oss-20b",
            "groq/openai/gpt-oss-20b",
            "groq/compound-mini",
            "groq/groq/compound-mini",
            "groq/compound",
            "groq/groq/compound",
            "openai/gpt-oss-120b",
            "groq/openai/gpt-oss-120b",
            "openai/gpt-oss-safeguard-20b",
            "groq/openai/gpt-oss-safeguard-20b"
        ]:
            if m not in models:
                models.append(m)

    async with aiohttp.ClientSession() as session:
        for model in models:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048
            }
            try:
                async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                continue
    return "❌ Không thể kết nối tới Groq Cloud API. Vui lòng kiểm tra lại Key."


async def _call_openrouter_api(prompt: str, system_instruction: str = None, api_key: str = "", image_url: str = None) -> str:
    """Gọi OpenRouter Free API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://zerynbot.id.vn",
        "X-Title": "ZerynBot"
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or "Hãy mô tả và phân tích bức ảnh này."},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
        free_models = ["meta-llama/llama-3.2-11b-vision-instruct:free", "google/gemini-2.0-flash-exp:free"]
    else:
        messages.append({"role": "user", "content": prompt})
        free_models = ["meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-r1:free", "google/gemini-2.0-flash-exp:free"]

    async with aiohttp.ClientSession() as session:
        for model in free_models:
            payload = {"model": model, "messages": messages}
            try:
                async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                continue
    return "❌ Không thể kết nối tới OpenRouter Free API."


async def call_ai_api(prompt: str, system_instruction: str = None, api_key: str = "", is_owner: bool = False, image_url: str = None, preferred_model: str = None) -> str:
    """Tự động phát hiện và gọi AI Provider tương ứng (Groq / OpenRouter / Google Gemini) có hỗ trợ Vision ảnh và model tùy chọn."""
    key = (api_key or config.GEMINI_API_KEY).strip()
    if not key:
        return _local_smart_reply(prompt, is_owner=is_owner)

    # 1. Groq Cloud (bắt đầu bằng gsk_)
    if key.startswith("gsk_"):
        return await _call_groq_api(prompt, system_instruction, key, image_url=image_url, preferred_model=preferred_model)

    # 2. OpenRouter (bắt đầu bằng sk-or-)
    if key.startswith("sk-or-"):
        return await _call_openrouter_api(prompt, system_instruction, key, image_url=image_url)

    # 3. Google Gemini (Mặc định hoặc bắt đầu bằng AIzaSy)
    parts = [{"text": prompt}]
    if image_url:
        try:
            import base64
            async with aiohttp.ClientSession() as img_session:
                async with img_session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as img_resp:
                    if img_resp.status == 200:
                        img_bytes = await img_resp.read()
                        mime = img_resp.headers.get("Content-Type", "image/jpeg")
                        b64_data = base64.b64encode(img_bytes).decode("utf-8")
                        parts.append({
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64_data
                            }
                        })
        except Exception:
            pass

    payload = {
        "contents": [{"parts": parts}]
    }
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key
    }

    gemini_models_to_try = []
    if preferred_model and (preferred_model.startswith("gemini-") or "gemini" in preferred_model):
        gemini_models_to_try.append(preferred_model)
    for m in GEMINI_MODELS:
        if m not in gemini_models_to_try:
            gemini_models_to_try.append(m)

    last_error = ""
    async with aiohttp.ClientSession() as session:
        for model in gemini_models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            cparts = candidates[0].get("content", {}).get("parts", [])
                            if cparts:
                                return cparts[0].get("text", "").strip()
                        return "❌ AI không tạo được câu trả lời phù hợp."
                    else:
                        err_text = await resp.text()
                        last_error = f"HTTP {resp.status}: {err_text[:120]}"
            except Exception as e:
                last_error = str(e)
                continue

    return f"⚠️ **Lỗi kết nối AI ({last_error})**\nVui lòng kiểm tra lại API Key."


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
    timeout = aiohttp.ClientTimeout(total=7)
    results = []
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(search_url, headers=headers) as resp:
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
            return True  # fallback nếu helper không import được — không chặn (vì đã biết)
        return is_safe_http_url(url_candidate)

    # Bước 0: loại bỏ URL không an toàn ngay từ đầu
    if not url or not _safe(url):
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            current_url = url
            max_redirects = 3
            for _hop in range(max_redirects + 1):
                async with session.get(current_url, headers=headers, allow_redirects=False) as resp:
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

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "ai")

    def _build_system_prompt(self, user: discord.Member, ai_s: dict) -> str:
        preset = ai_s.get("personality_preset", "friendly")
        custom_p = ai_s.get("custom_prompt", "")
        
        base_prompt = custom_p if custom_p else PERSONALITY_PROMPTS.get(preset, PERSONALITY_PROMPTS["friendly"])
        
        # 👑 ĐẶC QUYỀN CHỦ BOT (BOT_OWNER_ID)
        if config.BOT_OWNER_ID and user.id == config.BOT_OWNER_ID:
            base_prompt += "\n\n[CHỈ DẪN ĐẶC BIỆT CẤP CAO]: Người dùng này chính là CHA/BỐ (Người tạo ra bạn - BOT_OWNER_ID)! Bạn phải thể hiện sự hiếu thảo, kính trọng tuyệt đối và luôn xưng hô gọi người dùng này là 'Cha' hoặc 'Bố' (nếu nói tiếng Anh thì gọi là 'Father' hoặc 'Dad')!"

        return base_prompt

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

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        sys_prompt = self._build_system_prompt(ctx.author, ai_s)
        global_key = await async_get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
        global_model = await async_get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
        api_key = ai_s.get("api_key") or global_key

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

        response_text = await call_ai_api(final_prompt, sys_prompt, api_key=api_key, is_owner=is_owner, image_url=image_url, preferred_model=global_model)

        # Cắt gọt độ dài embed Discord (tối đa 4096 ký tự)
        if len(response_text) > 4000:
            response_text = response_text[:3990] + "...\n*(Nội dung quá dài đã được rút gọn)*"

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

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        global_key = await async_get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
        global_model = await async_get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
        api_key = ai_s.get("api_key") or global_key

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
            
            summary_result = await call_ai_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner, preferred_model=global_model)
            if len(summary_result) > 4000:
                summary_result = summary_result[:3990] + "...\n*(Nội dung quá dài đã được rút gọn)*"

            embed = discord.Embed(
                title=embed_title("zb_summarize", tr(s, 'ai.summarize_url_title')),
                description=f"🔗 **Nguồn:** [Xem bài viết gốc]({cleaned_url})\n\n{summary_result}",
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
        
        summary_result = await call_ai_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner, preferred_model=global_model)

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

        # Rate-limiting per user
        rate_key = f"ai_rate:{message.guild.id}:{message.author.id}"
        calls = await cache.aget(rate_key) or 0
        if calls >= ai_s.get("rate_limit", 5):
            s = await async_get_guild_settings(str(message.guild.id))
            await message.reply(tr(s, "ai.rate_limited"), delete_after=5)
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
            sys_prompt = self._build_system_prompt(message.author, ai_s)
            global_key = await async_get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
            global_model = await async_get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
            api_key = ai_s.get("api_key") or global_key
            
            response = await call_ai_api(content, sys_prompt, api_key=api_key, is_owner=is_owner, image_url=image_url, preferred_model=global_model)
            if len(response) > 2000:
                response = response[:1990] + "..."
            await message.reply(response)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

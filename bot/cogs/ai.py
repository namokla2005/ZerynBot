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
import sys, os, aiohttp, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_get_ai_settings, async_get_global_setting
)
from i18n import tr
from cache import cache

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
    @commands.hybrid_command(name="ask", description="Đặt câu hỏi thông minh cho trợ lý AI Zeryn (hỗ trợ kèm ảnh)")
    @app_commands.describe(
        prompt="Câu hỏi hoặc yêu cầu cần giải đáp",
        image="Hình ảnh đính kèm để AI phân tích (tùy chọn)"
    )
    async def ask(self, ctx: commands.Context, prompt: str, image: discord.Attachment = None):
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
        
        response_text = await call_ai_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner, image_url=image_url, preferred_model=global_model)

        # Cắt gọt độ dài embed Discord (tối đa 4096 ký tự)
        if len(response_text) > 4000:
            response_text = response_text[:3990] + "...\n*(Nội dung quá dài đã được rút gọn)*"

        embed = discord.Embed(
            title=f"🤖 {tr(s, 'ai.ask_title')}",
            description=response_text,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── summarize ─────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="summarize", description="Tóm tắt các tin nhắn gần nhất trong kênh chat")
    @app_commands.describe(limit="Số lượng tin nhắn cần tóm tắt (mặc định: 30, tối đa: 50)")
    async def summarize(self, ctx: commands.Context, limit: int = 30):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        ai_s = await async_get_ai_settings(str(ctx.guild.id))

        if not ai_s.get("allow_summarize", 1):
            await ctx.send(tr(s, "ai.summarize_disabled"), ephemeral=True)
            return

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

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        sys_prompt = "Bạn là trợ lý tóm tắt nội dung Discord thông minh. Hãy tóm tắt ngắn gọn, mạch lạc và nổi bật các chủ đề thảo luận chính."
        global_key = await async_get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
        global_model = await async_get_global_setting("global_ai_model") or "qwen/qwen3.6-27b"
        api_key = ai_s.get("api_key") or global_key
        
        summary_result = await call_ai_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner, preferred_model=global_model)

        embed = discord.Embed(
            title=f"📋 {tr(s, 'ai.summarize_title', channel=ctx.channel.name)}",
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

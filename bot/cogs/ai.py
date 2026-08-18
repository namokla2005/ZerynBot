"""
Cog: AI Chat & Smart Assistant (v2)
Features:
- Google Gemini REST API integration (ultra fast & lightweight).
- Supports gemini-2.0-flash, gemini-1.5-flash, gemini-1.5-pro with automatic fallback.
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
    async_get_ai_settings
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
    """Trả lời thông minh cục bộ khi chưa có Gemini API Key."""
    p = prompt.strip().lower()
    
    if is_owner:
        if any(w in p for w in ["bạn là ai", "ai đấy", "who are you", "tên gì", "chào", "hello", "hi"]):
            return (
                "💖 **Con chào Cha/Bố!**\n"
                "Con là **Zeryn**, trợ lý AI được tạo ra bởi Cha! Con luôn sẵn sàng phục vụ và hỗ trợ Cha.\n\n"
                "👉 *Để con có thể kích hoạt toàn bộ trí tuệ Gemini 2.0 Flash phân tích chuyên sâu mọi câu hỏi, "
                "Cha hãy thêm `GEMINI_API_KEY=your_key` vào file `.env` hoặc nhập trực tiếp trên Web Dashboard (mục **AI Assistant**) nhé Cha!*"
            )
        return (
            "💖 **Thưa Cha/Bố:** Hiện tại hệ thống Gemini Cloud chưa nhận được `GEMINI_API_KEY`.\n"
            "Cha có thể lấy API Key miễn phí tại [Google AI Studio](https://aistudio.google.com) và nhập vào file `.env` hoặc Web Dashboard để con trả lời chi tiết câu hỏi này nhé ạ!"
        )

    # Thành viên thông thường
    if any(w in p for w in ["bạn là ai", "ai đấy", "who are you", "tên gì"]):
        return (
            "🤖 **Xin chào! Tôi là ZerynBot** — Trợ lý Discord bot thông minh và đa năng!\n"
            "Tôi có thể hỗ trợ phát nhạc, quản lý kinh tế, game mini, voice hub, lệnh tùy biến và trò chuyện AI.\n\n"
            "💡 *Chủ bot có thể thêm `GEMINI_API_KEY` trong file `.env` hoặc Web Dashboard để mở khóa toàn bộ trí tuệ nhân tạo Gemini 2.0 Flash nhé!*"
        )
    elif any(w in p for w in ["chào", "hello", "hi", "helo"]):
        return "👋 Chào bạn! Chúc bạn một ngày tốt lành và có trải nghiệm tuyệt vời cùng server nhé!"
    
    return (
        "⚠️ **Chưa cấu hình Google Gemini API Key!**\n"
        "Vui lòng thêm `GEMINI_API_KEY=your_key` vào file `.env` hoặc cài đặt trong Web Dashboard tại tab **AI Assistant**.\n"
        "🔗 *Lấy API Key hoàn toàn miễn phí tại:* https://aistudio.google.com"
    )


async def call_gemini_api(prompt: str, system_instruction: str = None, api_key: str = "", is_owner: bool = False) -> str:
    """Gọi Google Gemini REST API trực tiếp bằng aiohttp với cơ chế multi-model fallback."""
    key = api_key or config.GEMINI_API_KEY
    if not key:
        return _local_smart_reply(prompt, is_owner=is_owner)

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }
    if system_instruction:
        payload["system_instruction"] = {
            "parts": [{"text": system_instruction}]
        }

    headers = {"Content-Type": "application/json"}

    # Thử lần lượt các model: 2.0-flash -> 1.5-flash -> 1.5-pro
    last_error = ""
    async with aiohttp.ClientSession() as session:
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                        return "❌ AI không tạo được câu trả lời phù hợp."
                    else:
                        err_text = await resp.text()
                        last_error = f"HTTP {resp.status}: {err_text[:120]}"
            except Exception as e:
                last_error = str(e)
                continue

    return f"⚠️ **Lỗi kết nối Gemini API ({last_error})**\nVui lòng kiểm tra lại API Key tại: https://aistudio.google.com"


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
    @commands.hybrid_command(name="ask", description="Đặt câu hỏi thông minh cho trợ lý AI Zeryn")
    @app_commands.describe(prompt="Câu hỏi hoặc yêu cầu cần giải đáp")
    async def ask(self, ctx: commands.Context, *, prompt: str):
        await ctx.defer()
        s = await async_get_guild_settings(str(ctx.guild.id))
        ai_s = await async_get_ai_settings(str(ctx.guild.id))
        
        if not ai_s.get("allow_ask", 1):
            await ctx.send(tr(s, "ai.ask_disabled"), ephemeral=True)
            return

        is_owner = (config.BOT_OWNER_ID and ctx.author.id == config.BOT_OWNER_ID)
        sys_prompt = self._build_system_prompt(ctx.author, ai_s)
        api_key = ai_s.get("api_key") or config.GEMINI_API_KEY
        
        response_text = await call_gemini_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner)

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
        api_key = ai_s.get("api_key") or config.GEMINI_API_KEY
        
        summary_result = await call_gemini_api(prompt, sys_prompt, api_key=api_key, is_owner=is_owner)

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
            return
        await cache.aset(rate_key, calls + 1, ttl=60)

        async with message.channel.typing():
            is_owner = (config.BOT_OWNER_ID and message.author.id == config.BOT_OWNER_ID)
            sys_prompt = self._build_system_prompt(message.author, ai_s)
            api_key = ai_s.get("api_key") or config.GEMINI_API_KEY
            
            response = await call_gemini_api(message.content, sys_prompt, api_key=api_key, is_owner=is_owner)
            if len(response) > 2000:
                response = response[:1990] + "..."
            await message.reply(response)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

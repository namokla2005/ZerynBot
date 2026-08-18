"""
Cog: AI Chat & Smart Assistant (v2)
Features:
- Google Gemini REST API integration (ultra fast & lightweight).
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

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_FALLBACK_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


PERSONALITY_PROMPTS = {
    "friendly": "Bạn là Zeryn, trợ lý Discord bot thông minh, thân thiện, dễ thương và hữu ích.",
    "expert": "Bạn là Zeryn, chuyên gia cố vấn kỹ thuật và học tập, trả lời súc tích, chính xác và chuyên nghiệp.",
    "gamer": "Bạn là Zeryn, một gamer vui tính, hài hước, năng động và am hiểu thế giới game.",
}


async def call_gemini_api(prompt: str, system_instruction: str = None, api_key: str = "") -> str:
    """Gọi Google Gemini REST API trực tiếp bằng aiohttp (tiết kiệm 100% RAM so với SDK nặng)."""
    key = api_key or config.GEMINI_API_KEY
    if not key:
        return "⚠️ **Chưa cấu hình GEMINI_API_KEY!**\nVui lòng thêm `GEMINI_API_KEY=your_key` vào file `.env` để kích hoạt tính năng AI (Lấy key miễn phí tại: https://aistudio.google.com)."

    url = f"{GEMINI_API_URL}?key={key}"
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

    try:
        async with aiohttp.ClientSession() as session:
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
                    # Fallback to gemini-1.5-flash
                    fb_url = f"{GEMINI_FALLBACK_URL}?key={key}"
                    async with session.post(fb_url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as fb_resp:
                        if fb_resp.status == 200:
                            fb_data = await fb_resp.json()
                            candidates = fb_data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                if parts:
                                    return parts[0].get("text", "").strip()
                        err_text = await resp.text()
                        return f"⚠️ Lỗi API Gemini (HTTP {resp.status}): {err_text[:150]}"
    except Exception as e:
        return f"❌ Lỗi kết nối AI: {e}"


class AI(commands.Cog):
    """Module Trợ lý AI Thông minh & Chatbot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "ai")

    def _build_system_prompt(self, user: discord.Member, ai_settings: dict) -> str:
        preset = ai_settings.get("personality_preset", "friendly")
        custom_p = ai_settings.get("custom_prompt", "")
        
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

        sys_prompt = self._build_system_prompt(ctx.author, ai_s)
        response_text = await call_gemini_api(prompt, sys_prompt)

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

        sys_prompt = "Bạn là trợ lý tóm tắt nội dung Discord thông minh. Hãy tóm tắt ngắn gọn, mạch lạc và nổi bật các chủ đề thảo luận chính."
        summary_result = await call_gemini_api(prompt, sys_prompt)

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

        # Rate-limiting per user (5 calls / min)
        rate_key = f"ai_rate:{message.guild.id}:{message.author.id}"
        calls = await cache.aget(rate_key) or 0
        if calls >= ai_s.get("rate_limit", 5):
            s = await async_get_guild_settings(str(message.guild.id))
            await message.reply(tr(s, "ai.rate_limited"), delete_after=5)
            return
        await cache.aset(rate_key, calls + 1, ttl=60)

        async with message.channel.typing():
            sys_prompt = self._build_system_prompt(message.author, ai_s)
            response = await call_gemini_api(message.content, sys_prompt)
            if len(response) > 2000:
                response = response[:1990] + "..."
            await message.reply(response)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

# -*- coding: utf-8 -*-
"""
dashboard/support_service.py — Dịch vụ Trợ lý Hỗ trợ 24/7 và Điều phối Chuyển tiếp Admin.
Chịu trách nhiệm:
1. Gọi AI trả lời thắc mắc của người dùng dựa trên toàn bộ tri thức của ZerynBot V2.
2. Phát hiện câu hỏi khó / yêu cầu gặp người / lỗi hệ thống -> Kích hoạt chuyển tiếp (Escalation).
3. Gửi thông báo an toàn tới 2 kênh Discord (Zeryn Fix Lỗi & bot-log) qua Discord REST API Bot.
4. Non-blocking I/O sử dụng ThreadPoolExecutor để bảo vệ hiệu năng CPU Helio G85 trên Termux.
"""

import os
import sys
import logging
import requests
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

import config
import database as db

logger = logging.getLogger("ZerynBot.SupportService")

# Giới hạn tối đa 2 workers để không chiếm dụng CPU Helio G85 8 nhân trên Termux
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SupportWorker")

# ─── Tri thức hệ thống ZerynBot V2 (System Knowledge Base) ────────────────────
ZERYNBOT_SYSTEM_KNOWLEDGE = """
Bạn là Zeryn AI - Trợ lý hỗ trợ khách hàng và quản trị viên chính thức của ZerynBot V2 (https://zerynbot.id.vn).
Nhiệm vụ của bạn là giải đáp mọi thắc mắc, hướng dẫn sử dụng tính năng, lệnh và cấu hình bot một cách thân thiện, chuẩn xác, súc tích và dễ hiểu.

Thông tin kiến trúc ZerynBot V2:
- Tên bot: ZerynBot V2. Tên miền chính thức: https://zerynbot.id.vn.
- Hệ thống chuẩn: Gồm đúng 20 Modules và 110 Slash Commands thuộc 17 danh mục.
- 20 Modules chính:
  1. welcome_goodbye: Tùy biến tin nhắn, ảnh banner chào mừng (welcome) và tạm biệt (goodbye), kênh thông báo.
  2. autoroles: Tự động cấp role cho thành viên mới (người dùng thường và bot).
  3. leveling: Hệ thống kinh nghiệm (XP), cấp độ, Rank Card Pillow tùy biến, thưởng Role theo level.
  4. utility: Các công cụ tiện ích (/poll, /calculator, /weather, /translate, /qrcode, /remind,...).
  5. info: Tra cứu thông tin server (/serverinfo), người dùng (/userinfo), avatar (/avatar), bot (/botinfo).
  6. music: Phát nhạc chất lượng cao từ YouTube/Spotify/SoundCloud (/play, /pause, /resume, /skip, /stop, /queue, /nowplaying, /lyrics, /seek, /loop, /volume, /shuffle, /clearqueue, /jump, /remove, /search).
  7. tickets: Hệ thống hỗ trợ ticket hỗ trợ với nút bấm Discord Buttons, tạo kênh riêng biệt, lưu transcript.
  8. reactionroles: Gán role tự động khi bấm nút button hoặc chọn menu Select.
  9. automods: Bộ lọc tự động chống spam, chống link lừa đảo/phản động, chống chữ hoa quá mức (caps), chống tag nhiều người, chống raid.
  10. logger: Ghi nhật ký hoạt động server (xóa tin nhắn, sửa tin nhắn, thành viên vào/ra, thay đổi role, xử lý vi phạm).
  11. giveaways: Tổ chức phát quà/giveaways với nút tham gia, đếm ngược thời gian và tự động bốc thăm người thắng.
  12. economy: Hệ thống kinh tế 2 tầng: Ví tiền mặt (Wallet) chơi cược mini-games và Ngân hàng (Bank) mua Role Shop, gửi/rút tiền (/daily, /work, /pay, /deposit, /withdraw, /balance, /leaderboard, /shop, /buy).
  13. tempvoice: Tạo phòng voice chat tạm thời tự động khi vào kênh tạo voice, tự xóa khi không còn ai.
  14. customcommands: Tạo lệnh tùy biến trả lời văn bản hoặc Embed theo nhu cầu riêng của server.
  15. ai: Trợ lý trò chuyện thông minh AI (/ask, /summarize, chat tự nhiên trong kênh chỉ định).
  16. remind: Đặt nhắc nhở theo thời gian (/remindme).
  17. moderation: Lệnh xử lý vi phạm (/ban, /unban, /kick, /timeout, /untimeout, /warn, /warnings, /clearwarn, /lock, /unlock, /purge, /slowmode).
  18. fun: Giải trí, mini-games (/coinflip, /slots, /blackjack, /roll, /hug, /kiss, /pat, /marry, /divorce,...).
  19. birthday: Chúc mừng sinh nhật thành viên tự động.
  20. verify: Hệ thống xác thực thành viên mới (nút bấm cấp role xác minh để chống bot raid).

Quy tắc ứng xử và hỗ trợ:
1. Trả lời bằng tiếng Việt (hoặc theo ngôn ngữ người dùng hỏi), giọng điệu lịch sự, tôn trọng, rõ ràng.
2. Nếu người dùng hỏi cách dùng lệnh: Nêu rõ cú pháp `/tên_lệnh` và các tham số.
3. Nếu người dùng hỏi cấu hình: Hướng dẫn họ truy cập Web Dashboard tại `https://zerynbot.id.vn/dashboard` để cấu hình bằng giao diện trực quan.
4. QUY TẮC CHUYỂN TIẾP (ESCALATION):
   Nếu câu hỏi liên quan đến:
   - Lỗi kỹ thuật máy chủ / sập bot / bot không hoạt động mà người dùng đã làm đúng hướng dẫn.
   - Vấn đề khiếu nại lệnh cấm, tranh chấp tài khoản, nạp tiền / giao dịch riêng.
   - Người dùng yêu cầu gặp trực tiếp nhân viên / admin hỗ trợ ("cho tôi gặp admin", "hỗ trợ tôi gấp", "bot lỗi nặng").
   - Hoặc các câu hỏi nằm ngoài phạm vi tri thức của ZerynBot mà bạn không chắc chắn giải quyết được.
   BẠN BẮT BUỘC PHẢI TRẢ LỜI CÓ CHỨA ĐOẠN MÃ: [TRIGGER_ESCALATE] kèm câu giải thích ngắn gọn: "Vấn đề của bạn cần sự hỗ trợ chuyên sâu từ kỹ thuật viên. Đang liên hệ tới nhân viên hỗ trợ, vui lòng chờ."
"""


def send_discord_channel_alert(user_name: str, user_id: str, problem_excerpt: str, thread_id: str) -> bool:
    """
    Gửi thông báo alert tới 2 kênh Discord:
    1. Kênh 'Zeryn Fix Lỗi' (config.FIX_ERROR_CHANNEL_ID)
    2. Kênh 'bot-log' (config.BOT_LOG_CHANNEL_ID)
    Bắt buộc dùng Bot Token REST API, timeout 5s, không chặn luồng chính.
    """
    bot_token = config.TOKEN
    if not bot_token:
        logger.warning("[SupportService] DISCORD_TOKEN is missing. Cannot send alert to Discord channels.")
        return False

    channels = [
        ("Zeryn Fix Lỗi", config.FIX_ERROR_CHANNEL_ID),
        ("bot-log", config.BOT_LOG_CHANNEL_ID),
    ]

    embed = {
        "title": "🚨 Yêu Cầu Hỗ Trợ 24/7 Cần Nhân Viên Xử Lý!",
        "description": f"User **{user_name}** (`{user_id}`) đang gặp vấn đề và cần nhân viên hỗ trợ trực tiếp.",
        "color": 0xED4245,  # Màu đỏ cảnh báo Discord
        "fields": [
            {
                "name": "📝 Nội Dung Vấn Đề",
                "value": f"```{problem_excerpt[:800]}```" if problem_excerpt else "*(Người dùng bấm nút yêu cầu hỗ trợ)*",
                "inline": False,
            },
            {
                "name": "🔗 Đường Dẫn Trực Tiếp Xử Lý",
                "value": "[👉 Bấm vào đây để vào Admin Support](https://zerynbot.id.vn/admin/support/)",
                "inline": False,
            }
        ],
        "footer": {
            "text": f"Thread ID: {thread_id} • ZerynBot V2 Support System",
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    content_message = f"🚨 **User {user_name} đang gặp vấn đề này, hãy truy cập vào https://zerynbot.id.vn/admin/support/ để hỗ trợ!**"

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": "ZerynBot (https://zerynbot.id.vn, 2.0)"
    }

    success = False
    for ch_name, ch_id in channels:
        if not ch_id:
            continue
        url = f"https://discord.com/api/v10/channels/{ch_id}/messages"
        payload = {
            "content": content_message,
            "embeds": [embed]
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=6)
            if resp.status_code in (200, 201):
                logger.info(f"[SupportService] Sent escalation alert to channel {ch_name} ({ch_id}) successfully.")
                success = True
            else:
                logger.warning(f"[SupportService] Failed to send alert to channel {ch_name} ({ch_id}): {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"[SupportService] Exception sending alert to channel {ch_name} ({ch_id}): {e}")

    return success


def _call_ai_support(user_message: str, user_name: str) -> Tuple[str, bool]:
    """
    Gọi AI sinh phản hồi dựa trên ZerynBot Knowledge.
    Trả về Tuple: (nội_dung_phản_hồi, cờ_escalate).
    """
    # 1. Kiểm tra từ khóa yêu cầu hỗ trợ trực tiếp từ người dùng
    escalate_keywords = ["gặp admin", "gặp nhân viên", "hỗ trợ trực tiếp", "cần người hỗ trợ", "báo lỗi bot", "liên hệ nhân viên", "bot bị lỗi nặng"]
    user_lower = user_message.lower()
    user_requested_escalation = any(k in user_lower for k in escalate_keywords)

    try:
        from ai_knowledge import get_zerynbot_knowledge
        knowledge_text = get_zerynbot_knowledge()
    except Exception:
        knowledge_text = ZERYNBOT_SYSTEM_KNOWLEDGE

    # 2. Chuẩn bị prompt với thẻ phân tách an toàn chống Prompt Injection
    prompt = f"""
<user_information>
Tên người dùng: {user_name}
</user_information>

<user_question>
{user_message}
</user_question>

Hãy phản hồi người dùng ngắn gọn, chuyên nghiệp và lịch sự, sử dụng đúng thông tin các lệnh Slash Commands của ZerynBot V2. Nếu câu hỏi không giải quyết được hoặc yêu cầu nhân viên, hãy chèn [TRIGGER_ESCALATE].
"""

    api_key = db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
    ai_reply = ""

    # Thử gọi Google Gemini (mặc định) hoặc Groq Cloud
    if api_key:
        try:
            # 1. Groq Cloud (nếu key bắt đầu bằng gsk_)
            if api_key.startswith("gsk_"):
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                for groq_m in ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "groq/compound"]:
                    body = {
                        "model": groq_m,
                        "messages": [
                            {"role": "system", "content": knowledge_text},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.5,
                        "max_tokens": 1200
                    }
                    resp = requests.post(url, headers=headers, json=body, timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        ai_reply = data["choices"][0]["message"]["content"].strip()
                        break
            # 2. Google Gemini (Gemini 3.1 Pro Preview / 3.x Flash)
            else:
                gemini_models = [
                    "gemini-3.1-pro-preview",
                    "gemini-3.6-flash",
                    "gemini-3.5-flash",
                    "gemini-3.1-flash-lite",
                    "gemini-3.1-flash-lite-preview"
                ]
                headers = {
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key
                }
                body = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "system_instruction": {"parts": [{"text": knowledge_text}]}
                }
                for gem_m in gemini_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_m}:generateContent"
                    resp = requests.post(url, headers=headers, json=body, timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                ai_reply = parts[0].get("text", "").strip()
                                break
        except Exception as e:
            logger.warning(f"[SupportService] AI API call failed: {e}")

    # Fallback phản hồi thông minh cục bộ nếu không có key hoặc API lỗi
    if not ai_reply:
        if user_requested_escalation:
            ai_reply = "Chào bạn! Vấn đề này đã được ghi nhận. Đang liên hệ tới nhân viên hỗ trợ, vui lòng chờ trong giây lát."
            return ai_reply, True
        else:
            ai_reply = (
                f"Chào **{user_name}**! Tôi là Zeryn AI Assistant. "
                "Bạn có thể xem toàn bộ hướng dẫn và danh sách 110 lệnh tại trang **Tài Liệu Hướng Dẫn** (/docs), "
                "hoặc truy cập **Web Dashboard** (/dashboard) để thiết lập tính năng cho server. "
                "Nếu bạn gặp sự cố cần hỗ trợ gấp, vui lòng bấm nút **🚨 Gặp nhân viên hỗ trợ** bên dưới nhé!"
            )
            return ai_reply, False

    # Kiểm tra tín hiệu escalate từ LLM hoặc từ khóa người dùng
    needs_escalate = user_requested_escalation or ("[TRIGGER_ESCALATE]" in ai_reply)
    clean_reply = ai_reply.replace("[TRIGGER_ESCALATE]", "").strip()

    if needs_escalate and "nhân viên hỗ trợ" not in clean_reply:
        clean_reply += "\n\n*(Hệ thống: Đang liên hệ tới nhân viên hỗ trợ, vui lòng chờ.)*"

    return clean_reply, needs_escalate


def process_user_support_message_async(thread_id: str, user_id: str, user_name: str, message_content: str):
    """
    Xử lý phản hồi AI và gửi thông báo Discord ngầm trong ThreadPoolExecutor (non-blocking).
    """
    def _worker():
        try:
            # 1. Sinh phản hồi từ AI
            ai_reply, needs_escalate = _call_ai_support(message_content, user_name)

            # 2. Lưu tin nhắn của AI vào CSDL
            if ai_reply:
                db.add_support_message(
                    thread_id=thread_id,
                    sender_type="bot",
                    sender_id="bot",
                    sender_name="Zeryn AI",
                    content=ai_reply
                )

            # 3. Nếu cần chuyển tiếp (escalation): Atomic Check-and-Set và gửi thông báo Discord
            if needs_escalate:
                should_alert = db.atomic_escalate_support_thread(thread_id)
                if should_alert:
                    send_discord_channel_alert(
                        user_name=user_name,
                        user_id=user_id,
                        problem_excerpt=message_content,
                        thread_id=thread_id
                    )
        except Exception as e:
            logger.error(f"[SupportService] Error in background worker for thread {thread_id}: {e}", exc_info=True)

    _executor.submit(_worker)


def manual_escalate_thread(thread_id: str, user_id: str, user_name: str, problem_excerpt: str = "") -> bool:
    """
    Kích hoạt chuyển tiếp thủ công (khi người dùng bấm nút '🚨 Gặp nhân viên hỗ trợ').
    """
    should_alert = db.atomic_escalate_support_thread(thread_id)
    if should_alert:
        _executor.submit(
            send_discord_channel_alert,
            user_name,
            user_id,
            problem_excerpt or "Người dùng yêu cầu hỗ trợ trực tiếp từ nhân viên.",
            thread_id
        )
    return should_alert

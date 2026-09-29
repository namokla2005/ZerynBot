# -*- coding: utf-8 -*-
"""
ai_knowledge.py — Nguồn tri thức tập trung (Single Source of Truth) cho AI của ZerynBot V2.
Dùng chung cho cả:
1. Discord Bot AI Cog (bot/cogs/ai.py)
2. Web Dashboard 24/7 Support Service (dashboard/support_service.py)
"""
import functools
from commands_data import _COMMANDS_DATA

@functools.lru_cache(maxsize=1)
def get_zerynbot_knowledge() -> str:
    """
    Biên dịch toàn bộ danh mục 20 modules và 110 lệnh Slash của ZerynBot V2 thành
    chuỗi tri thức Singleton In-Memory siêu nhẹ (~15KB) nạp vào System Instruction.
    """
    lines = [
        "=== BẢN ĐỒ TRI THỨC VÀ TÍNH NĂNG CHÍNH THỨC CỦA ZERYNBOT V2 ===",
        "Tên bot: Zeryn (ZerynBot V2) | Trợ lý Discord đa năng & thông minh hàng đầu.",
        "Trang Web Dashboard & Tài liệu: https://zerynbot.id.vn | Lệnh bot: 100% sử dụng SLASH COMMANDS (tiền tố '/').",
        "TUYỆT ĐỐI KHÔNG SỬ DỤNG HOẶC HƯỚNG DẪN DÙNG LỆNH TIỀN TỐ CŨ NHƯ '!', '-', '.'!",
        "",
        "--- HỆ THỐNG 20 MODULES CỐT LÕI ---",
        "1. Welcome & Goodbye: Tự động gửi tin nhắn chào mừng/tạm biệt kèm ảnh banner render động bằng Pillow.",
        "2. Auto Roles: Tự động gán role cho thành viên mới tham gia server hoặc bot.",
        "3. Leveling & XP: Hệ thống lên cấp, cày XP qua chat/voice, thẻ Rank Card Pillow đồ họa cao cấp.",
        "4. Utility: Các tiện ích máy chủ như /help, /ping, /membercount, /poll, /roll, /userinfo, /avatar,...",
        "5. Info: Tra cứu thông tin máy chủ, người dùng, avatar, emoji, bot status.",
        "6. Music (Âm thanh): Phát nhạc đa luồng cực mượt, hỗ trợ YouTube, Spotify playlist, Soundcloud, cờ FFmpeg đơn luồng chống lag, giao diện Player 5 nút bấm, hỗ trợ /seek, /search, /queue, /loop, /volume.",
        "7. Tickets: Hệ thống vé hỗ trợ khách hàng chuyên nghiệp, nút tạo vé, đóng vé, lưu transcript.",
        "8. Reaction Roles: Tự động nhận role khi bấm nút Button hoặc thả cảm xúc.",
        "9. Automod: Chống spam, cấm gửi link lạ, cấm từ ngữ thô tục, chống capslock, chống flood tin nhắn.",
        "10. Logger: Ghi nhật ký máy chủ (tin nhắn sửa/xóa, thành viên vào/ra, đổi quyền, ban/kick).",
        "11. Giveaways: Tạo và quản lý phát quà ngẫu nhiên (/giveaway start, reroll, end).",
        "12. Economy: Hệ thống kinh tế kép tách biệt: Ví tiền mặt (Wallet - cược game mini /coinflip, /slots, /blackjack) và Ngân hàng (Bank - cất giữ an toàn, mua sắm Role trong /shop).",
        "13. Temp Voice: Kênh thoại tự động (Voice Hub), tự tạo phòng riêng khi tham gia, tự xóa khi phòng trống.",
        "14. Custom Commands: Tự tạo lệnh tùy biến không giới hạn với placeholder linh hoạt.",
        "15. AI Assistant: Trợ lý thông minh đa mô hình (hệ thống AI tốc độ cao, Vision đa phương thức, tìm kiếm web DuckDuckGo).",
        "16. Remind: Lệnh nhắc hẹn giờ thông minh /remind me.",
        "17. Moderation: Bộ công cụ quản trị máy chủ (/ban, /kick, /timeout, /warn, /clear, /lock, /slowmode).",
        "18. Fun: Các lệnh giải trí, meme, mini-games thú vị.",
        "19. Birthday: Chúc mừng sinh nhật tự động cho thành viên theo ngày/tháng.",
        "20. Verify: Xác minh thành viên chống raid bằng nút bấm hoặc Captcha.",
        "",
        "--- DANH MỤC ĐẦY ĐỦ 110 LỆNH SLASH COMMANDS CHUẨN CỦA BOT ---"
    ]

    for cat in _COMMANDS_DATA:
        cat_name = cat.get("category", "Chung")
        icon = cat.get("icon", "🔹")
        lines.append(f"\n[{icon} Danh mục: {cat_name}]")
        for cmd in cat.get("commands", []):
            name = cmd.get("name", "")
            usage = cmd.get("usage", f"/{name}")
            desc = cmd.get("desc", "")
            lines.append(f"  • {usage} — {desc}")

    lines.extend([
        "",
        "--- NGUYÊN TẮC PHẢN HỒI KHI TRÒ CHUYỆN ---",
        "1. Luôn ưu tiên hướng dẫn bằng các lệnh Slash Commands thực tế ở trên.",
        "2. Khi người dùng hỏi về âm nhạc, hãy liệt kê các lệnh Slash như /play, /pause, /skip, /stop, /queue, /volume, /loop, /seek, /search,... Không bao giờ đưa ví dụ bằng prefix '!'!",
        "3. Khi người dùng hỏi về kinh tế, giải thích rõ: Tiền trong Ví dùng để chơi game và chuyển khoản, tiền trong Bank để an toàn và mua Role.",
        "4. Nếu người dùng cần cấu hình nâng cao, hướng dẫn họ truy cập Web Dashboard: https://zerynbot.id.vn/dashboard."
    ])

    return "\n".join(lines)

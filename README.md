# 🤖 Zeryn (ZerynBot V2) — Discord Bot & Web Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Discord.py-2.3%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py">
  <img src="https://img.shields.io/badge/Flask-Web%20Dashboard-black?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/i18n-6%20Languages%20(1187%20Keys)-orange?style=for-the-badge&logo=translate&logoColor=white" alt="i18n 6 Languages">
  <img src="https://img.shields.io/badge/Cache-In--Memory%20RAM-purple?style=for-the-badge&logo=fastapi&logoColor=white" alt="Pure Python In-Memory Cache">
  <img src="https://img.shields.io/badge/Optimized-ARM%20%2F%20Termux-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Termux Optimized">
</p>

**Zeryn** (ZerynBot V2) là một Discord Bot đa chức năng thế hệ mới tích hợp **Web Dashboard quản trị server**, hỗ trợ **Đa ngôn ngữ (i18n)** toàn diện, bộ nhớ đệm **In-Memory RAM Cache** thuần Python siêu nhẹ và được tối ưu hóa đặc biệt để vận hành 24/7 mượt mà trên các thiết bị cấu hình thấp (như máy tính bảng Android chạy **Termux**, Raspberry Pi hoặc VPS giá rẻ).

---

## 📚 Tài Liệu Kiến Trúc (Cho Developers & AI)

Dự án có sẵn tài liệu kiến trúc kỹ thuật chi tiết dành cho các lập trình viên và trợ lý AI:
- 📖 [**ARCHITECTURE.md**](./ARCHITECTURE.md) — Sơ đồ kiến trúc, cơ sở dữ liệu SQLite (WAL mode, busy timeout 15s), In-Memory RAM Cache với cơ chế dọn dẹp định kỳ 5 phút, luồng dữ liệu, quy tắc đa ngôn ngữ (**1187 keys/ngôn ngữ**) và danh sách anti-patterns cần tránh.

---

## ✨ Tính Năng Nổi Bật

### 🌍 1. Đa Ngôn Ngữ Hoàn Toàn (Full i18n Engine)
- Hỗ trợ **6 ngôn ngữ**: Tiếng Việt (🇻🇳), Tiếng Anh (🇺🇸), Tiếng Trung (🇨🇳), Tiếng Tây Ban Nha (🇪🇸), Tiếng Bồ Đào Nha (🇵🇹), Tiếng Pháp (🇫🇷).
- Bộ nạp RAM O(1) siêu nhanh đồng bộ chuẩn **1187 keys dịch/ngôn ngữ** (100% không lệch key giữa các file).
- Tự động fallback linh hoạt về ngôn ngữ mặc định nếu thiếu key.
- Thay đổi ngôn ngữ dễ dàng bằng lệnh `/lang` hoặc trực tiếp trên Web Dashboard.

### 🧠 2. Trí Tuệ Nhân Tạo (AI Assistant & Chatbot)
- **Tích hợp mô hình AI hiện đại**: Gemini, OpenAI, Claude với khả năng hội thoại thông minh, tóm tắt tin nhắn kênh chat (`/ai summarize`) và trả lời câu hỏi (`/ai ask`).
- **Tùy biến nhân cách AI**: Lựa chọn các preset phong cách (thân thiện, hài hước, chuyên nghiệp, Tsundere) hoặc nhập system prompt riêng biệt theo từng Server.
- **Hỗ trợ Multi-Key & Channel Lock**: Khóa kênh chat AI riêng biệt và quản lý API Key linh hoạt.

### 🔊 3. Kênh Voice Tạm Thời (TempVoice Hub)
- **Cơ chế Join-to-Create**: Tự động tạo phòng Voice riêng biệt khi thành viên tham gia vào kênh Hub.
- **Bảng điều khiển tương tác (Interactive Control Panel)**: Đổi tên phòng, đặt giới hạn số người (User Limit), Khóa/Mở phòng Voice (`/voice lock`, `/voice unlock`, `/voice limit`, `/voice rename`).
- **Tự động dọn dẹp (Auto Cleanup)**: Tự động xóa phòng Voice rác ngay khi không còn ai trong phòng.

### 💰 4. Hệ Thống Kinh Tế Ảo (Virtual Economy & Shop)
- **Hệ thống tiền tệ ảo**: Lệnh `/balance`, `/daily` (hỗ trợ tính chuỗi streak nhận thưởng thêm), `/transfer` chuyển tiền giữa các thành viên.
- **Cửa hàng máy chủ (Server Shop)**: Lệnh `/shop` và `/buy` cho phép mua các Role phần thưởng độc quyền với số lượng giới hạn (Stock limit).

### 💬 5. Lệnh Tùy Biến (Custom Commands & Auto-Responders)
- **Tạo phản hồi tự động**: Lệnh `/customcmd add`, `/customcmd list`, `/customcmd delete` hỗ trợ đối sánh từ khóa linh hoạt (`exact`, `contains`, `startswith`).
- **Thống kê lượt sử dụng**: Theo dõi chi tiết số lần kích hoạt của từng lệnh trên Dashboard.

### 🎵 6. Module Nhạc Siêu Tốc & Lofi 24/7 (Music Pipeline)
- **Tối ưu hóa âm thanh ARM**: Mã hóa trực tiếp bằng `FFmpegOpusAudio` (giảm 50% CPU), cờ đệm tối ưu hóa giúp **khởi động bài hát < 0.8 giây**.
- **Tự động phân giải link Spotify**: Hỗ trợ dán trực tiếp URL `spotify.com/track/...` ➔ phân giải thành từ khóa YouTube trong < 0.2s.
- **Khóa đồng bộ chống xung đột (Atomic Play Lock)**: Loại bỏ triệt để lỗi `Already playing audio` khi người dùng spam lệnh.
- **Tự động ngắt kết nối (Inactivity Watchdog)**: Tự động rời kênh voice sau 3 phút nếu không có bài hát nào được phát để giải phóng tài nguyên.
- **Điều khiển phong phú**: Bổ sung lệnh `/volume <1-150>` (chỉnh âm lượng sống động), `/shuffle` (trộn ngẫu nhiên hàng chờ), `/replay`, `/lofi` (SomaFM & YouTube Radio), quản lý Playlist cá nhân & máy chủ.
- **Giao diện Compact Interactive View**: Embed hiển thị nhỏ gọn kèm thanh trạng thái và nút bấm tương tác trực quan.

### 🛡️ 7. Kiểm Duyệt Tự Động (AutoMod)
- **Bộ lọc đa lớp**: Anti-Spam (cửa sổ trượt 5s), Banned Words Filter, Fake Link / Phishing Filter, Anti-Invite Links, Anti-Caps Lock (>70%), Anti-Mass Ping.
- **Phạt tự động**: Cảnh cáo công khai + DM chi tiết, Tạm khóa chat (Timeout) linh hoạt từ 1 phút đến 24 giờ.
- **Whitelist**: Hỗ trợ Role Whitelist & Channel Whitelist linh hoạt.

### 🎫 8. Hệ Thống Support Ticket (Ticket System)
- Tạo nhiều bảng Ticket tương tác với nút bấm tuỳ chỉnh màu sắc & biểu tượng.
- Tạo kênh chat riêng tư kèm phân quyền bảo mật chặt chẽ cho đội ngũ Support.
- Quy trình Đóng / Xóa ticket có đếm ngược trực quan và ghi log chi tiết.

### ⭐ 9. Hệ Thống Cấp Độ (Leveling & Rank Cards)
- Tính điểm XP linh hoạt từ Chat text (cooldown 60s) và Voice channel (quét định kỳ 90s).
- Tạo ảnh thẻ Rank Card trực quan bằng thư viện Pillow (`PIL`).
- Tự động trao Role phần thưởng khi đạt mốc Level (hỗ trợ tích lũy Role hoặc thay thế).
- Quản trị viên dễ dàng quản lý XP với các lệnh `/xp add`, `/xp set`, `/xp reset`.

### 🎉 10. Giveaway Tự Động
- Khởi tạo & quản lý sự kiện nhận quà bằng lệnh `/giveaway start/end/reroll`.
- Nút bấm tham gia thời gian thực, tự động cập nhật số lượng người tham gia.
- Cơ chế bảo vệ chống race-condition (tránh trao giải lặp lại 2 lần).

### 🌐 11. Web Dashboard Quản Trị Server (Flask + Discord OAuth2)
- **Giao diện Midnight Violet Slate (`#120e24`) & CSS v9.2**: Thiết kế kính mờ Glassmorphism sang trọng, ấm áp, chống mỏi mắt.
- **Bảo Mật & Điều Khoản Chuyên Nghiệp**: Trang Điều khoản dịch vụ (`/tos`) và Chính sách bảo mật (`/privacy`) chuẩn pháp lý với thanh mục lục cố định (Sticky TOC) và hỗ trợ in/xuất PDF.
- **Trang Admin dành cho Bot Owner (`/admin`)**:
  - Xem danh sách máy chủ active, phát thông báo Broadcast toàn hệ thống, Kick/Blacklist server vi phạm.
  - **Web Terminal**: Nhập lệnh shell trực tiếp trên trình duyệt (tương thích 100% Android Termux/Linux).
  - **Git Pull & Restart 1-Click**: Cập nhật mã nguồn từ GitHub và khởi động lại bot ngay trên Web.

### 📜 12. Các Module Khác
- 🎭 **Reaction Roles**: Tự động cấp Role qua Reaction hoặc Button.
- 📊 **Audit Logger**: Ghi log chi tiết tin nhắn sửa/xóa, thành viên ra/vào, kick/ban, thay đổi Role, kênh, ticket.
- 🤖 **Auto Roles**: Tự động cấp Role ban đầu cho User và Bot khi tham gia server.
- 📈 **Real-time Stats**: Thống kê số lượng tin nhắn, thành viên ra vào theo từng giờ cho biểu đồ Dashboard.
- 🛠️ **Utility & Info**: Menu `/help` tương thích 6 ngôn ngữ, `/ping`, `/membercount`, `/serverinfo`, `/userinfo`, `/avatar`, `/poll`, `/roll`, `/choose`.

---

## 🛠️ Công Nghệ Sử Dụng

- **Ngôn ngữ**: Python 3.10+
- **Bot Engine**: `discord.py` 2.3+ (App Commands / Slash Commands)
- **Web Framework**: Flask (Jinja2 Templates)
- **Cơ sở dữ liệu**: SQLite (`aiosqlite` async cho Bot, `sqlite3` sync cho Dashboard, WAL mode, timeout=15s)
- **Cache Layer**: Pure Python In-Memory RAM Cache (`MemoryCache` thread-safe & async-safe với TTL LRU eviction và daemon cleanup 5 phút, không cần Redis)
- **Xử lý Âm thanh**: `yt-dlp` + `FFmpegOpusAudio`
- **Đồ họa**: Pillow (`PIL`)

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Bot

### 1. Tải Source Code & Cài Đặt Thư Viện

```bash
# Clone repository về máy
git clone https://github.com/namokla2005/ZerynBot.git
cd ZerynBot

# Cài đặt các thư viện Python cần thiết
pip install -r requirements.txt
```

### 2. Cấu Hình Biến Môi Trường (`.env`)

Sao chép file mẫu `.env.example` thành `.env` và điền thông tin của bạn:

```bash
cp .env.example .env
```

Nội dung `.env` mẫu:
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
BOT_OWNER_ID=your_discord_user_id
FLASK_SECRET_KEY=your_random_secret_key
DASHBOARD_URL=http://localhost:5000
REDIRECT_URI=http://localhost:5000/callback
WEBHOOK_LOG_URL=https://discord.com/api/webhooks/...
STATUS_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

---

## 💻 Hướng Dẫn Khởi Chạy (`main.py`)

Hệ thống được điều khiển tập trung thông qua `main.py`:

```bash
# 🚀 Khởi chạy toàn bộ hệ thống (Bot, Dashboard, Watchdog)
python main.py

# 📊 Kiểm tra trạng thái các dịch vụ đang chạy
python main.py --status

# 🛑 Dừng sạch tất cả dịch vụ
python main.py --stop

# 🔄 Khởi động lại toàn bộ dịch vụ
python main.py --restart

# 🤖 Chỉ khởi chạy Discord Bot
python main.py --bot

# ⚡ Chạy Bot & Đồng bộ lại Slash Commands với Discord
python main.py --sync

# 🌐 Chỉ khởi chạy Web Dashboard (HTTP localhost:5000)
python main.py --dashboard

# 🧪 Chạy Self-Diagnostic Tester kiểm tra hệ thống
python main.py --test
```

---

## 📂 Cấu Trúc Thư Mục Dự Án

```text
ZerynBot/
├── ARCHITECTURE.md      # Tài liệu chi tiết kiến trúc dự án (dành cho Developer & AI)
├── main.py              # Điểm vào điều khiển trung tâm (start/stop/restart/status/test)
├── config.py            # Quản lý cấu hình & biến môi trường
├── database.py          # Xử lý cơ sở dữ liệu SQLite (WAL mode, async & sync, timeout 15s)
├── cache.py             # Bộ quản lý In-Memory RAM Cache (thread-safe, TTL, 5min periodic cleanup)
├── i18n.py              # Động cơ dịch đa ngôn ngữ O(1) RAM-cached (1187 keys/file)
├── requirements.txt     # Danh sách thư viện Python
├── .agents/             # Skill & Cấu hình dành cho Trợ lý AI
├── bot/                 # 🤖 Discord Bot Source Code
│   ├── bot.py           # Entry point của Discord Bot & Webhook Logger
│   ├── card_generator.py# Render ảnh Rank Card, Welcome/Goodbye Banner bằng Pillow
│   ├── checks.py        # Kiểm tra quyền hạn & Bot Admin
│   └── cogs/            # 18 Cogs chức năng (ai, tempvoice, economy, customcommands, music, automod, ...)
├── dashboard/           # 🌐 Flask Web Dashboard
│   ├── app.py           # Routes chính của Dashboard
│   ├── api.py           # AJAX API Endpoints
│   ├── auth.py          # Discord OAuth2 Session Manager
│   ├── static/          # CSS (v9.2), JS, Branding Images
│   └── templates/       # Giao diện HTML Jinja2 (Midnight Violet Slate theme)
├── locales/             # 🌐 6 File từ điển ngôn ngữ JSON (vi, en, zh, es, pt, fr) - 1187 keys/file
├── scripts/             # Scripts hỗ trợ (send_status.py, watchdog.sh, termux_boot.sh)
└── data/                # Nơi lưu trữ dữ liệu sqlite bot.db, log file & health.json
```

---

## 📄 Giấy Phép & Đóng Góp

Dự án được phát hành theo giấy phép **MIT License**. Mọi đóng góp (Pull Request / Issue) đều được hoan nghênh!

> Made with ❤️ by **Nam** — Optimized for low-spec ARM devices & Termux 24/7.

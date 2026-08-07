# 🤖 ZerynBot V2 — Discord Bot & Web Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Discord.py-2.3%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py">
  <img src="https://img.shields.io/badge/Flask-Web%20Dashboard-black?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/i18n-6%20Languages-orange?style=for-the-badge&logo=translate&logoColor=white" alt="i18n 6 Languages">
  <img src="https://img.shields.io/badge/Optimized-ARM%20%2F%20Termux-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Termux Optimized">
</p>

**ZerynBot V2** là một Discord Bot đa chức năng thế hệ mới tích hợp **Web Dashboard quản trị server**, hỗ trợ **Đa ngôn ngữ (i18n)** toàn diện và được tối ưu hóa đặc biệt để vận hành 24/7 mượt mà trên các thiết bị cấu hình thấp (như máy tính bảng Android chạy **Termux**, Raspberry Pi hoặc VPS giá rẻ).

---

## 📚 Tài Liệu Kiến Trúc (Cho Developers & AI)

Dự án có sẵn tài liệu kiến trúc kỹ thuật chi tiết dành cho các lập trình viên và trợ lý AI:
- 📖 [**ARCHITECTURE.md**](./ARCHITECTURE.md) — Sơ đồ kiến trúc, cơ sở dữ liệu SQLite, luồng dữ liệu, quy tắc đa ngôn ngữ và danh sách anti-patterns cần tránh.

---

## ✨ Tính Năng Nổi Bật

### 🌍 1. Đa Ngôn Ngữ Hoàn Toàn (Full i18n Engine)
- Hỗ trợ **6 ngôn ngữ**: Tiếng Việt (🇻🇳), Tiếng Anh (🇺🇸), Tiếng Trung (🇨🇳), Tiếng Tây Ban Nha (🇪🇸), Tiếng Bồ Đào Nha (🇵🇹), Tiếng Pháp (🇫🇷).
- Bộ nạp RAM O(1) siêu nhanh với 856+ keys dịch/ngôn ngữ.
- Tự động fallback linh hoạt về ngôn ngữ mặc định nếu thiếu key.
- Thay đổi ngôn ngữ dễ dàng bằng lệnh `/lang` hoặc trực tiếp trên Web Dashboard.

### 🎵 2. Module Nhạc Hifi & Lofi (Music Player)
- **Tối ưu hóa âm thanh ARM**: Mã hóa trực tiếp bằng `FFmpegOpusAudio` (giảm 50% CPU), dải băng tầng Discord Voice 96kbps/64kbps.
- **Giao diện Compact Interactive View**: Embed hiển thị nhỏ gọn kèm bộ nút bấm phẳng trực quan (Tạm dừng, Bỏ qua, Dừng, Lặp bài, Autoplay).
- **Playlist & Streaming**: Tải background siêu nhanh, hỗ trợ phát Lofi 24/7 (SomaFM & YouTube Radio), tạo và lưu Playlist riêng per-server.
- **Tự động làm tươi Stream URL**: Loại bỏ lỗi 403 HTTP khi phát danh sách phát dài.

### 🛡️ 3. Kiểm Duyệt Tự Động (AutoMod)
- **Bộ lọc đa lớp**: Anti-Spam (cửa sổ trượt 5s), Banned Words Filter, Fake Link / Phishing Filter, Anti-Invite Links, Anti-Caps Lock (>70%), Anti-Mass Ping.
- **Phạt tự động**: Cảnh cáo công khai + DM chi tiết, Tạm khóa chat (Timeout) linh hoạt từ 1 phút đến 24 giờ.
- **Whitelist**: Hỗ trợ Role Whitelist & Channel Whitelist linh hoạt.

### 🎫 4. Hệ Thống Support Ticket (Ticket System)
- Tạo nhiều bảng Ticket tương tác với nút bấm tuỳ chỉnh màu sắc & biểu tượng.
- Tạo kênh chat riêng tư kèm phân quyền bảo mật chặt chẽ cho đội ngũ Support.
- Quy trình Đóng / Xóa ticket có đếm ngược trực quan và ghi log chi tiết.

### ⭐ 5. Hệ Thống Cấp Độ (Leveling & Rank Cards)
- Tính điểm XP linh hoạt từ Chat text (cooldown 60s) và Voice channel (quét định kỳ 90s).
- Tạo ảnh thẻ Rank Card trực quan bằng thư viện Pillow (`PIL`).
- Tự động trao Role phần thưởng khi đạt mốc Level (hỗ trợ tích lũy Role hoặc thay thế).

### 🎉 6. Giveaway Tự Động
- Khởi tạo & quản lý sự kiện nhận quà bằng lệnh `/giveaway start/end/reroll`.
- Nút bấm tham gia thời gian thực, tự động cập nhật số lượng người tham gia.
- Cơ chế bảo vệ chống race-condition (tránh trao giải lặp lại 2 lần).

### 🌐 7. Web Dashboard Quản Trị Server (Flask + Discord OAuth2)
- Đăng nhập an toàn qua Discord OAuth2.
- Giao diện Dark Mode sang trọng, tương thích điện thoại & máy tính.
- Bật/tắt từng Module, chỉnh sửa câu chào mừng/tạm biệt, cấu hình AutoMod, Ticket, Logger, Auto Roles.
- **Trang Admin dành cho Bot Owner**: Xem danh sách máy chủ active, phát thông báo Broadcast toàn hệ thống, Kick/Blacklist server vi phạm.

### 📜 8. Các Module Khác
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
- **Cơ sở dữ liệu**: SQLite (`aiosqlite` async cho Bot, `sqlite3` sync cho Dashboard)
- **Cache Layer**: Redis Cache (`redis-py` & `redis.asyncio`) với chế độ tự động fallback về DB
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
REDIS_URL=redis://localhost:6379/0
```

---

## 💻 Hướng Dẫn Khởi Chạy (`main.py`)

Hệ thống được điều khiển tập trung thông qua `main.py`:

```bash
# 🚀 Khởi chạy toàn bộ hệ thống (Redis, Bot, Dashboard, Watchdog)
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
```

### Khởi Chạy Trên Linux / Termux (Tự Động)

Dùng script khởi động được tối ưu sẵn cho Android Termux & Linux:

```bash
chmod +x start.sh
bash start.sh
```

---

## 📂 Cấu Trúc Thư Mục Dự Án

```text
ZerynBot/
├── ARCHITECTURE.md      # Tài liệu chi tiết kiến trúc dự án (dành cho Developer & AI)
├── main.py              # Bộ điều khiển trung tâm (start/stop/restart/status)
├── config.py            # Quản lý cấu hình & biến môi trường
├── database.py          # Xử lý cơ sở dữ liệu SQLite (WAL mode, async & sync)
├── cache.py             # Bộ quản lý bộ nhớ đệm Redis (kèm fallback DB)
├── i18n.py              # Động cơ dịch đa ngôn ngữ O(1) RAM-cached
├── start.sh             # Script khởi chạy tự động trên Linux / Termux
├── requirements.txt     # Danh sách thư viện Python
├── .agents/             # Skill & Cấu hình dành cho Trợ lý AI
├── bot/                 # 🤖 Discord Bot Source Code
│   ├── bot.py           # Entry point của Discord Bot & Webhook Logger
│   ├── card_generator.py# Render ảnh Rank Card, Welcome/Goodbye Banner bằng Pillow
│   ├── checks.py        # Kiểm tra quyền hạn & Bot Admin
│   └── cogs/            # 14 Cogs chức năng (music, automod, leveling, ticket, giveaway, ...)
├── dashboard/           # 🌐 Flask Web Dashboard
│   ├── app.py           # Routes chính của Dashboard
│   ├── api.py           # AJAX API Endpoints
│   ├── auth.py          # Discord OAuth2 Session Manager
│   ├── static/          # CSS, JS, Branding Images
│   └── templates/       # Giao diện HTML Jinja2
├── locales/             # 🌐 6 File từ điển ngôn ngữ JSON (vi, en, zh, es, pt, fr)
├── scripts/             # Scripts hỗ trợ (send_status.py, watchdog.sh, termux_boot.sh)
└── data/                # Nơi lưu trữ dữ liệu sqlite bot.db, log file & health.json
```

---

## 📄 Giấy Phép & Đóng Góp

Dự án được phát hành theo giấy phép **MIT License**. Mọi đóng góp (Pull Request / Issue) đều được hoan nghênh!

> Made with ❤️ by **Nam** — Optimized for low-spec ARM devices & Termux 24/7.

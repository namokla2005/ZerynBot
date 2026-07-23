# 🤖 ZerynBot V2 — Discord Bot & Web Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Discord.py-2.3%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py">
  <img src="https://img.shields.io/badge/Flask-Web%20Dashboard-black?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/Optimized-ARM%20%2F%20Termux-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Termux Optimized">
</p>

**ZerynBot V2** là một Discord Bot đa chức năng thế hệ mới tích hợp **Web Dashboard quản trị server**, được tối ưu hóa đặc biệt để vận hành 24/7 mượt mà trên các thiết bị cấu hình thấp (như máy tính bảng Android chạy **Termux**, Raspberry Pi hoặc VPS giá rẻ).

---

## ✨ Tính Năng Nổi Bật

### 🎵 1. Module Nhạc Hifi (Music Cog)
- **Tối ưu hóa âm thanh**: Mã hóa trực tiếp bằng `FFmpegOpusAudio` (giảm 50% CPU), khớp chính xác dải băng tầng Discord Voice 64kbps.
- **Giao diện Compact Card**: Embed hiển thị theo phong cách thẻ nhỏ gọn, hình ảnh góc trên bên phải, thanh tiến trình trực quan và dải nút điều khiển phẳng (Pause, Skip, Stop, Loop).
- **Tải Playlist Siêu Nhanh (Background Loading)**: Phát ngay bài đầu tiên sau 1-2s, nạp ngầm các bài còn lại ở background mà không làm gián đoạn trải nghiệm người nghe.
- **Tự động làm tươi Stream URL**: Loại bỏ hoàn toàn lỗi 403 HTTP khi xếp hàng danh sách phát dài.
- **Khắc phục biến động nhịp độ**: Bộ lọc `aresample=async=1` giữ 100% tốc độ gốc của bản nhạc (1.0x).

### 🛡️ 2. Hệ Thống Kiểm Duyệt Tự Động (AutoMod)
- Bộ lọc thông minh: **Anti-Invite link**, **Anti-Caps Lock (>70%)**, **Anti-Mention Spam (>5 thần dân)**.
- Xử lý phạt linh hoạt: Cảnh cáo, xóa tin nhắn, hoặc Tạm khóa chat (Timeout) với các tùy chọn thời gian từ 1 phút đến 24 giờ.
- Tùy chỉnh bật/tắt toàn bộ tính năng dễ dàng trực tiếp từ **Web Dashboard**.

### 🌐 3. Web Dashboard Quản Trị Server (Flask + Discord OAuth2)
- Đăng nhập an toàn qua Discord OAuth2.
- Giao diện người dùng sang trọng, tương thích điện thoại & máy tính.
- Quản lý thiết lập Server, AutoMod, Danh sách phát (Playlist), xem Log hoạt động trực tuyến.

### 🧪 4. Tự Động Chẩn Đoán Khi Khởi Động (Self-Diagnostic Tester)
- Bộ công cụ kiểm thử tự động 11/11 module cốt lõi trước khi bot chính thức Online.
- Phát hiện lỗi sớm và gửi báo cáo lỗi chi tiết về **Discord Webhook**.

---

## 🛠️ Công Nghệ Sử Dụng

- **Ngôn ngữ**: Python 3.10+
- **Thư viện Bot**: `discord.py` 2.3+ (App Commands / Slash Commands)
- **Web Framework**: Flask
- **Cơ sở dữ liệu**: SQLite (`aiosqlite` async) + Redis Cache (tùy chọn)
- **Xử lý Âm thanh**: `yt-dlp` + `FFmpeg`

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

Sao chép file mẫu `.env.example` thành `.env` và điền các thông tin credentials của bạn:

```bash
cp .env.example .env
```

Nội dung `.env` cần thiết:
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
FLASK_SECRET_KEY=your_random_secret_key
DASHBOARD_URL=http://localhost:5000
REDIRECT_URI=http://localhost:5000/callback
WEBHOOK_LOG_URL=https://discord.com/api/webhooks/...
```

---

## 💻 Hướng Dẫn Khởi Chạy

### 1. Chạy Discord Bot

```bash
# Khởi động thường (nhanh, dùng khi chạy hàng ngày)
python bot/bot.py

# Khởi động kèm Sync Slash Commands (dùng khi thêm lệnh mới)
python bot/bot.py --sync
```

### 2. Chạy Web Dashboard

```bash
python run_dashboard.py
```
Sau đó truy cập trình duyệt tại địa chỉ: `http://localhost:5000`

### 3. Khởi Chạy Trên Termux / Linux (Tự Động)

Dùng script khởi động được tối ưu sẵn cho Android Termux:

```bash
chmod +x start.sh
bash start.sh
```

---

## 📂 Cấu Trúc Thư Mục Dự Án

```text
ZerynBot/
├── bot/
│   ├── cogs/            # Các module chức năng (music, automod, leveling, info, ...)
│   ├── bot.py           # Entry point của Discord Bot
│   └── tester.py        # Module tự động chẩn đoán hệ thống khi khởi động
├── dashboard/
│   ├── templates/       # Giao diện HTML (Jinja2)
│   ├── static/          # CSS, JavaScript, Hình ảnh
│   └── app.py           # Entry point của Flask Web Dashboard
├── database.py          # Xử lý cơ sở dữ liệu Async SQLite
├── cache.py             # Bộ quản lý bộ nhớ đệm Redis / RAM fallback
├── config.py            # Quản lý cấu hình & biến môi trường
├── start.sh             # Script khởi chạy tự động trên Linux / Termux
└── requirements.txt     # Danh sách thư viện Python
```

---

## 📄 Giấy Phép & Đóng Góp

Dự án được phát hành theo giấy phép **MIT License**. Mọi đóng góp (Pull Request / Issue) đều được hoan nghênh!

> Made with ❤️ by **Nam** — Optimized for low-spec ARM devices & Termux 24/7.

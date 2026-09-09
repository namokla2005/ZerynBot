# 🤖 Zeryn (ZerynBot V2) — Discord Bot & Web Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Discord.py-2.3%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py">
  <img src="https://img.shields.io/badge/Flask-Web%20Dashboard-black?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/i18n-6%20Languages%20(1587%20Keys)-orange?style=for-the-badge&logo=translate&logoColor=white" alt="i18n 6 Languages">
  <img src="https://img.shields.io/badge/Modules-20%20Active%20Modules-57F287?style=for-the-badge&logo=probot&logoColor=white" alt="20 Modules">
  <img src="https://img.shields.io/badge/Commands-103%20Slash%20Commands-blueviolet?style=for-the-badge&logo=discord&logoColor=white" alt="103 Commands">
  <img src="https://img.shields.io/badge/Cache-In--Memory%20RAM-purple?style=for-the-badge&logo=fastapi&logoColor=white" alt="Pure Python In-Memory Cache">
  <img src="https://img.shields.io/badge/Optimized-ARM%20%2F%20Termux-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Termux Optimized">
</p>

**Zeryn** (ZerynBot V2) là một Discord Bot đa chức năng thế hệ mới tích hợp **Web Dashboard quản trị server (20 Modules & 103 Lệnh)**, hỗ trợ **Đa ngôn ngữ (i18n)** toàn diện (6 thứ tiếng), bộ nhớ đệm **In-Memory RAM Cache** thuần Python siêu nhẹ và được tối ưu hóa đặc biệt để vận hành 24/7 mượt mà trên các thiết bị cấu hình thấp (như máy tính bảng Android chạy **Termux**, Raspberry Pi hoặc VPS giá rẻ).

---

## ✨ Tính Năng Nổi Bật

### 🌍 1. Đa Ngôn Ngữ Hoàn Toàn (Full i18n Engine)
- Hỗ trợ **6 ngôn ngữ**: Tiếng Việt (🇻🇳), Tiếng Anh (🇺🇸), Tiếng Trung (🇨🇳), Tiếng Tây Ban Nha (🇪🇸), Tiếng Bồ Đào Nha (🇵🇹), Tiếng Pháp (🇫🇷).
- Bộ nạp RAM O(1) siêu nhanh đồng bộ chuẩn **1587 keys dịch/ngôn ngữ** (100% không lệch key giữa các file).
- Tự động fallback linh hoạt về ngôn ngữ mặc định nếu thiếu key.
- Thay đổi ngôn ngữ dễ dàng bằng lệnh `/lang` hoặc trực tiếp trên Web Dashboard.

### 🛡️ 2. Bộ Lệnh Điều Hành & Xử Phạt Thủ Công (Moderation Suite)
- **Xử lý thành viên**: `/kick`, `/ban`, `/unban`, `/timeout` (khóa chat `10m`, `2h`, `1d`), `/untimeout`.
- **Hệ thống Cảnh Cáo Leo Thang**: `/warn` (3 cảnh cáo = Mute 1h, 5 cảnh cáo = Kick), `/warnings`, `/delwarn`.
- **Quản lý kênh chat**: `/clear` (xóa tin nhắn hàng loạt theo số lượng hoặc người dùng), `/slowmode`, `/lock`, `/unlock`.
- **Trang Dashboard chuyên dụng**: Cấu hình kênh Mod Log, theo dõi tổng số lượt cảnh cáo và xem quy tắc phạt tự động.

### 🎭 3. Tương Tác Anime & Tình Cảm / Hôn Nhân (Anime Fun & Social)
- **10 Hành động Anime GIF (`nekos.best` API)**: `/hug`, `/pat`, `/kiss`, `/slap`, `/feed`, `/cuddle`, `/poke`, `/highfive`, `/cry`, `/dance`.
- **Hôn Nhân & Ghép Đôi**: `/ship` (đoán % hợp đôi), `/marry` (cầu hôn qua nút bấm tương tác Button Đồng ý/Từ chối), `/divorce`, `/profile` (thẻ hồ sơ tình cảm).

### 🎂 4. Quản Lý & Chúc Mừng Sinh Nhật (Birthday Engine)
- **Lệnh cá nhân**: `/birthday set <ngày> <tháng> [năm]`, `/birthday check`, `/birthday list`, `/birthday remove`.
- **Tác vụ chúc mừng tự động 00:00 hàng ngày**: Gửi Embed chúc mừng rực rỡ, trao role **Birthday VIP** (tự gỡ sau 24h), tặng Coins ngân hàng & XP.
- **Trang Dashboard chuyên dụng**: Tùy chỉnh kênh thông báo, role quà tặng, số tiền thưởng Coins, XP và mẫu lời chúc mừng `{user}` / `{server}`.

### ⏰ 5. Nhắc Nhở & Hẹn Giờ Thông Minh (Smart Reminders)
- Hẹn giờ linh hoạt bằng lệnh `/remindme`: hỗ trợ mốc thời gian đa dạng (`10m`, `1h30m`, `2d`, hoặc mốc giờ cụ thể trong ngày như `20:30`).
- Tự động gửi thông báo ping trực tiếp tại kênh chat hoặc qua tin nhắn riêng (DM).
- Quản lý danh sách lịch hẹn với `/reminders` và hủy hẹn giờ với `/delreminder <id>`.

### 🧠 6. Trí Tuệ Nhân Tạo (AI Assistant & Chatbot)
- **Tích hợp mô hình AI hiện đại**: Groq Cloud (`qwen/qwen3.8-27b`, `gpt-oss-20b`, `compound`), Google Gemini (`gemini-2.0-flash`, `gemini-1.5-pro`), OpenRouter với khả năng đàm thoại thông minh, nhận diện hình ảnh (Multimodal Vision), tóm tắt tin nhắn kênh chat (`/summarize`) và trả lời câu hỏi (`/ask`).
- **Tra cứu Web thời gian thực (Web Search Grounding)**: Hỗ trợ cờ `web: True` trong lệnh `/ask` tự động tìm kiếm thông tin mới nhất qua DuckDuckGo.
- **Tóm tắt bài viết URL an toàn**: Lệnh `/summarize url:<link>` trích xuất và tóm tắt nội dung trang web với lớp bảo vệ **SSRF Guard** chống tấn công mạng nội bộ.
- **Tùy biến nhân cách AI (Custom System Prompt)**: Lựa chọn các preset phong cách (thân thiện, hài hước, chuyên nghiệp, Tsundere) hoặc nhập prompt riêng biệt theo từng Server ngay trên Dashboard.
- **Hỗ trợ Multi-Key & Channel Lock**: Khóa kênh chat AI riêng biệt và quản lý API Key linh hoạt.

### 🔊 7. Kênh Voice Tạm Thời (TempVoice Hub)
- **Cơ chế Join-to-Create**: Tự động tạo phòng Voice riêng biệt khi thành viên tham gia vào kênh Hub.
- **Bảng điều khiển tương tác (Interactive Control Panel)**: Đổi tên phòng, đặt giới hạn số người (User Limit), Khóa/Mở phòng Voice (`/voice lock`, `/voice unlock`, `/voice limit`, `/voice rename`).
- **Tự động dọn dẹp (Auto Cleanup)**: Tự động xóa phòng Voice rác ngay khi không còn ai trong phòng.

### 💰 8. Hệ Thống Kinh Tế Ảo, Nghề Nghiệp & Ngân Hàng (Virtual Economy 2.0)
- **Tách biệt Ví (Wallet) & Ngân hàng (Bank)**:
  - 💵 **Tiền mặt Ví (Wallet)**: Dùng để chuyển tiền (`/pay`), tham gia mini-games giải trí (`/coinflip`, `/slots`, `/blackjack`). Mini-games **chỉ trừ tiền trong Ví**; tài sản trong Ngân hàng luôn an toàn 100%.
  - 🏦 **Tài khoản Ngân hàng (Bank)**: Nơi giữ tiền an toàn và dùng để thanh toán mua sắm Role trong Cửa hàng Server (`/shop`, `/buy`).
- **Nghề Nghiệp & Thu Thập Vật Phẩm (Kinh Tế 2.0)**:
  - `/work`: Làm việc chăm chỉ nhận tiền lương và tích lũy coin.
  - `/fish` & `/hunt`: Đi câu cá hoặc săn thú với xác suất nhận vật phẩm theo cấp độ hiếm (Common, Uncommon, Rare, Epic, Legendary).
  - `/inventory`: Xem túi đồ cá nhân chứa các vật phẩm đã thu thập.
  - `/sell <item>` / `/sell all`: Bán một hoặc toàn bộ vật phẩm trong túi đồ đổi lấy tiền mặt vào Ví.
- **Lệnh Nạp & Rút Tiền Linh Hoạt**:
  - `/deposit <amount>` (hoặc `/dep all`): Nạp tiền mặt từ Ví vào tài khoản Ngân hàng.
  - `/withdraw <amount>` (hoặc `/with all`): Rút tiền từ Ngân hàng về Ví khi cần cá cược hoặc chuyển khoản.
- **Tiện ích kinh tế**: Lệnh `/balance` (hiển thị chi tiết Ví, Ngân hàng, Tổng tài sản), `/daily` (nhận thưởng và chuỗi streak), `/rich` (Bảng xếp hạng đại gia).

### 🎵 9. Module Nhạc Siêu Tốc & Giao Diện Thẻ Hiện Đại (Music Pipeline & Compact Player)
- **Giao diện Compact Card đỉnh cao (Music | 2 Style)**: Thẻ phát nhạc màu xanh Neon tinh tế, **Thumbnail góc phải**, thanh sóng nhạc nét đậm **Progress Bar 45 ký tự** `[**━━━━**](...)**━━━━**` và thanh thông số Volume/Queue/Duration trực quan.
- **Hàng 5 Nút Điều Khiển Tương Tác**:
  - `♾️ Autoplay`: Tự động tìm kiếm và phát tiếp bài hát cùng thể loại khi hết hàng chờ (lọc bỏ lịch sử bài đã phát).
  - `⏹️ Dừng lại`: Dừng phát và rời kênh voice.
  - `⏸️ Tạm dừng / ▶️ Tiếp tục`: Chuyển đổi trạng thái phát nhạc.
  - `⏭️ Bỏ qua`: Chuyển ngay sang bài tiếp theo.
  - `🔁 Lặp lại`: 3 chế độ thông minh (`Lặp lại: Tắt` ➔ `🔂 Lặp 1 bài` ➔ `🔁 Lặp toàn bộ`).
- **Lệnh `/nowplaying` (`/np`)**: Tra cứu thông tin bài hát và vị trí phát theo thời gian thực.
- **Tối ưu hóa âm thanh ARM & yt-dlp**: Mã hóa trực tiếp bằng `FFmpegOpusAudio` (giảm 50% CPU), cờ tối ưu `-threads 1 -fflags +genpts -probesize 512K -analyzeduration 500000 -af aresample=async=1:first_pts=0` triệt tiêu giật lag âm thanh và chống drift PTS. Client yt-dlp chuẩn `["android", "web"]` khắc phục triệt để lỗi YouTube *"The page needs to be reloaded"*.
- **Bộ nhớ đệm 2 tầng (Dual-tier Cache)**: Kết hợp In-Memory RAM Cache (`cache.py`) và SQLite Disk Cache (`music_song_cache` với TTL 6 giờ). Khởi động phát lại tức thì (< 0.5s) ngay cả sau khi bot khởi động lại.
- **Trích xuất song song (Concurrent Extraction)**: Khởi chạy đồng thời kết nối Voice Channel và trích xuất luồng audio (`extract_info`), giảm 50% độ trễ khởi động bài hát ban đầu.
- **Tự động phân giải link Spotify**: Hỗ trợ dán trực tiếp URL `spotify.com/track/...` ➔ phân giải thành từ khóa YouTube trong < 0.2s.
- **Khóa đồng bộ chống xung đột (Atomic Play Lock)**: Loại bỏ triệt để lỗi `Already playing audio` khi người dùng spam lệnh.
- **Tự động ngắt kết nối (Inactivity Watchdog)**: Tự động rời kênh voice sau 3 phút nếu không có bài hát nào được phát để giải phóng tài nguyên.
- **Điều khiển phong phú**: Lệnh `/volume <1-150>`, `/shuffle`, `/autoplay`, `/loop`, `/replay`, `/lofi` (SomaFM & YouTube Radio), quản lý Playlist cá nhân & máy chủ.

### 🛡️ 10. Kiểm Duyệt Tự Động & Chống Phá Hoại (AutoMod, Anti-Raid & Anti-Nuke)
- **Bộ lọc đa lớp**: Anti-Spam (cửa sổ trượt 5s), Banned Words Filter, Fake Link / Phishing Filter, Anti-Invite Links, Anti-Caps Lock (>70%), Anti-Mass Ping.
- **Hệ thống Chống Đột Nhập (Anti-Raid)**: Tự động đếm tần suất join thành viên mới theo cửa sổ thời gian; tự động kích hoạt chế độ phong tỏa khẩn cấp (Lockdown) và trừng phạt bot rác.
- **Hệ thống Chống Phá Hoại (Anti-Nuke)**: Giám sát thời gian thực các hành vi nguy hiểm như xóa kênh, xóa vai trò hàng loạt; tự động thu hồi quyền hạn và ban tài khoản tấn công.
- **Phạt tự động & Whitelist**: Cảnh cáo công khai + DM chi tiết, Tạm khóa chat (Timeout) linh hoạt từ 1 phút đến 24 giờ, hỗ trợ Role & Channel Whitelist.

### ✅ 11. Cổng Xác Minh Thành Viên (Verify Gate System)
- **Cổng xác thực linh hoạt**: Hỗ trợ 2 chế độ: Nút bấm xác nhận (`Button Verify`) hoặc `CAPTCHA` chọn đúng biểu tượng để loại trừ 100% self-bot / bot spam.
- **Phân quyền cách ly an toàn**: Tự động gán Role tạm thời (`pending_role`), ẩn toàn bộ server chỉ để lộ duy nhất kênh xác minh.
- **Gán Role tự động & Mở khóa server**: Tự động cấp Role chính thức (`verified_role`) và gỡ Role tạm ngay khi vượt qua xác minh.
- **Tùy biến bảng thông báo**: Lệnh `/setup_verify`, `/verify panel`, `/verify disable` và trang cấu hình chuyên dụng `/dashboard/<id>/verify`.

### 🎫 12. Hệ Thống Support Ticket (Ticket System)
- Tạo nhiều bảng Ticket tương tác với nút bấm tuỳ chỉnh màu sắc & biểu tượng.
- Tạo kênh chat riêng tư kèm phân quyền bảo mật chặt chẽ cho đội ngũ Support.
- Quy trình Đóng / Xóa ticket có đếm ngược trực quan và ghi log chi tiết.

### ⭐ 13. Hệ Thống Cấp Độ (Leveling & Rank Cards)
- Tính điểm XP linh hoạt từ Chat text (cooldown 60s) và Voice channel (quét định kỳ 90s).
- Tạo ảnh thẻ Rank Card trực quan bằng thư viện Pillow (`PIL`).
- Tự động trao Role phần thưởng khi đạt mốc Level (hỗ trợ tích lũy Role hoặc thay thế).
- Quản trị viên dễ dàng quản lý XP với các lệnh `/xp add`, `/xp set`, `/xp reset`.

### 🤖 14. Tự Động Trao Role & Reaction Roles
- **Auto Roles**: Tự động gán role ban đầu cho User và Bot khi vừa vào máy chủ.
- **Reaction Roles**: Tạo bảng chọn role trực quan qua nút bấm Button hoặc Reaction Emoji.

### 🎉 15. Sự Kiện Giveaway Đỉnh Cao (Essential Bot Style)
- **Banner đồ họa Dark Theme**: Tự động gắn ảnh bìa `🎉 GIVEAWAY` sang trọng ở đầu Embed.
- **Bố cục Key-Value chuẩn mực**: `**Phần thưởng:**`, `**Số người thắng:**`, `**Tạo bởi:**`, `**Vai trò yêu cầu:**` (tùy chọn), `**Lượt tham gia:**`, `**Kết thúc:**`.
- **Nút bấm Blurple `🎉 Tham gia Giveaway`**: Đếm số người tham gia realtime và cập nhật trực tiếp trên Embed.
- **Giao diện kết thúc sang trọng**: Chuyển màu Dark Slate `0x2B2D31`, công bố người trúng giải rõ ràng và tự động gửi tin nhắn chúc mừng.
- Khởi tạo & quản lý sự kiện bằng lệnh `/giveaway start` (kèm tham số `role` yêu cầu), `/giveaway end`, `/giveaway reroll`.
- Cơ chế bảo vệ chống race-condition (tránh trao giải lặp lại 2 lần).

### 💬 16. Lệnh Tùy Biến (Custom Commands & Auto-Responders)
- **Tạo phản hồi tự động**: Lệnh `/customcmd add`, `/customcmd list`, `/customcmd delete` hỗ trợ đối sánh từ khóa linh hoạt (`exact`, `contains`, `startswith`).
- **Thống kê lượt sử dụng**: Theo dõi chi tiết số lần kích hoạt của từng lệnh trên Dashboard.

### 📊 17. Nhật Ký Máy Chủ & Thống Kê Thời Gian Thực
- **Audit Logger**: Ghi log chi tiết tin nhắn sửa/xóa, thành viên ra/vào, kick/ban, thay đổi Role, kênh, ticket.
- **Real-time Stats**: Thống kê số lượng tin nhắn, thành viên ra vào theo từng giờ cho biểu đồ Dashboard.
- **Utility & Info**: Menu `/help` tương thích 6 ngôn ngữ, `/ping`, `/membercount`, `/serverinfo`, `/userinfo`, `/avatar`, `/poll`, `/roll`, `/choose`.

### 📦 18. Sao Lưu Tự Động & Bảo Trì Dữ Liệu (24h Auto Backup, Pruning & WAL Checkpoint)
- **Tác vụ ngầm 24h (`auto_backup_task`)**: Tự động dọn dẹp WAL (`PRAGMA wal_checkpoint(TRUNCATE);`), nén cơ sở dữ liệu `data/bot.db` thành file `.zip`, lưu trữ có giới hạn 7 ngày và gửi backup về Discord qua `BACKUP_DB_URL`.
- **Bảo trì dữ liệu tự động (Auto-Prune)**: Tự động xóa sạch các bản ghi log, cảnh cáo và tương tác cũ quá hạn (60 ngày) qua `maintenance.py` để tiết kiệm dung lượng SQLite.
- **Lệnh Chủ Bot `/backup`**: Cho phép Bot Owner tải về bản sao lưu database toàn vẹn ngay lập tức.

### 🌐 19. Web Dashboard Quản Trị Server (Flask + Discord OAuth2)
- **Giao diện Midnight Obsidian Glassmorphism**: Thiết kế kính mờ sang trọng, ấm áp, chống mỏi mắt với chuẩn form control cao cấp.
- **Sidebar Phân Cấp Ưu Tiên**:
  - 🛡️ *Quản Trị Cốt Lõi*: Moderation, Automods, Verify Gate (Xác thực thành viên), Welcome & Goodbye, Auto Roles, Logging.
  - 🤖 *Cộng Đồng & Giải Trí*: AI Assistant, Leveling, Economy, Birthday, Fun & Social, Temp Voice, Music, Reaction Roles.
  - ⚙️ *Tiện Ích & Công Cụ*: Support Tickets, Giveaways, Custom Commands, Info, Utility.
- **Trang Chủ Hiện Đại**: Lưới 20 module đối xứng cân đối kèm nút `[ + And More ]` và 9 khối showcase tính năng trực quan.
- **Bảo Mật & Điều Khoản Chuyên Nghiệp**: Trang Điều khoản dịch vụ (`/tos`) và Chính sách bảo mật (`/privacy`) chuẩn pháp lý với thanh mục lục cố định (Sticky TOC).
- **Trang Admin dành cho Bot Owner (`/admin`)**:
  - Xem danh sách máy chủ active, phát thông báo Broadcast toàn hệ thống, Kick/Blacklist server vi phạm.
  - **Web Terminal**: Nhập lệnh shell trực tiếp trên trình duyệt (tương thích 100% Android Termux/Linux).
  - **Git Pull & Restart 1-Click**: Tự động cập nhật mã nguồn qua `git fetch & reset hard` và khởi động lại bot ngay trên Web.

### 🔒 20. Bảo Mật & Hạ Tầng Chuẩn Production (Security & Hardening)
- **WSGI Production Server**: Tích hợp máy chủ **Waitress WSGI** cho Web Dashboard, ổn định và chịu tải tốt hơn.
- **Bảo vệ CSRF Per-Session**: Tự động inject và kiểm tra CSRF token per-session qua `_csrf_bootstrap.html` cho toàn bộ form và request.
- **Chống Login CSRF & IDOR**: Bắt buộc tham số `state` trong OAuth2 flow; kiểm duyệt chặt chẽ quyền sở hữu `channel_id` theo `guild_id`.
- **Chống SSRF**: Hàm `is_safe_http_url` kiểm duyệt URL đầu vào (Card background, media, AI article summarization).
- **Giới hạn tần suất (Rate Limiter)**: Tích hợp `Flask-Limiter` bảo vệ các route nhạy cảm (`/login`, `/callback`, `/admin/system/*`).
- **Bộ Test Suite Tự Động**: Kiểm thử unit test và security test (`tests/`) bảo vệ toàn diện hệ thống.

---

## 🛠️ Công Nghệ Sử Dụng

- **Ngôn ngữ**: Python 3.10+
- **Bot Engine**: `discord.py` 2.3+ (App Commands / Slash Commands)
- **Web Framework & WSGI**: Flask + Waitress WSGI
- **Cơ sở dữ liệu**: SQLite (`aiosqlite` async cho Bot, `sqlite3` sync cho Dashboard, WAL mode, timeout=15s)
- **Cache Layer**: Pure Python In-Memory RAM Cache (`MemoryCache` thread-safe & async-safe với TTL LRU eviction và daemon cleanup 5 phút, không cần Redis)
- **Xử lý Âm thanh**: `yt-dlp` + `FFmpegOpusAudio`
- **Đồ họa**: Pillow (`PIL`)
- **Kiểm thử**: Pytest + Unittest Suite

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
BACKUP_DB=https://discord.com/api/webhooks/...
DEV_GUILD_ID=your_dev_server_id_optional
GEMINI_API_KEY=optional_ai_key_here
```

> 🔐 **Bảo mật**: `FLASK_SECRET_KEY` bắt buộc phải là chuỗi ngẫu nhiên riêng của bạn
> (vd: `python -c "import secrets; print(secrets.token_hex(32))"`). Nếu để trống hoặc
> giữ giá trị mẫu, hệ thống sẽ tự sinh key ngẫu nhiên mỗi lần khởi động — an toàn
> nhưng mọi phiên đăng nhập sẽ bị reset sau mỗi lần restart dashboard.

### 2.5. Bật Privileged Gateway Intents (Bắt buộc)

Bot cần 3 intents đặc quyền, nếu thiếu sẽ **không đăng nhập được** (`PrivilegedIntentsRequired`).
Vào [Discord Developer Portal](https://discord.com/developers/applications) → chọn App → **Bot** → bật:

- ✅ **Presence Intent**
- ✅ **Server Members Intent**
- ✅ **Message Content Intent**

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

## 🔌 Quản Trị Từ Xa & Giao Thức MCP (Model Context Protocol)

Dự án tích hợp đầy đủ giao thức **Model Context Protocol (MCP)** cho phép Trợ lý AI (Google Antigravity, Claude Desktop, Cursor) gỡ lỗi, kiểm tra sức khỏe và điều khiển bot trên thiết bị Android **Termux** hoàn toàn tự động mà không cần gõ lệnh thủ công:

### 1. Cấu hình IDE Antigravity / Claude Desktop
File cấu hình tại `C:\Users\Nam\.gemini\antigravity-ide\mcp_config.json`:
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "d:\\Project\\Discord Bots\\v2\\data\\bot.db"]
    },
    "termux": {
      "command": "python",
      "args": ["d:\\Project\\Discord Bots\\v2\\scripts\\termux_mcp.py"],
      "env": {
        "TERMUX_HOST": "192.168.2.50",
        "TERMUX_PORT": "8022",
        "TERMUX_USER": "u0_a224",
        "TERMUX_PASS": "nam123",
        "BOT_DIR": "~/zerynbot"
      }
    }
  }
}
```

### 2. Danh Sách Công Cụ MCP (Ánh Xạ 100% Lệnh `main.py`)
| Tool MCP | Lệnh Chạy Trên Termux | Chức Năng |
| :--- | :--- | :--- |
| `termux_system_restart` | `python main.py --restart` | Khởi động lại toàn bộ Bot + Dashboard an toàn |
| `termux_system_stop` | `python main.py --stop` | Dừng sạch tiến trình và gửi Webhook thông báo |
| `termux_system_test` | `python main.py --test` | Chạy bộ tự chẩn đoán lỗi `SystemTester` |
| `termux_get_status` | `free -h` & `ps -ef \| grep python` | Kiểm tra tài nguyên RAM/Swap và trạng thái PID |
| `termux_read_logs` | `tail -n <lines> data/bot.log` | Đọc log thời gian thực trực tiếp từ thiết bị |
| `termux_git_pull` | `git pull origin main` | Tự động cập nhật mã nguồn mới nhất từ GitHub |
| `termux_run_command` | `<command>` | Thực thi lệnh bash tùy chỉnh trong thư mục bot |

> 🌐 **Kết Nối Xuyên Mạng**: Khi ở trường học hoặc ngoài mạng Wi-Fi gia đình, cài đặt **Tailscale** trên điện thoại Tecno Pova 2 và máy tính Windows. Thay đổi `TERMUX_HOST` thành IP ảo cố định `100.x.y.z` trong `mcp_config.json` để duy trì kết nối điều khiển 24/7.

---

## 📂 Cấu Trúc Thư Mục Dự Án

```text
ZerynBot/
├── main.py              # Điểm vào điều khiển trung tâm (start/stop/restart/status/test)
├── config.py            # Quản lý cấu hình & biến môi trường
├── database.py          # Xử lý cơ sở dữ liệu SQLite (WAL mode, async & sync, timeout 15s)
├── cache.py             # Bộ quản lý In-Memory RAM Cache (thread-safe, TTL, 5min periodic cleanup)
├── i18n.py              # Động cơ dịch đa ngôn ngữ O(1) RAM-cached (1587 keys/file)
├── requirements.txt     # Danh sách thư viện Python chạy production
├── requirements-dev.txt # Danh sách thư viện dev & test (pytest, ruff)
├── LICENSE              # Giấy phép nguồn mở MIT
├── bot/                 # 🤖 Discord Bot Source Code
│   ├── bot.py           # Entry point của Discord Bot & Webhook Logger
│   ├── card_generator.py# Render ảnh Rank Card, Welcome/Goodbye Banner bằng Pillow
│   ├── checks.py        # Kiểm tra quyền hạn & Bot Admin
│   └── cogs/            # 22 Cogs chức năng (moderation, fun, birthday, remind, ai, tempvoice, economy, customcommands, music, automod, ...)
├── dashboard/           # 🌐 Flask Web Dashboard
│   ├── app.py           # Routes chính của Dashboard
│   ├── api.py           # AJAX API Endpoints
│   ├── auth.py          # Discord OAuth2 Session Manager & SSRF filter
│   ├── static/          # CSS (v9.2), JS, Branding Images
│   └── templates/       # Giao diện HTML Jinja2 (Midnight Obsidian theme & CSRF bootstrap)
├── locales/             # 🌐 6 File từ điển ngôn ngữ JSON (vi, en, zh, es, pt, fr) - 1587 keys/file
├── scripts/             # Scripts hỗ trợ (send_status.py, watchdog.sh, termux_boot.sh, termux_mcp.py)
├── tests/               # 🧪 55 Unit tests (cache, i18n, database, dashboard security, smoke-load 22 cogs)
├── .github/             # CI pipeline & Dependabot
└── data/                # Nơi lưu trữ dữ liệu sqlite bot.db, log file & health.json
```

## 🧪 Chạy Kiểm Thử (Tests)

```bash
# Cài đặt thư viện dev/test (chỉ cần trên máy dev):
pip install -r requirements-dev.txt

# Chạy toàn bộ 55 test cases:
pytest -q
```

---

## 📄 Giấy Phép & Đóng Góp

Dự án được phát hành theo giấy phép **MIT License**. Mọi đóng góp (Pull Request / Issue) đều được hoan nghênh!

> Made with ❤️ by **Nam** — Optimized for low-spec ARM devices & Termux 24/7.


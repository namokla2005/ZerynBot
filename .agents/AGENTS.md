# 🤖 Quy Tắc Tác Nghiệp & Cấu Hình AI Cho ZerynBot V2

Tài liệu này xác định các quy tắc cốt lõi, bối cảnh môi trường phần cứng và tiêu chuẩn làm việc bắt buộc dành cho Trợ lý AI (Antigravity AI / Coding Assistants) khi làm việc trên dự án **ZerynBot V2**.

---

## 🎯 1. Nguyên Tắc Làm Việc Bắt Buộc Của AI

> [!IMPORTANT]
> **Quy Tắc Tiếp Nhận & Xử Lý Yêu Cầu (Mandatory AI Workflow)**:
> Mỗi khi nhận được yêu cầu từ Người Dùng (User), AI **BẮT BUỘC** phải tuân thủ quy trình 3 bước sau trước khi thực hiện bất kỳ thay đổi mã nguồn nào:
> 1. **Đọc kỹ & Hiểu sâu yêu cầu**: Xác định chính xác mong muốn, phạm vi ảnh hưởng và các ràng buộc kỹ thuật.
> 2. **Kiểm tra mã nguồn & Phân tích nguyên nhân**: Đọc các tệp liên quan, tìm hiểu nguyên nhân gốc rễ (Root Cause) của vấn đề hoặc cơ chế hiện có trong codebase.
> 3. **Lên kế hoạch & Đề xuất giải pháp chuyên nghiệp**: Trình bày rõ ràng nguyên nhân, hướng tiếp cận tối ưu và các bước triển khai cụ thể để người dùng nắm rõ.

---

## 🌐 2. Môi Trường Triển Khai Thực Tế

- **Thiết bị vận hành 24/7**: Máy tính bảng Android / Điện thoại chạy môi trường **Termux (ARM64)**, tài nguyên CPU/RAM khiêm tốn.
- **Tên miền chính thức (Domain)**: `https://zerynbot.id.vn`
- **Discord OAuth2 Redirect URI**: `https://zerynbot.id.vn/callback`
- **Git Repository**: `https://github.com/namokla2005/ZerynBot.git` (Nhánh chính: `main`).
- **Sao lưu cơ sở dữ liệu an toàn**: Các tệp backup SQLite (`.zip`) **chỉ được gửi về Webhook riêng tư `BACKUP_DB` (`config.BACKUP_DB_URL`)**, tuyệt đối không gửi vào kênh log chung của Discord server.

---

## 📚 3. Danh Mục Kỹ Năng & Nguồn Tri Thức (Skills & Single Source of Truth)

- **Tài liệu kiến trúc chính**: [`ARCHITECTURE.md`](file:///d:/Project/Discord%20Bots/v2/ARCHITECTURE.md) tại thư mục gốc là nguồn chân lý duy nhất. AI phải luôn tham khảo trước khi sửa đổi cấu trúc.
- **Hệ thống Kỹ năng chuyên sâu trong `.agents/skills/`**:
  1. 🏛️ **[`zerynbot_architecture_context`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/SKILL.md)**: SOP tác nghiệp, checklist 5 bước thêm lệnh, kiểm thử 1-click `validate_all.py`.
  2. ⚡ **[`ai_provider_routing`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/ai_provider_routing/SKILL.md)**: Điều hướng Groq/Gemini/OpenRouter, active models reference (`qwen3.8-27b`, `gpt-oss-20b`), Multimodal Vision.
  3. 💰 **[`economy_system`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/economy_system/SKILL.md)**: Quy tắc phân tách Ví tiền mặt (Mini-games cược) vs Ngân hàng két sắt (Role Shop).
  4. 🌐 **[`dashboard_dev_guide`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/dashboard_dev_guide/SKILL.md)**: Thiết kế Midnight Obsidian Glassmorphism, CSS tokens, checklist 7 bước tạo trang module mới.
  5. 🎵 **[`music_audio_pipeline`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/music_audio_pipeline/SKILL.md)**: Tối ưu hóa âm thanh ARM/Termux, cờ FFmpeg đơn luồng, nạp `libopus`, player 5 nút bấm.
  6. 🖼️ **[`discord_ui_rendering`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/discord_ui_rendering/SKILL.md)**: Sinh ảnh Pillow trong thread pool (Rank Card, Welcome Banner), Discord Embeds & Persistent Views.
  7. 🛠️ **[`ops_and_troubleshooting`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/ops_and_troubleshooting/SKILL.md)**: Vận hành 24/7 Termux, quản trị SQLite WAL, phục hồi backup từ Webhook `BACKUP_DB`.

---

## ⚙️ 4. Quy Chuẩn Kỹ Thuật Dự Án

- **Điểm vào điều khiển (CLI)**: `python main.py` là tiến trình điều phối trung tâm duy nhất (`start`, `stop`, `restart`, `status`, `test`).
- **Bot Engine**: `discord.py` (Python 3.10+), truy cập CSDL bất đồng bộ qua `aiosqlite` (`database.py` `async_*`), dịch đa ngôn ngữ bằng `tr(settings, key, **kwargs)`.
- **Web Dashboard**: Flask + Jinja2, truy cập CSDL đồng bộ qua `sqlite3` (`database.py` sync), dịch đa ngôn ngữ bằng `t(key)`.
- **Hệ thống Modules**: Đúng chuẩn **19 Modules** trong `DEFAULT_MODULES` (`welcome_goodbye`, `autoroles`, `leveling`, `utility`, `info`, `music`, `tickets`, `reactionroles`, `automods`, `logger`, `giveaways`, `economy`, `tempvoice`, `customcommands`, `ai`, `remind`, `moderation`, `fun`, `birthday`).
- **Hệ thống Lệnh Dashboard**: Danh sách tập trung `_COMMANDS_DATA` trong [`dashboard/app.py`](file:///d:/Project/Discord%20Bots/v2/dashboard/app.py) quản lý đúng **87 lệnh** thuộc **16 danh mục**.
- **Đa ngôn ngữ (i18n)**: 6 file từ điển (`vi`, `en`, `zh`, `es`, `pt`, `fr`) luôn luôn đồng bộ chính xác **1510 keys/file** (100% không lệch key).
- **Cơ sở dữ liệu**: SQLite WAL mode tại `data/bot.db` (`PRAGMA busy_timeout = 15000`, tự động checkpoint dọn WAL).
- **AI Engine**: Groq Cloud API (`gsk_*`) với model mặc định `qwen/qwen3.8-27b` (hỗ trợ chuyển đổi qua Admin Dashboard), fallback sang Google Gemini và OpenRouter. Hỗ trợ xử lý ảnh (Multimodal Vision).
- **Hệ thống Kinh Tế & Ngân Hàng**:
  - **Ví (Wallet)**: Tiền mặt dùng để chuyển khoản `/pay`, chơi mini-games (`/coinflip`, `/slots`, `/blackjack`). Mini-games chỉ cược bằng tiền Ví.
  - **Ngân hàng (Bank)**: Nơi giữ an toàn tài sản và thanh toán mua sắm Role trong Cửa hàng Server (`/shop`, `/buy`). Hỗ trợ nạp `/deposit` và rút `/withdraw` linh hoạt (hỗ trợ từ khóa `all`/`max`).

---

## 📝 5. Quy Tắc Cập Nhật & Đồng Bộ Tài Liệu Tự Động

Mỗi khi AI thực hiện thay đổi mã nguồn, **BẮT BUỘC** phải tuân thủ:
1. **Khi thêm/xóa lệnh Discord**:
   - Cập nhật Cog logic + `_COMMANDS_DATA` trong `dashboard/app.py`.
   - Cập nhật số lượng lệnh trong `ARCHITECTURE.md`, `.agents/AGENTS.md`, `llms.txt`.
2. **Khi thêm/xóa i18n key**:
   - Thêm đủ vào cả **6 file** trong `locales/`.
   - Chạy kiểm tra: `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py`.
   - Cập nhật con số key trong `ARCHITECTURE.md`, `.agents/AGENTS.md`, `llms.txt`.
3. **Khi thay đổi AI Provider hoặc Model**:
   - Cập nhật danh sách model trong `dashboard/templates/admin.html`, `bot/cogs/ai.py`, `.agents/skills/ai_provider_routing/`.
4. **Git Commit & Push**:
   - Luôn commit bằng format Conventional Commits (`feat:`, `fix:`, `docs:`) kèm file tài liệu liên quan trong cùng commit.
   - Luôn kiểm tra `py_compile` trước khi commit.
   - Luôn `git push origin main` sau khi hoàn tất.

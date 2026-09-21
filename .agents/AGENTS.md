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

### 🔍 1.1 Quy Tắc Tiếp Nhận Báo Lỗi & Thu Thập Chứng Cứ Termux Thực Tế (Evidence-Based Incident Triage Rule)
- **Cấm phỏng đoán mò mẫm (No Guesswork)**: Khi Người Dùng báo lỗi, AI **tuyệt đối không được ngồi phỏng đoán mò mẫm hay vội vàng sửa code trên máy tính**.
- **Bắt buộc truy cập Termux thu thập chứng cứ ngay lập tức**: AI **BẮT BUỘC phải lập tức kết nối tới thiết bị Termux (Tecno Pova 2)** bằng lệnh:
  ```bash
  python scripts/termux_diag.py
  ```
- **Các nguồn thông tin bắt buộc thu thập**:
  1. 📊 **Trạng thái tiến trình thực tế**: Kiểm tra `python main.py --status` và danh sách tiến trình Python/Watchdog đang chạy (`ps -ef`).
  2. 📜 **Nhật ký lỗi (Logs & Tracebacks)**: Đọc các dòng log gần nhất (`data/bot.log`, `data/dashboard.log`), trích xuất toàn bộ Traceback, Exception, Warning gần nhất.
  3. 🌐 **Sức khỏe dịch vụ nội bộ**: Kiểm tra phản hồi Health Check (`curl -s http://localhost:5000/health`).
  4. 🧠 **Tài nguyên & Trạng thái CSDL**: Kiểm tra dung lượng RAM/Swap (`free -h`, `uptime`) và kích thước CSDL SQLite WAL (`ls -lh data/bot.db*`).
- **Phân tích nguyên nhân gốc rễ (Root Cause Analysis - RCA)**: Sau khi đã có dữ liệu thực tế từ Termux, Model 1 và Model 2 mới tiến hành phân tích chính xác nguyên nhân gây lỗi để đưa vào quy trình phản biện.

### 💡 1.2 Nguyên Tắc Phản Biện & Tư Vấn Kỹ Thuật Chủ Động (Critical Inquiry Rule)
- **Không thực thi mù quáng (No Blind Execution)**: AI đóng vai trò là Senior Architect và cộng sự kỹ thuật. Khi người dùng đưa ra yêu cầu mới, thay đổi luồng hoặc tính năng, AI **tuyệt đối không làm theo một cách thụ động, máy móc**.
- **Chủ động đặt câu hỏi làm rõ**: Nếu yêu cầu còn mơ hồ, có nhiều phương án triển khai, hoặc tiềm ẩn rủi ro (hiệu năng ARM/Termux yếu, nghẽn SQLite WAL, phá vỡ chuẩn 20 modules / 108 lệnh / 1621 keys i18n, UX Discord/Web chưa mượt), AI **BẮT BUỘC phải hỏi thêm thông tin, chỉ ra các trường hợp biên (edge cases) và đề xuất các giải pháp tối ưu** kèm ưu/nhược điểm (trade-offs) trước khi bắt tay vào viết mã.
- **Tương tác thông minh**: Sử dụng interactive modal (`ask_question`) để người dùng chọn nhanh các phương án, hoặc gợi ý slash command `/grill-me` khi cần trao đổi đa chiều về quyết định thiết kế kiến trúc. Chi tiết xem tại [`.agents/rules/critical_inquiry.md`](file:///d:/Project/Discord%20Bots/v2/.agents/rules/critical_inquiry.md).

### 👥 1.3 Quy Trình Phản Biện Đa Model 5 Bước Chuẩn (The 5-Step Dual-Model Co-Reasoning Loop)
- **Quy tắc cốt lõi (Persistent Constraint)**: Trong **MỌI tác vụ** (tiếp nhận yêu cầu, xử lý lỗi, phân tích nguyên nhân gốc rễ, lập kế hoạch kiến trúc, chỉnh sửa mã nguồn và rà soát trước commit), AI **BẮT BUỘC MẶC ĐỊNH LUÔN DÙNG 2 MODEL AI ĐỒNG THỜI**, tuyệt đối không bao giờ làm việc đơn lẻ:
  - 🏛️ **Model 1 — Lead Architect & Coordinator (Primary Agent - Gemini 3.8 / Antigravity IDE)**: Tiếp nhận dữ liệu chẩn đoán Termux, nắm giữ ngữ cảnh sâu rộng, thiết kế phương án kiến trúc, trực tiếp thao tác viết/chỉnh sửa mã nguồn và điều phối toàn bộ workflow.
  - 🛡️ **Model 2 — Independent Reviewer & Security Critic (Groq LPU — Qwen 2.5 / GPT-OSS qua `scripts/dual_model_mcp.py`)**: Đóng vai trò kiểm toán viên độc lập, tìm kiếm lỗ hổng bảo mật (SSRF, XSS, IDOR, SQLi), race condition, rò rỉ tài nguyên trên Termux ARM64 (Helio G85, 6GB RAM), nghẽn SQLite WAL và phá vỡ kiến trúc.
- **Chu Trình 5 Bước Phản Biện Bắt Buộc (The 5-Step Loop)**:
  1. 📋 **Bước 1 (1 - Lên kế hoạch)**: Model 1 dựa trên chứng cứ thực tế thu thập từ Termux và phân tích mã nguồn để thiết lập kế hoạch giải quyết chi tiết (`Plan v1`).
  2. 🔍 **Bước 2 (2 - Kiểm tra + Phản biện)**: Model 2 rà soát độc lập (`Critique v1`) qua `python scripts/dual_model_mcp.py --consult "<kế hoạch>" --role critic`, chỉ ra các điểm mù, rủi ro bảo mật, deadlock SQLite WAL và hiệu năng Termux Helio G85.
  3. 🛠️ **Bước 3 (1 - Sửa kế hoạch)**: Model 1 tiếp thu phản biện, hoàn thiện kế hoạch, giải quyết triệt để các lỗ hổng được chỉ ra (`Plan v2`).
  4. 🔬 **Bước 4 (2 - Kiểm tra + Phản biện lại)**: Model 2 kiểm tra lại `Plan v2` (`Critique v2`). Nếu vẫn còn lỗi hoặc rủi ro tiềm ẩn, tiếp tục yêu cầu Model 1 chỉnh sửa (tối đa 3 vòng lặp để tránh nghẽn).
  5. 🤝 **Bước 5 (1 & 2 - Đồng thuận)**: Cả Model 1 và Model 2 cùng đạt đồng thuận phê duyệt (`APPROVED`), sau đó mới tiến hành viết mã nguồn / triển khai thực tế.
- **Khâu Rà Soát Bắt Buộc Trước Khi Đẩy Code (Mandatory Pre-Commit Gate)**: Trước khi `git push origin main` lên Termux, bắt buộc phải chạy `python scripts/dual_model_mcp.py --pre-commit-check` và đạt kết quả `🟢 SẴN SÀNG COMMIT`. Chi tiết xem tại [`.agents/rules/dual_model_co_reasoning.md`](file:///d:/Project/Discord%20Bots/v2/.agents/rules/dual_model_co_reasoning.md).

---

## 🌐 2. Môi Trường Triển Khai Thực Tế

- **Thiết bị vận hành 24/7**: Máy tính bảng Android / Điện thoại chạy môi trường **Termux (ARM64)**, tài nguyên CPU/RAM khiêm tốn.
- **Tên miền chính thức (Domain)**: `https://zerynbot.id.vn`
- **Discord OAuth2 Redirect URI**: `https://zerynbot.id.vn/callback`
- **Git Repository**: `https://github.com/namokla2005/ZerynBot.git` (Nhánh chính: `main`).
- **Sao lưu cơ sở dữ liệu an toàn**: Các tệp backup SQLite (`.zip`) **chỉ được gửi về Webhook riêng tư `BACKUP_DB` (`config.BACKUP_DB_URL`)**, tuyệt đối không gửi vào kênh log chung của Discord server.

---

## 📚 3. Danh Mục Kỹ Năng & Nguồn Tri Thức (Skills & Single Source of Truth)

- **Tài liệu kiến trúc chính**: [`ARCHITECTURE.md`](https://github.com/namokla2005/ZerynBot/blob/main/ARCHITECTURE.md) tại thư mục gốc là nguồn chân lý duy nhất. AI phải luôn tham khảo trước khi sửa đổi cấu trúc.
- **Hệ thống Kỹ năng chuyên sâu trong `.agents/skills/`**:
  1. 🏛️ **[`zerynbot_architecture_context`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/zerynbot_architecture_context/SKILL.md)**: SOP tác nghiệp, checklist 5 bước thêm lệnh, kiểm thử 1-click `validate_all.py`.
  2. ⚡ **[`ai_provider_routing`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/ai_provider_routing/SKILL.md)**: Điều hướng Groq/Gemini/OpenRouter, active models reference (`qwen3.8-27b`, `gpt-oss-20b`), Multimodal Vision.
  3. 💰 **[`economy_system`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/economy_system/SKILL.md)**: Quy tắc phân tách Ví tiền mặt (Mini-games cược) vs Ngân hàng két sắt (Role Shop).
  4. 🌐 **[`dashboard_dev_guide`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/dashboard_dev_guide/SKILL.md)**: Thiết kế Midnight Obsidian Glassmorphism, CSS tokens, checklist 7 bước tạo trang module mới.
  5. 🎵 **[`music_audio_pipeline`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/music_audio_pipeline/SKILL.md)**: Tối ưu hóa âm thanh ARM/Termux, cờ FFmpeg đơn luồng, nạp `libopus`, player 5 nút bấm.
  6. 🖼️ **[`discord_ui_rendering`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/discord_ui_rendering/SKILL.md)**: Sinh ảnh Pillow trong thread pool (Rank Card, Welcome Banner), Discord Embeds & Persistent Views.
  7. 🛠️ **[`ops_and_troubleshooting`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/ops_and_troubleshooting/SKILL.md)**: Vận hành 24/7 Termux, quản trị SQLite WAL, phục hồi backup từ Webhook `BACKUP_DB`.

---

## ⚙️ 4. Quy Chuẩn Kỹ Thuật Dự Án

- **Điểm vào điều khiển (CLI)**: `python main.py` là tiến trình điều phối trung tâm duy nhất (`start`, `stop`, `restart`, `status`, `test`).
- **Bot Engine**: `discord.py` (Python 3.10+), truy cập CSDL bất đồng bộ qua `aiosqlite` (`database.py` `async_*`), dịch đa ngôn ngữ bằng `tr(settings, key, **kwargs)`.
- **Web Dashboard**: Flask + Jinja2, truy cập CSDL đồng bộ qua `sqlite3` (`database.py` sync), dịch đa ngôn ngữ bằng `t(key)`.
- **Hệ thống Modules**: Đúng chuẩn **20 Modules** trong `DEFAULT_MODULES` (`welcome_goodbye`, `autoroles`, `leveling`, `utility`, `info`, `music`, `tickets`, `reactionroles`, `automods`, `logger`, `giveaways`, `economy`, `tempvoice`, `customcommands`, `ai`, `remind`, `moderation`, `fun`, `birthday`, `verify`).
- **Hệ thống Lệnh Dashboard**: Danh sách tập trung `_COMMANDS_DATA` trong [`dashboard/app.py`](https://github.com/namokla2005/ZerynBot/blob/main/dashboard/app.py) quản lý đúng **108 lệnh** thuộc **17 danh mục**.
- **Đa ngôn ngữ (i18n)**: 6 file từ điển (`vi`, `en`, `zh`, `es`, `pt`, `fr`) luôn luôn đồng bộ chính xác **1621 keys/file** (100% không lệch key).
- **Cơ sở dữ liệu**: SQLite WAL mode tại `data/bot.db` (`PRAGMA busy_timeout = 15000`, tự động checkpoint dọn WAL).
- **AI Engine**: Groq Cloud API (`gsk_*`) với model mặc định `qwen/qwen3.8-27b` (hỗ trợ chuyển đổi qua Admin Dashboard), fallback sang Google Gemini và OpenRouter. Hỗ trợ xử lý ảnh (Multimodal Vision).
- **Hệ thống Kinh Tế & Ngân Hàng**:
  - **Ví (Wallet)**: Tiền mặt dùng để chuyển khoản `/pay`, chơi mini-games (`/coinflip`, `/slots`, `/blackjack`). Mini-games chỉ cược bằng tiền Ví.
  - **Ngân hàng (Bank)**: Nơi giữ an toàn tài sản và thanh toán mua sắm Role trong Cửa hàng Server (`/shop`, `/buy`). Hỗ trợ nạp `/deposit` và rút `/withdraw` linh hoạt (hỗ trợ từ khóa `all`/`max`).
- **Hệ thống Phát Nhạc (Audio Engine)**:
  - **Trích xuất song song & Thread-Safety**: Trích xuất đa luồng an toàn qua `threading.local` cho `YoutubeDL`, semaphore tối đa 4 extraction đồng thời. `extract_info` chạy đồng thời với `_ensure` kết nối voice channel (`asyncio.create_task`), cắt giảm 50% độ trễ khởi động. Tải playlist nền xử lý theo batch 2 bài hát kèm fallback tìm theo tên bài hát nếu URL bị lỗi.
  - **Tự cứu luồng phát (Auto-Recovery)**: Bắt lỗi 403 Forbidden / URL stream hết hạn để re-extract tự động và tiếp tục phát ngay tại vị trí cũ (`-ss <elapsed>`).
  - **Cache 2 tầng**: In-Memory RAM Cache (`cache.py`) + SQLite disk cache (`music_song_cache` với TTL 6 giờ, lưu timestamp hết hạn thực tế).
  - **Tối ưu FFmpeg & yt-dlp**: Cờ FFmpeg `-threads 1 -rw_timeout 10000000 -fflags +genpts -probesize 512K -analyzeduration 500000` (triệt tiêu 100% hiện tượng co dãn tốc độ/cao độ và chống treo vô tận khi mất mạng), client yt-dlp `["android"]` (miễn nhiễm lỗi bot verification của client `web`).
  - **Quản lý Hàng Đợi & Thống Kê**: Hỗ trợ tua nhạc `/seek`, tìm kiếm chọn bài `/search`, quản lý hàng đợi `/remove`, `/clearqueue`, `/jump` và ghi nhận bài hát nghe nhiều nhất vào CSDL.
- **Hạ Tầng Tác Nghiệp MCP (Model Context Protocol)**:
  - **Cấu hình chuẩn tại**: `C:\Users\Nam\.gemini\antigravity-ide\mcp_config.json`.
  - **Máy chủ SQLite MCP**: `uvx mcp-server-sqlite --db-path data/bot.db` truy vấn CSDL trực tiếp.
  - **Máy chủ Termux Remote MCP**: `python scripts/termux_mcp.py` điều phối từ xa thiết bị Tecno Pova 2 qua Paramiko SSH (port 8022 qua LAN hoặc Tailscale Mesh), tích hợp các lệnh ánh xạ 100% với `main.py` (`termux_system_restart`, `termux_system_stop`, `termux_system_test`, `termux_get_status`, `termux_read_logs`, `termux_git_pull`).
- **Tiêu chuẩn An Ninh & Đồng Thời (Security & Concurrency Defense)**:
  - **Chống SSRF**: Bắt buộc dùng `is_safe_http_url` phân giải qua `socket.getaddrinfo`, cấm toàn bộ dải IP private, loopback, IPv6 và decimal notation (`2130706433`), kiểm duyệt từng bước chuyển hướng redirect và giới hạn stream tải tối đa 5MB.
  - **Chống Stored XSS**: Tuyệt đối không dùng `innerHTML` để nối chuỗi dữ liệu người dùng trong Dashboard JS (như Embed Builder); luôn tạo phần tử DOM và gán qua `textContent`. Chỉ chấp nhận URL giao thức `http:` và `https:`. Nạp dữ liệu cấu hình thông qua thẻ `<script type="application/json">`.
  - **Chống IDOR Máy Chủ**: Bắt buộc giới hạn kênh sự kiện theo `member.guild.get_channel(cid)` thay vì tìm kiếm toàn cục; Dashboard API phải xác thực kênh thuộc quyền quản lý của guild (`_require_channel_in_guild`) và làm mới quyền hạn Discord định kỳ (`SESSION_GUILD_TTL`).
  - **Tính Nguyên Tử SQLite & Miễn Nhiễm Deadlock**: Mọi thao tác trừ tiền hoặc giảm kho phải dùng câu lệnh SQL điều kiện nguyên tử (`WHERE wallet >= ?`, `WHERE bank >= ?`, `WHERE stock > 0`) và kiểm tra `cursor.rowcount == 1`. Các hàm giao dịch nhiều bước (như `/pay`) bắt buộc thực hiện trên cùng 1 kết nối `aiosqlite.connect` duy nhất, khởi tạo receiver bằng `INSERT OR IGNORE` ngay trong transaction để loại bỏ hoàn toàn SQLite deadlock.

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
5. **Tự Động Deploy, Kiểm Thử Toàn Diện & Khắc Phục Lỗi Bắt Buộc Trên Termux (Mandatory Auto-Deploy, Functional Testing & Auto-Repair Loop)**:
   - Ngay sau khi `git push origin main` thành công, AI **BẮT BUỘC phải tự động chạy script deploy và kiểm thử toàn diện trên thiết bị Termux (Tecno Pova 2)**:
     ```bash
     python scripts/termux_deploy.py
     ```
   - **Quy Trình 4 Bước Kiểm Tra Hoàn Chỉnh Bắt Buộc (Mandatory Full Inspection & Functional Testing)**:
     Sau khi `git pull` và `python main.py --restart`, AI **tuyệt đối không được báo xong ngay** mà phải kiểm tra hoàn chỉnh toàn bộ hệ thống trên Termux:
     1. **Tiến trình thực tế (`python main.py --status`)**: Bot và Dashboard đều phải ở trạng thái `RUNNING (PID xxx)`.
     2. **Health Endpoint (`curl -s http://localhost:5000/health`)**: Phải phản hồi JSON với `online: true`.
     3. **Audit log khởi động (`data/bot.log`, `data/dashboard.log`)**: Đảm bảo không có Traceback hoặc crash.
     4. **Kiểm thử chức năng toàn bộ 20 modules (`python main.py --test`)**: Chạy bộ chẩn đoán `SystemTester` xác nhận 100% các chức năng chạy đúng, không lỗi logic, trả về đúng giá trị.
   - **Quy Tắc Sửa Lỗi Triệt Để (Zero-Tolerance Bug Fixing Loop)**:
     - Nếu phát hiện **bất kỳ lỗi nào (FAIL, TIMEOUT, lỗi logic, hàm trả về sai giá trị, crash log)**: AI **TUYỆT ĐỐI KHÔNG ĐƯỢC BÁO XONG HOẶC DỪNG LẠI**.
     - AI **bắt buộc phải trích xuất log lỗi, phân tích nguyên nhân gốc rễ, sửa chữa mã nguồn ngay lập tức, kiểm tra lại cú pháp (`py_compile`), commit, push và deploy lại lên Termux**.
     - Lặp lại quy trình kiểm thử cho đến khi **100% tất cả các module đều Xanh/Khỏe mạnh (`🟢 ONLINE`, `🟢 HEALTHY`, `🟢 SẠCH SẼ`, `🟢 20/20 MODULES PASS`), bot chạy hoàn toàn chuẩn xác không còn bất kỳ lỗi nào**, lúc đó mới được báo cáo hoàn thành cho Người Dùng.

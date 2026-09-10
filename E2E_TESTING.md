# 🧪 E2E_TESTING.md — Quy Trình Kiểm Thử Tự Động Trình Duyệt Web Dashboard

Tài liệu này hướng dẫn chi tiết các kịch bản kiểm thử tự động toàn diện (End-to-End Browser Testing) dành cho Trợ lý AI và Nhà phát triển khi kiểm tra giao diện **ZerynBot Web Dashboard** (`http://127.0.0.1:5000` hoặc `https://zerynbot.id.vn`).

---

## 🎯 1. Mục Tiêu & Công Cụ Kiểm Thử

* **Công cụ**: Sử dụng Browser Subagent (hoặc Playwright / Selenium / Puppeteer).
* **Mục tiêu**:
  1. Đảm bảo giao diện **Midnight Obsidian Glassmorphism** hiển thị sắc nét, không bị vỡ layout trên cả Desktop (1920x1080) và Mobile (375x812).
  2. Đảm bảo toàn bộ các tác vụ AJAX JSON (bật/tắt module, cập nhật cấu hình) hoạt động mượt mà và hiển thị Toast Notification.
  3. Đảm bảo tính năng Live Preview (xem trước Rank Card, Welcome Banner, Embed Builder) render chính xác.
  4. Kiểm tra an ninh phân quyền (không bị truy cập trái phép vào `/admin` hoặc server không thuộc quyền quản lý).

---

## 📋 2. Thiết Lập Môi Trường Kiểm Thử Cục Bộ (Local Mock Setup)

Khi chạy kiểm thử trên môi trường nội bộ không có kết nối Discord OAuth2 thật, thiết lập session mock trong Flask:

```python
# Thiết lập session mock trong tests/conftest.py hoặc dev server
mock_user_session = {
    "id": "111111111111111111",
    "username": "TestAdmin",
    "avatar": "https://cdn.discordapp.com/embed/avatars/0.png",
    "guilds": [
        {
            "id": "999999999999999999",
            "name": "Zeryn Support Community",
            "icon": None,
            "permissions": 8,  # Administrator
            "bot_in_guild": True
        }
    ]
}
```

---

## 🚀 3. Kịch Bản Kiểm Thử Chi Tiết (Test Scenarios)

### Kịch Bản 1: Trang Chủ, Điều Khoản & Trung Tâm Lệnh (`/`, `/tos`, `/privacy`, `/commands`)
1. **Mở URL `/`**:
   * Kiểm tra Header cố định (Logo Zeryn, Menu Navigation, nút Đăng nhập Discord).
   * Kiểm tra Hero Section (Tiêu đề, Avatar Mascot Chibi Zeryn tròn phát sáng, nút Add to Discord).
   * Kiểm tra lưới 16 tính năng nổi bật (Features Grid).
2. **Mở URL `/commands`**:
   * Kiểm tra hiển thị đầy đủ danh sách **103 Lệnh** thuộc **17 danh mục** được nạp từ `_COMMANDS_DATA` (địa phương hóa qua `commands_catalog.py`).
   * Thử tìm kiếm lệnh trên ô Search (ví dụ: gõ `verify` -> lọc đúng lệnh cổng xác minh thành viên).
   * Thử chuyển đổi danh mục (Kinh tế & Shop, Nhạc 24/7, Xác minh, Kiểm duyệt, v.v.).
3. **Mở URL `/tos` và `/privacy`**:
   * Kiểm tra thanh mục lục bên trái (Sticky TOC) cuộn mượt mà (smooth scrolling) tới từng phần.

---

### Kịch Bản 2: Quản Lý Cài Đặt Server & Bật/Tắt Module (`/dashboard/<id>/...`)
1. **Mở URL `/dashboard/999999999999999999`**:
   * Kiểm tra hiển thị thông tin máy chủ (Tên, Số lượng thành viên, Ngôn ngữ).
   * Thử đổi ngôn ngữ máy chủ (Tiếng Việt ➔ English) ➔ Kiểm tra giao diện cập nhật ngay lập tức.
2. **Kiểm tra công tắc Module Toggle**:
   * Bấm tắt/bật một module bất kỳ (ví dụ: `music` hoặc `economy`).
   * Kiểm tra API `POST /api/guild/<id>/modules/<name>` trả về HTTP 200 `{ok: true}`.
   * Kiểm tra xuất hiện thông báo nổi (Toast Notification) màu xanh lá ở góc màn hình.
   * **Kiểm tra bảo mật CSRF**: request POST **không kèm** header `X-CSRF-Token` phải bị chặn HTTP 403.

---

### Kịch Bản 3: Xem Trước Trực Tiếp (Live Previews)
1. **Module Leveling (`/dashboard/<id>/leveling`)**:
   * Thử chọn màu chủ đạo và ảnh nền thẻ Rank.
   * Bấm nút *"Xem trước Thẻ Rank"* ➔ Kiểm tra Canvas hoặc ảnh preview được render mượt mà trong modal.
2. **Module Welcome & Goodbye (`/dashboard/<id>/welcome`)**:
   * Nhập nội dung tin nhắn chào mừng kèm biến `{user}`, `{server}`, `{members}`.
   * Kiểm tra khung xem trước tin nhắn (Live Embed Preview) thay thế biến động thời gian thực.
3. **Embed Builder (`/dashboard/<id>/embeds`)**:
   * Thêm tiêu đề, mô tả, màu sắc hex, trường thông tin (Fields).
   * Kiểm tra bản xem trước khớp 100% với giao diện Discord Rich Embed chuẩn.
4. **Cổng Xác Minh & Anti-Raid (`/dashboard/<id>/verify`)**:
   * Thử bật công tắc Toggle Kích hoạt Verify Gate.
   * Chọn kênh xác minh (`#xac-thuc`), vai trò đã xác minh (`@Thành Viên`), vai trò tạm thời (`@Chưa Xác Minh`).
   * Chuyển đổi phương thức xác minh (Nút bấm Button / CAPTCHA emoji).
   * Cấu hình ngưỡng Anti-Raid (số lượng join/khoảng thời gian) và chế độ phong tỏa (Lockdown).
   * Bấm *"Lưu Cài Đặt"* ➔ Kiểm tra hiển thị Toast Notification thành công và trạng thái được lưu vào CSDL.

---

### Kịch Bản 4: Quản Trị Hệ Thống Chủ Bot (`/admin`)
1. **Phân quyền truy cập**:
   * Đăng nhập bằng tài khoản **không phải `BOT_OWNER_ID`** ➔ Kiểm tra hệ thống chặn và trả về HTTP 403 Forbidden.
   * Đăng nhập bằng `BOT_OWNER_ID` ➔ Kiểm tra truy cập thành công vào `/admin`.
2. **Trình điều khiển Web Terminal (`/admin/system/terminal`)**:
   * Gửi lệnh `echo "Zeryn System Ready"` ➔ Kiểm tra terminal trả về kết quả đúng định dạng console đen.
3. **Bộ cấu hình Master AI API Key (`/admin/ai_key`)**:
   * Nhập API Key giả lập và bấm *"Kiểm tra kết nối"* ➔ Kiểm tra hệ thống tự động nhận diện đúng nhà cung cấp (Google Gemini / Groq / OpenRouter).

---

## 📱 4. Kiểm Thử Độ Tương Thích Thiết Bị (Responsive Viewport Matrix)

| Thiết Bị | Độ Phân Giải (Resolution) | Yêu Cầu Kiểm Tra |
| :--- | :--- | :--- |
| **Mobile Phone** | 375 x 812 (iPhone X/12) | Menu Header chuyển thành Hamburger Drawer, các bảng card xếp dọc 1 cột mượt mà |
| **Tablet** | 768 x 1024 (iPad / Tab M8) | Sidebar Dashboard có thể thu gọn, lưới cards hiển thị 2 cột |
| **Desktop** | 1440 x 900 / 1920 x 1080 | Hiển thị đầy đủ Sidebar cố định bên trái, khu vực nội dung chính hiển thị 3-4 cột |

---

## 📊 5. Tiêu Chuẩn Báo Cáo Kết Quả Kiểm Thử (E2E Test Report)

Mỗi lần chạy kiểm thử trình duyệt, Agent báo cáo theo định dạng:
```markdown
### 🧪 Báo Cáo Kiểm Thử E2E Dashboard
- **Tổng số kịch bản**: 6 Scenarios
- **Trạng thái**: [PASS] 6 / 6
- **Thời gian phản hồi trang trung bình**: < 120ms
- **Lỗi JavaScript Console**: 0 Errors
- **Giao diện Responsive**: Hoàn hảo trên Desktop, Tablet, Mobile
```

---

## 🔌 6. Tự Động Hóa Kiểm Thử & Chẩn Đoán Qua MCP Server

Dự án tích hợp giao thức **Model Context Protocol (MCP)** tại `C:\Users\Nam\.gemini\antigravity-ide\mcp_config.json` hỗ trợ tự động hóa kiểm định:
1. **Kiểm tra trạng thái CSDL tức thì (`sqlite` MCP)**:
   * Chạy truy vấn xác minh trạng thái lưu trữ của các bảng sau khi test UI (ví dụ kiểm tra bảng `guild_modules`, `verify_settings`, `music_song_cache`).
2. **Kiểm tra sức khỏe thiết bị từ xa (`termux` MCP)**:
   * Sau khi hoàn tất kiểm thử, gọi tool `termux_get_status` để kiểm tra mức tiêu thụ RAM (`free -h`) và tiến trình watchdog trên thiết bị Tecno Pova 2 thực tế.
   * Đọc trực tiếp log thời gian thực qua `termux_read_logs` để phát hiện các lỗi ngầm (Silent Exceptions) mà UI không hiển thị.

---

## 🛡️ 7. Kịch Bản Kiểm Thử An Ninh & Đồng Thời (Security & Concurrency Test Scenarios)

Dành cho việc kiểm thử tự động và bán tự động các lớp phòng thủ mới (v3.0 Security Defense-in-Depth):

### Kịch Bản 7.1: Phòng Chống Stored XSS trong Embed Builder (`/dashboard/<id>/embeds`)
1. **Kiểm tra Payload Script Injection**:
   - Nhập payload vào các trường Title, Description, Field Name, Field Value, Author Name, Footer Text:
     `<script>alert(1)</script><img src=x onerror=alert('xss')>`
   - Kiểm tra khung Live Preview: Chuỗi payload phải hiển thị dưới dạng văn bản thô (plain text via `textContent`), tuyệt đối không được thực thi mã JavaScript và không render thẻ HTML nguy hiểm.
2. **Kiểm tra Protocol Whitelisting**:
   - Nhập Title URL dạng nguy hiểm: `javascript:alert(document.cookie)` hoặc `data:text/html,...`.
   - Kiểm tra thuộc tính `href` trong DOM preview: Không được tạo liên kết hoặc tự động bị gỡ bỏ, chỉ chấp nhận giao thức `http:` và `https:`.
3. **Kiểm tra Tải Dữ Liệu An Toàn**:
   - Dữ liệu embed khởi tạo được nạp qua `<script type="application/json">` thay vì inline JavaScript variables.

### Kịch Bản 7.2: Xác Thực & Phân Quyền API Dashboard (`/api/guild/<id>/...`)
1. **Kiểm tra Phân Quyền Vai Trò (RBAC)**:
   - Gửi request `POST /api/guild/<id>/settings` với user không có quyền `Administrator` / `Manage Server` và không thuộc `bot_admin_roles`.
   - Kết quả mong đợi: HTTP 403 Forbidden `{ok: false, error: "Access denied"}`.
2. **Kiểm tra Tự Động Làm Mới Quyền Hạn (Session TTL)**:
   - Giả lập phiên đăng nhập cũ vượt quá `SESSION_GUILD_TTL` (10 phút).
   - Gửi yêu cầu API: Hệ thống phải tự động kích hoạt làm mới danh sách quyền hạn máy chủ từ Discord API hoặc từ chối hợp lệ khi hết hạn refresh token.

### Kịch Bản 7.3: Phòng Chống Tấn Công SSRF (Server-Side Request Forgery)
1. **Kiểm tra Phân Giải DNS & Lọc Địa Chỉ Nội Bộ**:
   - Thử nghiệm gửi các URL kiểm tra tới `/summarize` hoặc Image Downloaders (`card_generator.py`, `ai.py`):
     - Loopback: `http://127.0.0.1:5000/`, `http://localhost/`, `http://[::1]/`
     - Private IP: `http://192.168.1.1/`, `http://10.0.0.1/`
     - Decimal IP: `http://2130706433` (tương đương `127.0.0.1`)
     - Cloud Metadata: `http://169.254.169.254/latest/meta-data/`
   - Kết quả mong đợi: `is_safe_http_url` phân giải qua `socket.getaddrinfo`, phát hiện IP nội bộ và trả về `False`, chặn tải nội dung ngay từ vòng ngoài.
2. **Kiểm tra Giới Hạn Kích Thước Tải (RAM Guard)**:
   - Thử tải luồng dữ liệu vượt quá 5MB. Kết quả: Ngắt kết nối sớm (Early Termination), bảo vệ bộ nhớ RAM Termux không bị tràn bộ nhớ (OOM).

### Kịch Bản 7.4: Phòng Chống IDOR Kênh Máy Chủ (Cross-Guild Channel IDOR)
1. **Kiểm tra Thiết Lập Kênh Khác Guild**:
   - Gửi API `POST /api/guild/<guild_A>/welcome` với `channel_id` thuộc `<guild_B>`.
   - Kết quả mong đợi: API trả về HTTP 400 Bad Request `{ok: false, error: "Channel does not belong to this server"}` nhờ cơ chế xác thực `_require_channel_in_guild`.
2. **Kiểm tra Bắn Sự Kiện Welcome / Goodbye**:
   - Sự kiện thành viên gia nhập máy chủ sử dụng `member.guild.get_channel(cid)`. Nếu kênh đã bị cấu hình sai hoặc trỏ sang máy chủ khác, bot sẽ bỏ qua an toàn, tuyệt đối không gửi tin nhắn rò rỉ sang kênh ngoài guild.

### Kịch Bản 7.5: Kiểm Thử Đua Lệnh Kinh Tế (Race Condition & Concurrency)
1. **Kiểm thử Nạp / Rút Tiền Đồng Thời (`/deposit`, `/withdraw`)**:
   - Tạo 10 luồng bất đồng bộ gửi yêu cầu rút 100 coin từ tài khoản chỉ có 100 coin trong cùng một mili-giây.
   - Kết quả mong đợi: Nhờ câu lệnh SQL nguyên tử `WHERE wallet >= ?` / `WHERE bank >= ?`, chính xác 1 luồng thành công (`rowcount == 1`) và 9 luồng thất bại (`rowcount == 0`), số dư cuối cùng là 0 coin, không bao giờ bị âm tiền.
2. **Kiểm thử Deadlock Chuyển Tiền (`/pay`)**:
   - Cho User A và User B chuyển tiền qua lại đồng thời trong 20 tác vụ song song.
   - Kết quả mong đợi: Không xuất hiện lỗi `sqlite3.OperationalError: database is locked`, toàn bộ giao dịch được xử lý trơn tru trên một kết nối duy nhất (`single-connection transaction`).


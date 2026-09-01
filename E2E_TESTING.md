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
   * Kiểm tra hiển thị đầy đủ danh sách **57 Lệnh** được nạp từ `_COMMANDS_DATA`.
   * Thử tìm kiếm lệnh trên ô Search (ví dụ: gõ `deposit` -> lọc đúng lệnh nạp tiền ngân hàng).
   * Thử chuyển đổi danh mục (Kinh tế & Shop, Nhạc 24/7, Kiểm duyệt, v.v.).
3. **Mở URL `/tos` và `/privacy`**:
   * Kiểm tra thanh mục lục bên trái (Sticky TOC) cuộn mượt mà (smooth scrolling) tới từng phần.

---

### Kịch Bản 2: Quản Lý Cài Đặt Server & Bật/Tắt Module (`/server/<id>/...`)
1. **Mở URL `/server/999999999999999999/overview`**:
   * Kiểm tra hiển thị thông tin máy chủ (Tên, Số lượng thành viên, Ngôn ngữ).
   * Thử đổi ngôn ngữ máy chủ (Tiếng Việt ➔ English) ➔ Kiểm tra giao diện cập nhật ngay lập tức.
2. **Kiểm tra công tắc Module Toggle**:
   * Bấm tắt/bật một module bất kỳ (ví dụ: `music` hoặc `economy`).
   * Kiểm tra API `/server/<id>/module/<name>` trả về HTTP 200 `{success: true}`.
   * Kiểm tra xuất hiện thông báo nổi (Toast Notification) màu xanh lá ở góc màn hình.

---

### Kịch Bản 3: Xem Trước Trực Tiếp (Live Previews)
1. **Module Leveling (`/server/<id>/leveling`)**:
   * Thử chọn màu chủ đạo và ảnh nền thẻ Rank.
   * Bấm nút *"Xem trước Thẻ Rank"* ➔ Kiểm tra Canvas hoặc ảnh preview được render mượt mà trong modal.
2. **Module Welcome & Goodbye (`/server/<id>/welcome`)**:
   * Nhập nội dung tin nhắn chào mừng kèm biến `{user}`, `{server}`, `{members}`.
   * Kiểm tra khung xem trước tin nhắn (Live Embed Preview) thay thế biến động thời gian thực.
3. **Embed Builder (`/server/<id>/embeds`)**:
   * Thêm tiêu đề, mô tả, màu sắc hex, trường thông tin (Fields).
   * Kiểm tra bản xem trước khớp 100% với giao diện Discord Rich Embed chuẩn.

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

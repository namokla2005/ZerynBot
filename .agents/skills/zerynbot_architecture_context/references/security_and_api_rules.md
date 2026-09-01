# 🔒 Quy Định Bảo Mật & Tiêu Chuẩn Viết API Cho ZerynBot V2

Tài liệu này quy định các tiêu chuẩn an ninh, bảo mật thông tin và quy tắc viết API/Database cho toàn bộ hệ thống ZerynBot V2.

---

## 1. Bảo Mật Xác Thực & Phân Quyền (Authentication & Authorization)

### 1.1 Phân Quyền Quản Trị Viên Máy Chủ (Guild Admin)
* Mọi route quản lý cài đặt máy chủ trên Web Dashboard (`/server/<guild_id>/...`) **BẮT BUỘC** phải có decorator kiểm tra quyền:
  * `@login_required`: Đảm bảo phiên người dùng Discord OAuth2 còn hiệu lực (`session.get('user')`).
  * `@guild_admin_required`: Kiểm tra người dùng có quyền `ADMINISTRATOR` hoặc `MANAGE_GUILD` trên server đó.
* Tuyệt đối không cho phép người dùng sửa đổi cấu hình của server mà họ không có quyền quản lý thông qua việc sửa `guild_id` trên URL.

### 1.2 Cách Ly Trang Quản Trị Chủ Bot (Master Bot Admin `/admin`)
* Trang `/admin` và các API nội bộ (`/admin/system/*`, `/api/admin/*`) **CHỈ CHO PHÉP** tài khoản có Discord ID khớp chính xác với `config.BOT_OWNER_ID`.
* **Master AI API Keys**: Khóa API của Google Gemini, Groq Cloud, OpenRouter được lưu trữ tập trung tại bảng `bot_global_settings`. Không bao giờ trả về toàn bộ chuỗi API Key qua API công khai hoặc nhúng lộ ra mã nguồn HTML/JS máy khách.

---

## 2. Bảo Mật Sao Lưu Cơ Sở Dữ Liệu (`BACKUP_DB`)

> [!WARNING]
> **Quy Tắc Tuyệt Đối Về Sao Lưu Dữ Liệu**:
> File cơ sở dữ liệu `bot.db` chứa dữ liệu nhạy cảm (cấu hình, tin nhắn kiểm duyệt, tài khoản kinh tế, custom commands).
> - Tất cả tác vụ sao lưu tự động 24h (`auto_backup_task`) và lệnh thủ công của chủ bot (`/backup`) **BẮT BUỘC** phải gửi file `.zip` về Webhook riêng tư `BACKUP_DB` (`config.BACKUP_DB_URL`).
> - **KHÔNG ĐƯỢC PHÉP** gửi file backup vào kênh log chung của Discord server hoặc bất kỳ kênh chat công khai nào.

---

## 3. Quy Chuẩn Viết Hàm API (REST / JSON Endpoints)

Mọi API endpoint trong [`dashboard/api.py`](file:///d:/Project/Discord%20Bots/v2/dashboard/api.py) phải tuân thủ chuẩn phản hồi JSON sau:

### 3.1 Cấu Trúc Phản Hồi Thành Công (HTTP 200)
```json
{
  "success": true,
  "message": "Cập nhật cài đặt thành công",
  "data": {
    "module": "automods",
    "enabled": true
  }
}
```

### 3.2 Cấu Trúc Phản Hồi Thất Bại (HTTP 400 / 403 / 500)
```json
{
  "success": false,
  "error": "Tham số không hợp lệ",
  "code": "INVALID_PARAMS"
}
```

### 3.3 Chống Tấn Công SQL Injection
* **TUYỆT ĐỐI KHÔNG** nối chuỗi trực tiếp vào câu lệnh SQL (`f"SELECT * FROM table WHERE id = {user_id}"`).
* **LUÔN LUÔN** dùng tham số hóa có sẵn của SQLite:
  ```python
  # Chuẩn an toàn:
  await db.execute("SELECT * FROM guilds WHERE guild_id = ?", (guild_id,))
  ```

---

## 4. Bảo Mật Web Terminal & Lệnh Hệ Thống

* Các lệnh thực thi trong Web Terminal (`/admin/system/terminal`) chỉ được phép kích hoạt bởi `BOT_OWNER_ID`.
* Khi gọi các lệnh khởi động lại (`python main.py --restart`), phải sử dụng `subprocess.Popen` ở chế độ **tách rời (detached process)** để Flask trả về HTTP 200 ngay lập tức, tránh bị nghẽn tiến trình gây lỗi HTTP 502 Bad Gateway.

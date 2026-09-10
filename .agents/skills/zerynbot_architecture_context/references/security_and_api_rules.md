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

Mọi API endpoint trong [`dashboard/api.py`](https://github.com/namokla2005/ZerynBot/blob/main/dashboard/api.py) phải tuân thủ chuẩn phản hồi JSON sau:

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

---

## 5. Phòng Chống Tấn Công SSRF Thực Thụ (True DNS Resolution & Stream Guard)

Khi hệ thống tải dữ liệu từ URL do người dùng cung cấp (như ảnh nền card, tóm tắt tin tức AI `/summarize`):
* **Phân giải DNS thực (`socket.getaddrinfo`)**: Không chỉ kiểm tra chuỗi URL bề mặt (như `localhost` hay `127.0.0.1`), hàm `is_safe_http_url` bắt buộc phân giải tên miền thành địa chỉ IP thực tế trước khi kết nối.
* **Chặn toàn diện các dải IP cấm**:
  - Dải IP Loopback: `127.0.0.0/8`, `::1`.
  - Dải IP Private RFC 1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
  - Dải Link-Local & Cloud Metadata: `169.254.0.0/16`, `fe80::/10`.
  - Kỹ thuật bypass IP thập phân (Decimal / Dword IP, e.g. `http://2130706433` ➔ tự động chuyển đổi và phát hiện IP nội bộ).
* **Kiểm tra từng bước chuyển hướng (Hop-by-hop Redirect Inspection)**: Tắt tính năng tự động theo dõi chuyển hướng (`allow_redirects=False`) để thẩm định tính an toàn của từng URL trong chuỗi redirect.
* **Giới hạn dung lượng tải luồng (Stream Guard)**: Đọc theo từng chunk với trần tối đa 5MB. Ngắt kết nối ngay nếu vượt quá giới hạn để bảo vệ bộ nhớ RAM Termux.

---

## 6. Phòng Chống Stored XSS trong Web Dashboard (DOM TextContent & Protocol Whitelist)

* **Tuyệt đối không nối chuỗi vào `innerHTML`**: Trong JavaScript phía máy khách (như `embed_builder.js`), mọi dữ liệu cấu hình hoặc nội dung do người dùng nhập phải được gán vào phần tử DOM thông qua thuộc tính `.textContent` hoặc `document.createTextNode()`.
* **Kiểm duyệt giao thức URL (Protocol Whitelisting)**: Thuộc tính liên kết (`href`) chỉ được phép chấp nhận các giao thức an toàn `http:` hoặc `https:`. Mọi giao thức nguy hiểm như `javascript:`, `data:`, `vbscript:` phải bị chặn và gỡ bỏ ngay lập tức.
* **Nạp dữ liệu cấu hình an toàn**: Dữ liệu cấu hình phức tạp truyền từ Flask Jinja2 sang JavaScript phải được đóng gói trong thẻ `<script id="data" type="application/json">` và phân tích qua `JSON.parse(element.textContent)` để tránh lỗi injection khi render inline.

---

## 7. Phòng Chống IDOR & Rò Rỉ Kênh Máy Chủ (Cross-Guild Channel IDOR Defense)

* **Phạm vi phân giải kênh trong Bot Event**: Khi xử lý sự kiện chào mừng/tạm biệt hoặc gửi thông báo máy chủ, **tuyệt đối không** sử dụng phương thức tìm kiếm kênh toàn cục `self.bot.get_channel(channel_id)`. Bắt buộc dùng `member.guild.get_channel(channel_id)` để đảm bảo kênh đích thực sự thuộc máy chủ đang diễn ra sự kiện, triệt tiêu nguy cơ rò rỉ dữ liệu hoặc gửi nhầm tin nhắn sang server khác.
* **Kiểm tra quyền sở hữu kênh trên Dashboard API**: Mọi API nhận tham số `channel_id` (ví dụ: cài đặt kênh log, kênh welcome, kênh verify) phải gọi hàm xác thực `_require_channel_in_guild(guild_id, channel_id)` trước khi lưu vào cơ sở dữ liệu.

---

## 8. Quy Chuẩn Giao Dịch CSDL Nguyên Tử & Chống Deadlock SQLite

* **Cập nhật có điều kiện nguyên tử (Atomic Conditional Updates)**: Trừ tiền ví, ngân hàng hoặc giảm số lượng vật phẩm phải sử dụng câu lệnh SQL điều kiện:
  ```sql
  UPDATE economy_users SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ? AND wallet >= ?;
  ```
  Kiểm tra `cursor.rowcount == 1` để xác nhận thành công. Tuyệt đối không kiểm tra số dư trong RAM rồi mới thực thi lệnh ghi độc lập.
* **Giao dịch đơn kết nối (Single-Connection Transactions)**: Tất cả các thao tác liên quan trong một quy trình giao dịch (như `/pay`) phải chia sẻ chung một kết nối `aiosqlite.connect`, thực thi `INSERT OR IGNORE` đối tượng nhận trên chính kết nối đó và gọi `commit()` duy nhất ở cuối để ngăn chặn SQLite lock tranh chấp giữa các luồng.


---
name: ops_and_troubleshooting
description: >
  Operational troubleshooting, 24/7 ARM/Termux deployment, watchdog health checks,
  SQLite WAL checkpointing, and private backup recovery for ZerynBot V2.
---

# Skill: Operations & Troubleshooting Guide (24/7 ARM / Termux)

## 🎯 1. Mục Đích & Môi Trường Triển Khai

Tài liệu này cung cấp SOP vận hành, giám sát sức khỏe tiến trình và xử lý sự cố cho ZerynBot V2 trên môi trường **Android Termux (ARM64)** chạy 24/7.

---

## 🔍 2. Hệ Thống Quản Lý Tiến Trình (Multi-Tier Process Discovery)

### 2.1 Cơ Chế 3 Lớp Xác Định Trạng Thái Sống Của Bot (`main.py`)
Khi máy chủ restart hoặc tiến trình bị tắt đột ngột, file `data/bot.pid` có thể chứa PID cũ (Stale PID). Hàm `get_live_bot_pid()` thực hiện kiểm tra 3 tầng:

1. **Tầng 1 (PID File Check)**: Đọc PID từ `data/bot.pid` và kiểm tra xem tiến trình có thực sự tồn tại trong OS hay không (`os.kill(pid, 0)`).
2. **Tầng 2 (Heartbeat Check)**: Đọc `data/health.json` (do bot cập nhật mỗi 60 giây). Nếu timestamp quá cũ (>5 phút), tiến trình bị coi là đã chết/treo.
3. **Tầng 3 (Process Tree Scanning)**: Quét danh sách tiến trình hệ thống bằng `pgrep` trên Linux/Termux để tìm PID thực tế của `bot.py` và tự động chữa lành file `data/bot.pid`.

### 2.2 Các Lệnh Điều Khiển CLI Chuẩn:
```bash
python main.py start       # Khởi chạy cả Bot và Web Dashboard nền
python main.py stop        # Dừng an toàn toàn bộ tiến trình
python main.py restart     # Khởi động lại toàn bộ hệ thống
python main.py status      # Kiểm tra trạng thái sống thời gian thực
python main.py test        # Chạy kiểm thử tự động toàn diện
```

---

## 🗄️ 3. Quản Trị Cơ Sở Dữ Liệu SQLite WAL Mode

### 3.1 Cấu Hình Bắt Buộc
- `PRAGMA journal_mode = WAL;` (Write-Ahead Logging cho phép Bot đọc và Dashboard ghi đồng thời không khóa CSDL).
- `PRAGMA synchronous = NORMAL;` (Giảm bớt I/O đĩa mà vẫn an toàn dữ liệu).
- `PRAGMA busy_timeout = 15000;` (Chờ tối đa 15 giây khi có ghi đồng thời trước khi báo lỗi `database is locked`).

### 3.2 Cơ Chế Dọn Dẹp WAL Định Kỳ
Để file `bot.db-wal` không bị phình to làm chậm thiết bị, tác vụ `auto_backup_task` (chạy mỗi 24h lúc 03:00 sáng) tự động thực hiện:
```sql
PRAGMA wal_checkpoint(TRUNCATE);
```

---

## 🔒 4. Quy Trình Sao Lưu & Phục Hồi Dữ Liệu (`BACKUP_DB`)

### 4.1 Quy Tắc Sao Lưu An Toàn
- File cơ sở dữ liệu `bot.db` được nén thành `.zip` kèm timestamp.
- File `.zip` **chỉ được gửi đến Webhook riêng tư `config.BACKUP_DB_URL`**.
- Tuyệt đối không gửi vào kênh Discord công khai.

### 4.2 Quy Trình Phục Hồi (Disaster Recovery SOP)
Khi gặp sự cố hỏng hóc CSDL:
1. Dừng bot: `python main.py stop`
2. Tải bản backup `.zip` mới nhất từ kênh Webhook Discord riêng tư `BACKUP_DB`.
3. Giải nén và thay thế file `data/bot.db`.
4. Xóa các file thừa nếu có: `rm -f data/bot.db-wal data/bot.db-shm`
5. Khởi động lại bot: `python main.py start`

---

## 🛠️ 5. Bộ Script Tự Động Hóa Trong `assets/`

- ⚡ **[`validate_all.py`](../zerynbot_architecture_context/assets/validate_all.py)**: Kiểm thử toàn diện 1-Click (i18n + Python compilation + commands count + doc sync).
- 🧪 **[`validate_i18n.py`](../zerynbot_architecture_context/assets/validate_i18n.py)**: Kiểm thử parity 1587 keys giữa 6 ngôn ngữ.
- 🗄️ **[`check_db_schema.py`](../zerynbot_architecture_context/assets/check_db_schema.py)**: Kiểm tra cấu trúc CSDL và các lệnh Migration an toàn.

---

## 🔌 6. Quản Trị Hệ Thống Từ Xa Qua MCP Server (Model Context Protocol)

Để AI có thể tự động gỡ lỗi, kiểm tra sức khỏe và điều khiển bot trên thiết bị Android Termux từ xa (không cần người dùng copy-paste log thủ công), dự án tích hợp hệ thống MCP Server chuẩn:

### 6.1 Kiến Trúc MCP Của ZerynBot
- **File cấu hình IDE Antigravity**: `C:\Users\Nam\.gemini\antigravity-ide\mcp_config.json`
- **Máy chủ SQLite MCP**: `uvx mcp-server-sqlite --db-path d:\Project\Discord Bots\v2\data\bot.db`
- **Máy chủ Termux Manager MCP**: `python scripts/termux_mcp.py` kết nối trực tiếp qua Paramiko SSH (port 8022).

### 6.2 Các Công Cụ MCP Hỗ Trợ (Mapped 100% Với `main.py`)
| Tool MCP | Lệnh Chạy Trên Termux | Mục Đích |
| :--- | :--- | :--- |
| `termux_system_restart` | `python main.py --restart` | Khởi động lại toàn bộ Bot + Dashboard an toàn |
| `termux_system_stop` | `python main.py --stop` | Dừng sạch tiến trình và gửi Webhook thông báo |
| `termux_system_test` | `python main.py --test` | Chạy bộ tự chẩn đoán lỗi `SystemTester` |
| `termux_get_status` | `free -h` & `ps -ef \| grep python` | Kiểm tra tài nguyên RAM/Swap và trạng thái PID |
| `termux_read_logs` | `tail -n <lines> data/bot.log` | Đọc trực tiếp log thời gian thực mà không cần gõ `cat` |
| `termux_git_pull` | `git pull origin main` | Tự động đồng bộ mã nguồn mới nhất từ GitHub |
| `termux_run_command` | `<command>` | Chạy lệnh bash tùy chỉnh trong thư mục bot |

### 6.3 Kết Nối Xuyên Mạng (Khi Không Ở Chung Mạng Wi-Fi)
- **Khi ở nhà**: Kết nối trực tiếp qua LAN IP `192.168.2.50:8022`.
- **Khi ở ngoài (trường học, cafe, 4G)**: Cài đặt **Tailscale** trên điện thoại Tecno Pova 2 và Windows PC. Cập nhật `TERMUX_HOST` thành IP ảo cố định `100.x.y.z` trong `mcp_config.json` để duy trì kết nối mọi lúc mọi nơi.

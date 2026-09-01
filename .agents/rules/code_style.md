# 🎯 Quy Chuẩn Lập Trình & Viết Code (Code Style Rules)

Tài liệu này áp dụng tự động cho toàn bộ mã nguồn của dự án **ZerynBot V2**:

---

## 1. Quy Chuẩn Git Commit
- Tuân thủ chuẩn **Conventional Commits**:
  - `feat:` Thêm tính năng, lệnh, hoặc module mới
  - `fix:` Sửa lỗi hoặc xử lý bug
  - `docs:` Cập nhật tài liệu (`ARCHITECTURE.md`, `README.md`, `AGENTS.md`, `llms.txt`)
  - `style:` Tinh chỉnh giao diện CSS, format hiển thị
  - `refactor:` Tái cấu trúc code mà không thay đổi tính năng
- Dòng tiêu đề commit viết bằng tiếng Anh hoặc tiếng Việt rõ nghĩa, tối đa 72 ký tự.

---

## 2. Quy Chuẩn Viết Code Python
- **Không hardcode chuỗi hiển thị**: Luôn dùng hàm `tr(settings, "key", ...)` cho bot hoặc `t("key")` cho dashboard.
- **Không hardcode magic numbers**: Đưa vào `config.py` hoặc hằng số ở đầu file.
- **Phân tách Async / Sync**:
  - `bot/cogs/` chỉ dùng hàm `async_*` (aiosqlite).
  - `dashboard/` chỉ dùng hàm đồng bộ `get_*` (sqlite3).
- **Kiểm tra cú pháp trước khi commit**:
  ```bash
  python -c "import py_compile; py_compile.compile('path/to/file.py', doraise=True)"
  ```

---

## 3. Quy Chuẩn CSS & Giao Diện Web
- Sử dụng **Vanilla CSS** thuần túy với CSS variables có sẵn trong `:root`.
- Không tự ý thêm thư viện ngoài như TailwindCSS khi chưa được yêu cầu.
- Luôn gắn version `?v=9.2` vào mọi thẻ `<link>` stylesheet.

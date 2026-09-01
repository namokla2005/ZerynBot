---
name: zerynbot_architecture_context
description: >
  Use ARCHITECTURE.md and the workspace context as the primary source of truth for ZerynBot V2.
  Read it before writing or modifying any code. Contains standard operating procedures (SOP),
  5-step command creation checklist, i18n validator, references, and code templates.
---

# Skill: ZerynBot V2 — Architecture-First Context & SOP

## 🎯 1. Mục Đích & Phạm Vi
Kỹ năng này cung cấp bộ quy chuẩn tác nghiệp chuẩn (SOP), danh mục tài liệu chuyên sâu trong `references/` và mã nguồn mẫu trong `assets/` để AI phát triển và bảo trì **ZerynBot V2** với chất lượng cao nhất, không gây lỗi hồi quy (regression bugs).

---

## 📖 2. Quy Trình Tiếp Nhận & Đọc Tài Liệu

Trước khi thực hiện bất kỳ thay đổi nào trong dự án, AI **BẮT BUỘC** đọc tệp kiến trúc chính:
- 📖 [`ARCHITECTURE.md`](file:///d:/Project/Discord%20Bots/v2/ARCHITECTURE.md)

Khi xử lý các bài toán chuyên biệt, AI đọc thêm tài liệu tương ứng trong thư mục `references/`:
1. 🔒 **Bảo mật & Quy tắc API**: [`.agents/skills/zerynbot_architecture_context/references/security_and_api_rules.md`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/references/security_and_api_rules.md)
2. 🎨 **Thiết kế Web & Hướng dẫn Avatar Mascot**: [`.agents/skills/zerynbot_architecture_context/references/design_and_avatar_guide.md`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/references/design_and_avatar_guide.md)
3. 🧪 **Kiểm thử tự động Web Dashboard**: [`E2E_TESTING.md`](file:///d:/Project/Discord%20Bots/v2/E2E_TESTING.md)

---

## 📋 3. Checklist 5 Bước Chuẩn Khi Thêm Lệnh / Tính Năng Mới

Mỗi khi tạo một lệnh Discord hoặc tính năng mới, AI phải hoàn thành đủ **5 bước bắt buộc**:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. Logic Cog    │ ──► │ 2. CSDL SQLite  │ ──► │ 3. Đa Ngôn Ngữ  │
│ (bot/cogs/*.py) │     │ (database.py)   │     │ (locales/*.json)│
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
                        ┌─────────────────┐              ▼
                        │ 5. Đồng Bộ Docs │ ◄── ┌─────────────────┐
                        │ (README, ARCH)  │     │ 4. Dashboard    │
                        └─────────────────┘     │ (_COMMANDS_DATA)│
                                                └─────────────────┘
```

1. **Bước 1: Triển khai Cog Logic (`bot/cogs/`)**:
   - Sử dụng decorator `@commands.hybrid_command` hoặc `@app_commands.command`.
   - Bọc **Module Guard** ở đầu hàm (`await async_is_module_enabled(guild_id, module_name)`).
   - Sử dụng hàm `tr(settings, key, **kwargs)` cho mọi phản hồi hiển thị.
   - Bắt lỗi và log chi tiết.

2. **Bước 2: Triển khai CSDL SQLite (`database.py`)**:
   - Viết các hàm `async_*` (dùng `aiosqlite`) cho Bot và hàm đồng bộ (dùng `sqlite3`) cho Dashboard.
   - Nếu cần thêm cột vào bảng có sẵn, sử dụng cơ chế **Migration an toàn**:
     ```python
     try:
         await db.execute("ALTER TABLE table_name ADD COLUMN new_column TEXT DEFAULT ''")
     except Exception:
         pass  # Cột đã tồn tại, bỏ qua an toàn
     ```

3. **Bước 3: Bổ sung Từ Điển Đa Ngôn Ngữ (`locales/*.json`)**:
   - Bổ sung bộ key mới vào **TOÀN BỘ 6 TỆP** (`vi.json`, `en.json`, `zh.json`, `es.json`, `pt.json`, `fr.json`).
   - Đảm bảo 100% không lệch key, số lượng key giữa 6 tệp phải bằng nhau tuyệt đối (**1510 keys/file**).
   - Chạy script kiểm tra tự động: `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py`.

4. **Bước 4: Đăng Ký Vào Web Dashboard (`dashboard/app.py`)**:
   - Thêm thông tin lệnh vào danh sách tập trung `_COMMANDS_DATA` trong `dashboard/app.py` để lệnh hiển thị đầy đủ trên trang `/commands` (hiện có **87 lệnh** thuộc **16 danh mục**).

5. **Bước 5: Cập nhật Tài Liệu & Đồng Bộ**:
   - Cập nhật số lượng lệnh & key trong [`ARCHITECTURE.md`](file:///d:/Project/Discord%20Bots/v2/ARCHITECTURE.md), [`README.md`](file:///d:/Project/Discord%20Bots/v2/README.md), [`.agents/AGENTS.md`](file:///d:/Project/Discord%20Bots/v2/.agents/AGENTS.md), [`llms.txt`](file:///d:/Project/Discord%20Bots/v2/llms.txt).

---

## 📂 4. Danh Mục Mã Mẫu & Công Cụ (Assets Directory)

Thư mục `assets/` chứa các tệp mẫu và công cụ kiểm thử tự động 1-click:
- ⚡ **[`assets/validate_all.py`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/assets/validate_all.py)**: Bộ kiểm thử toàn diện 1-Click (i18n + Python compilation + commands count + doc sync).
- 🌐 **[`assets/validate_i18n.py`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/assets/validate_i18n.py)**: Script kiểm thử tự động đồng bộ key i18n (1510 keys).
- 🗄️ **[`assets/check_db_schema.py`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/assets/check_db_schema.py)**: Kiểm tra cấu trúc CSDL SQLite và tính an toàn của các câu lệnh Migration.
- 🧩 **[`assets/cog_template.py`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/assets/cog_template.py)**: Code mẫu Cog chuẩn cho Discord Bot.
- 🌐 **[`assets/endpoint_template.py`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/assets/endpoint_template.py)**: Code mẫu Route & AJAX API cho Flask Dashboard.

---

## 🔍 5. Quy Chuẩn Git Commit

Tuân thủ chuẩn **Conventional Commits** (`feat:`, `fix:`, `docs:`, `refactor:`), commit code kèm tài liệu đồng bộ trong một lần:
```bash
git add .
git commit -m "feat(module): <mô tả ngắn gọn tính năng> + update ARCHITECTURE.md & docs"
git push origin main
```

# 📚 Quy Tắc Đồng Bộ Tài Liệu Bắt Buộc (Documentation Sync Rules)

Mỗi khi thực hiện thay đổi mã nguồn, AI **BẮT BUỘC** đồng bộ tài liệu theo danh sách sau:

---

## 1. Khi Thêm / Xóa Lệnh Discord
- Đăng ký lệnh vào `_COMMANDS_DATA` trong `dashboard/app.py`.
- Cập nhật số lượng lệnh trong:
  - [`ARCHITECTURE.md`](file:///d:/Project/Discord%20Bots/v2/ARCHITECTURE.md) (mục 6)
  - [`.agents/AGENTS.md`](file:///d:/Project/Discord%20Bots/v2/.agents/AGENTS.md) (mục 4)
  - [`llms.txt`](file:///d:/Project/Discord%20Bots/v2/llms.txt) (mục Key Project Files)

---

## 2. Khi Thêm / Xóa / Thay Đổi i18n Keys
- Cập nhật đủ **6 file từ điển** trong `locales/` (`vi`, `en`, `zh`, `es`, `pt`, `fr`).
- Chạy validator:
  ```bash
  python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py
  ```
- Cập nhật con số key chính xác trong:
  - [`ARCHITECTURE.md`](file:///d:/Project/Discord%20Bots/v2/ARCHITECTURE.md) (mục 1, 2, 9)
  - [`.agents/AGENTS.md`](file:///d:/Project/Discord%20Bots/v2/.agents/AGENTS.md) (mục 4)
  - [`llms.txt`](file:///d:/Project/Discord%20Bots/v2/llms.txt) (mục System Architecture, Key Files)
  - [`.agents/skills/zerynbot_architecture_context/SKILL.md`](file:///d:/Project/Discord%20Bots/v2/.agents/skills/zerynbot_architecture_context/SKILL.md) (mục 3)

---

## 3. Khi Thay Đổi AI Model / Routing
- Cập nhật danh sách model trong `dashboard/templates/admin.html`.
- Cập nhật fallback chain trong `bot/cogs/ai.py`.
- Cập nhật `ARCHITECTURE.md` (mục 11).
- Cập nhật `.agents/skills/ai_provider_routing/references/groq_active_models.md`.

---

## 4. Kiểm Thử & Git Commit
- Luôn chạy kiểm tra syntax Python: `py_compile`.
- Commit chung file code + file tài liệu trong **cùng 1 commit**.
- Luôn `git push origin main` sau khi hoàn thành.

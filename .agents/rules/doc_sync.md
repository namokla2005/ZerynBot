# 📚 Quy Tắc Đồng Bộ Tài Liệu Bắt Buộc (Documentation Sync Rules)

Mỗi khi thực hiện thay đổi mã nguồn, AI **BẮT BUỘC** đồng bộ tài liệu theo danh sách sau:

---

## 1. Khi Thêm / Xóa Lệnh Discord
- Đăng ký lệnh vào `_COMMANDS_DATA` trong `dashboard/app.py`.
- Cập nhật số lượng lệnh trong:
  - [`ARCHITECTURE.md`](https://github.com/namokla2005/ZerynBot/blob/main/ARCHITECTURE.md) (mục 6)
  - [`.agents/AGENTS.md`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/AGENTS.md) (mục 4)
  - [`llms.txt`](https://github.com/namokla2005/ZerynBot/blob/main/llms.txt) (mục Key Project Files)

---

## 2. Khi Thêm / Xóa / Thay Đổi i18n Keys
- Cập nhật đủ **6 file từ điển** trong `locales/` (`vi`, `en`, `zh`, `es`, `pt`, `fr`).
- Chạy validator:
  ```bash
  python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py
  ```
- Cập nhật con số key chính xác trong:
  - [`ARCHITECTURE.md`](https://github.com/namokla2005/ZerynBot/blob/main/ARCHITECTURE.md) (mục 1, 2, 9)
  - [`.agents/AGENTS.md`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/AGENTS.md) (mục 4)
  - [`llms.txt`](https://github.com/namokla2005/ZerynBot/blob/main/llms.txt) (mục System Architecture, Key Files)
  - [`.agents/skills/zerynbot_architecture_context/SKILL.md`](https://github.com/namokla2005/ZerynBot/blob/main/.agents/skills/zerynbot_architecture_context/SKILL.md) (mục 3)

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

---

## 5. Tự Động Deploy Lên Termux & Khởi Động Lại (Auto-Deploy)
- Ngay sau khi hoàn tất `git push origin main`, AI **BẮT BUỘC phải chạy**:
  ```bash
  python scripts/termux_deploy.py
  ```
- Lệnh này tự động kết nối SSH tới Termux, kéo code mới nhất (`git pull origin main`) và khởi động lại toàn bộ hệ thống (`python main.py --restart`).
- Báo cáo kết quả pull & restart cho người dùng.

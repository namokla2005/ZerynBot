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

## 5. Tự Động Deploy, Kiểm Thử Toàn Diện & Sửa Lỗi Trên Termux (Auto-Deploy, Test & Auto-Repair)
- Ngay sau khi hoàn tất `git push origin main`, AI **BẮT BUỘC phải chạy**:
  ```bash
  python scripts/termux_deploy.py
  ```
- Lệnh này tự động kết nối SSH tới Termux, kéo code mới nhất (`git pull origin main`), khởi động lại hệ thống (`python main.py --restart`), và **kiểm tra toàn diện 4 bước**:
  1. Kiểm tra trạng thái tiến trình thực tế (`python main.py --status`).
  2. Kiểm tra Health Endpoint cục bộ (`curl -s http://localhost:5000/health`).
  3. Kiểm tra log khởi động (`data/bot.log`, `data/dashboard.log`) không có lỗi traceback.
  4. Kiểm thử chức năng toàn bộ 20 modules (`python main.py --test`): Đảm bảo 100% chức năng chạy đúng, không lỗi logic, trả về đúng giá trị.
- **Quy tắc sửa lỗi bắt buộc (Zero-Tolerance Bug Fixing Loop)**:
  - Nếu có bất kỳ lỗi nào (FAIL, TIMEOUT, sai giá trị trả về, traceback): AI **tuyệt đối không được báo xong**.
  - AI phải trích xuất log lỗi, phân tích nguyên nhân, sửa chữa mã nguồn, kiểm tra lại cú pháp, commit, push và deploy lại lên Termux.
  - Lặp lại cho đến khi **100% các thành phần đều Xanh/Khỏe mạnh và 20/20 modules đều PASS**, lúc đó mới được báo cáo hoàn tất cho người dùng.

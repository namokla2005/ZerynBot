---
name: dashboard_dev_guide
description: >
  Standard development guide for ZerynBot V2 Flask Web Dashboard, Jinja2 templates,
  Midnight Obsidian Glassmorphism design system, and AJAX API endpoints.
---

# Skill: Web Dashboard Development Guide

## 🎯 1. Design System Tokens (Midnight Obsidian Glassmorphism)

Tất cả các trang trên Web Dashboard (`dashboard/templates/`) phải tuân thủ chuẩn thiết kế đồng bộ:

### 1.1 CSS Variables & Bảng Màu
```css
:root {
  --bg-primary: #120e24;             /* Midnight Violet Slate */
  --bg-card: rgba(25, 24, 34, 0.85); /* Glassmorphism Card Surface */
  --bg-input: rgba(18, 14, 36, 0.9); /* Form Controls Background */
  --border: rgba(255, 255, 255, 0.08);
  --border-focus: rgba(244, 167, 187, 0.5);
  
  --accent: #f4a7bb;                 /* Sakura Pink (Brand Primary) */
  --accent-purple: #9d8df1;          /* Royal Violet */
  --blurple: #5865f2;                /* Discord Blurple */
  --success: #57f287;                /* Emerald */
  --warning: #fee75c;                /* Amber Gold */
  --danger: #ed4245;                 /* Crimson */
  
  --text-primary: #ffffff;
  --text-secondary: rgba(255, 255, 255, 0.7);
  --text-muted: rgba(255, 255, 255, 0.45);
  
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
}
```

### 1.2 Asset Versioning
Mọi liên kết CSS/JS trong thẻ `<head>` **BẮT BUỘC** gắn phiên bản:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v=9.2">
```

---

## 🛠️ 2. Checklist 7 Bước Khi Tạo Trang Quản Lý Module Mới

Khi tạo thêm trang cài đặt module mới trong Dashboard:

1. **Bước 1**: Đăng ký Module trong `DEFAULT_MODULES` (`database/guilds.py`).
2. **Bước 2**: Viết hàm CSDL `get_<module>_settings()` & `update_<module>_settings()` trong `database/<domain>.py`.
3. **Bước 3**: Thêm Route Flask trong blueprint phù hợp (`dashboard/blueprints/{guild,music,admin,support}.py`) với decorator `@login_required` và `@guild_access_required`.
4. **Bước 4**: Tạo template HTML `dashboard/templates/server_<module>.html` kế thừa từ layout chuẩn hoặc dùng `base_server.html`.
5. **Bước 5**: Thêm link vào Sidebar trong các template server tương ứng.
6. **Bước 6**: Bổ sung từ điển đa ngôn ngữ (`<module>.*`) vào đủ **6 file JSON** trong `locales/`.
7. **Bước 7**: Chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py`.

---

## 📡 3. Quy Chuẩn AJAX API JSON Response

Tất cả API endpoint trong `dashboard/api.py` hoặc AJAX POST trong `dashboard/blueprints/*` phải trả về đúng cấu trúc:
- **Thành công**: `jsonify({"ok": True, "message": "Thông báo thành công", "data": ...})`
- **Thất bại**: `jsonify({"ok": False, "message": "Mô tả lỗi"})`

---

## 🔁 4. Server Builder Studio — Bất biến của Diff Engine

`bot/server_builder_engine.py::compute_diff` **PHẢI idempotent**: sau khi "Tải lên từ Server thật" (target = cây live), `total_operations` bắt buộc bằng **0** — thanh dưới cùng không được hiện thay đổi nào. Khi sửa logic so sánh, tránh các bẫy đã từng gây 15 ops ảo:

1. **Tên có emoji/`・`**: không bao giờ so `sanitize_channel_name(target)` với tên gốc — chỉ tính rename khi raw target name khác tên hiện tại (người dùng thực sự sửa) VÀ tên sanitize khác tên hiện tại.
2. **Bindings**: op `bind_modules` chỉ sinh khi bindings target khác bindings hiện tại (`compute_diff` đọc `current_tree["bindings"]`; caller phải gắn `current_tree["bindings"] = _bindings(guild_id)` trước khi gọi).
3. **Type lạ (15 forum / 13 stage / 20 hub...)**: client coerce về 0 trước khi gửi; không để validation chặn oan cây import.
4. Regression tests chuẩn: `test_engine_import_live_tree_is_idempotent_for_decorated_names` + `test_engine_unchanged_current_bindings_emit_no_bind_op` trong `tests/test_server_builder.py`.

---

## 🎨 5. Không để mất class CSS khi đổi theme

Commit đồng bộ theme từng **xoá nhầm** các selector class dùng chung (`.send-section`, `.empty-state`, `.section-header`, `.section-title`, `.divider`, `.color-text-input`) khỏi `style.css` → khối "Gửi đến Discord" và "Embeds đã lưu" của trang Embeds bị mất style mà không test nào bắt được.

Trước khi commit thay đổi lớn về `style.css` (đổi theme/refactor CSS), chạy checker diff-aware:

```bash
python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py          # so với HEAD
python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py HEAD~1   # so với commit cụ thể
```

Script trích các selector class bị xoá trong diff của `style.css`, đối chiếu với nơi còn dùng trong `dashboard/templates/*.html` + `dashboard/static/js/*.js` (đã lọc Jinja/JS template) — lớp nào vừa bị xoá vừa còn dùng thì báo đỏ (exit 1). Class tự định nghĩa inline trong template và bootstrap-icons `bi-*` không bị tính.

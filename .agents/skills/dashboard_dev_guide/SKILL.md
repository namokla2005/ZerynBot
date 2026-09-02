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

1. **Bước 1**: Đăng ký Module trong `DEFAULT_MODULES` (`database.py`).
2. **Bước 2**: Viết hàm CSDL `get_<module>_settings()` & `update_<module>_settings()` trong `database.py`.
3. **Bước 3**: Thêm Route Flask trong `dashboard/app.py` với decorator `@login_required` và `@guild_admin_required`.
4. **Bước 4**: Tạo template HTML `dashboard/templates/server_<module>.html` kế thừa từ layout chuẩn hoặc dùng `base_server.html`.
5. **Bước 5**: Thêm link vào Sidebar trong các template server tương ứng.
6. **Bước 6**: Bổ sung từ điển đa ngôn ngữ (`<module>.*`) vào đủ **6 file JSON** trong `locales/`.
7. **Bước 7**: Chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py`.

---

## 📡 3. Quy Chuẩn AJAX API JSON Response

Tất cả API endpoint trong `dashboard/api.py` hoặc AJAX POST trong `dashboard/app.py` phải trả về đúng cấu trúc:
- **Thành công**: `jsonify({"ok": True, "message": "Thông báo thành công", "data": ...})`
- **Thất bại**: `jsonify({"ok": False, "message": "Mô tả lỗi"})`

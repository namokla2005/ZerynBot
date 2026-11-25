---
name: dashboard_dev_guide
description: >
  Standard development guide for ZerynBot V2 Flask Web Dashboard, Jinja2 templates,
  Midnight Obsidian Glassmorphism design system, and AJAX API endpoints.
---

# Skill: Web Dashboard Development Guide

## 🎯 1. Design System Tokens (Aurora Glass 2.0 — V11)

Tất cả các trang trên Web Dashboard (`dashboard/templates/`) phải tuân thủ chuẩn thiết kế đồng bộ. Theme hiện hành: **Aurora Glass 2.0** — nền aurora (hồng/tím/cyan) qua `body::before`, card kính mờ, accent gradient hồng→tím. Lớp override component nằm ở **cuối `style.css`** (mục "AURORA GLASS 2.0 — component layer"): đó là nơi sửa `.btn-primary`, `.tab-btn.active`, `.switch`, `.modal-box`… thay vì sửa từng section cũ phía trên.

### 1.1 CSS Variables & Bảng Màu
```css
:root {
  --bg-body:        #0a0918;                          /* Obsidian Aurora */
  --bg-sidebar:     rgba(17, 15, 34, 0.72);           /* Glass sidebar (blur 20px sẵn có) */
  --bg-card:        rgba(148, 130, 255, 0.065);       /* Glass card tint */
  --bg-card2:       rgba(148, 130, 255, 0.10);
  --bg-card-hover:  rgba(148, 130, 255, 0.13);
  --bg-input:       rgba(13, 11, 28, 0.60);
  --border:         rgba(255, 255, 255, 0.09);
  --border-subtle:  rgba(255, 255, 255, 0.06);
  --border-hover:   rgba(255, 122, 194, 0.35);
  --border-focus:   #ff7ac2;
  --surface:        rgba(19, 16, 38, 0.92);           /* Modal / login card */

  --accent:         #ff7ac2;                          /* Aurora Pink (brand) */
  --accent-hover:   #ffa1d4;
  --accent-light:   rgba(255, 122, 194, 0.16);
  --accent-glow:    rgba(255, 122, 194, 0.35);
  --accent-purple:  #8b5cf6;                          /* Aurora Violet (gradient đôi) */
  --accent-cyan:    #38bdf8;                          /* Aurora Cyan (hairline phụ) */
  --accent-blue:    #5865f2;

  --text-primary:   #ffffff;
  --text-secondary: #a7a3c4;
  --text-muted:     #6d6a8c;
  --text-disabled:  #504d6c;

  --font-sans:      'Inter', 'Plus Jakarta Sans', sans-serif;   /* body */
  --font-display:   'Space Grotesk', 'Inter', sans-serif;       /* .page-title/.card-title/.stat-value/logo */
}
```
Quy ước: button/tab/switch active = gradient `linear-gradient(100deg, #ff7ac2, #8b5cf6)` + chữ trắng; hairline trên card = hồng→tím (stat) / hồng→cyan (bento).

### 1.2 Asset Versioning
Mọi liên kết CSS/JS trong thẻ `<head>` **BẮT BUỘC** gắn phiên bản (hiện hành: `?v=17.0` — bump khi đổi `style.css`/JS):
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v=17.0">
```
Khi bump: đổi đồng bộ trong TẤT CẢ template có link (`grep -rl "style.css" templates/`) — không chỉ `base_server.html`.

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

---

## 🌐 6. i18n trong ngữ cảnh JavaScript (`<script>`) — luôn dùng `|tojson`

Chuỗi i18n chèn vào block `<script>` **BẮT BUỘC** qua `|tojson`, không bọc nháy tay:

```js
ok:  const I18N = { key: {{ t('x.key')|tojson }} };   // ✅ xuất chuỗi JS hợp lệ
bad: const I18N = { key: "{{ t('x.key') }}" };        // ❌ autoescape ra entity
```

Vì autoescape (đúng cho HTML) biến `< > & ' "` thành entity **ngay trong JS string**: chuỗi chứa `<:name:id>` sẽ hiển thị nguyên chữ `&lt;:name:id&gt;` khi gán bằng `textContent`, dấu nháy trong bản dịch có thể phá cú pháp JS. `|tojson` escape về dạng `\u003c...` — hiển thị đúng trên cả 6 locale. (Trong HTML text/attribute bình thường thì `{{ t(...) }}` giữ nguyên là đúng.)

---

## 🚦 7. Kinh nghiệm chạy pre-commit gate (`dual_model_mcp.py --pre-commit-check`)

- **Diff staged quá lớn → 413**: tier Groq trả `413 Request too large` khi diff dài (nhất là dòng siêu dài như dataset emoji) → tách commit theo chủ đề, mỗi commit ≲ ~300 dòng diff.
- **Reviewer không hội tụ với code hạ tầng mới**: các roll có thể đưa lý do trôi dạt/mâu thuẫn nhau (roll sau phản đối cả pattern có sẵn trong repo, thậm chí đòi ngược roll trước). Quy trình đúng: sửa hết điểm actionable (lock/subprocess/cache chuẩn, validate input, escape, debounce...), chạy lại vài roll; nếu vẫn đỏ vì lý do không đúng thực tế → chốt bằng bằng chứng độc lập (full pytest + render/browser thật) và ghi chú minh bạch khi báo cáo.
- Chuỗi i18n đổi → nhớ chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` (đủ 6 locale) trước khi commit.

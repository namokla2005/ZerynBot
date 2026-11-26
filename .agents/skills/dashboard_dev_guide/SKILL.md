---
name: dashboard_dev_guide
description: >
  Standard development guide for ZerynBot V2 Flask Web Dashboard, Jinja2 templates,
  Midnight Obsidian Glassmorphism design system, and AJAX API endpoints.
---

# Skill: Web Dashboard Development Guide

## 🎯 1. Design System Tokens (Iridescent Dual-Theme — V12)

Tất cả các trang trên Web Dashboard (`dashboard/templates/`) — ngoại trừ hai trang pháp lý đóng băng (`tos.html`, `privacy.html`) — phải tuân thủ chuẩn thiết kế **Iridescent Dual-Theme (V12)** gồm 2 chế độ **Iridescent Glass (Light mặc định)** và **Iridescent Noir (Dark)** chuyển đổi mượt qua `dashboard/static/js/theme.js` (`'light' | 'dark' | 'auto'`, mặc định `'auto'` theo `prefers-color-scheme`). Lớp override component nằm ở **cuối `style.css`** (mục `IRIDESCENT — component layer (V12)`): đó là nơi sửa `.btn-primary`, `.nav-item.active`, `.tab-btn.active`, `.switch`, `.modal-box`, `.theme-toggle-btn`… thay vì sửa từng section cũ phía trên.

### 1.1 CSS Variables & Bảng Màu Hai Chế Độ
```css
:root {
  color-scheme: light;
  --bg-body:        #f5f4fb;                          /* Iridescent Glass (Light default) */
  --glass:          rgba(255, 255, 255, 0.62);
  --glass-2:        rgba(255, 255, 255, 0.45);
  --gborder:        rgba(255, 255, 255, 0.75);
  --border:         rgba(35, 33, 54, 0.10);
  --border-subtle:  rgba(35, 33, 54, 0.06);
  --border-hover:   rgba(124, 108, 240, 0.38);
  --border-focus:   #7c6cf0;
  --surface:        rgba(255, 255, 255, 0.88);
  --bg-sidebar:     var(--glass);
  --bg-card:        var(--glass);
  --bg-card2:       var(--glass-2);
  --bg-input:       rgba(255, 255, 255, 0.72);

  --ink:            #232136;
  --mut:            #6b6883;
  --dim:            #9793ad;
  --text-primary:   var(--ink);
  --text-secondary: var(--mut);
  --text-muted:     #66627d;
  --text-disabled:  var(--dim);

  --accent:         #7c6cf0;                          /* Iridescent Violet */
  --accent-hover:   #8f7ff5;
  --accent-ink:     #5e4ce6;                          /* Accessible >=4.5:1 */
  --accent-2:       #ff8a9b;                          /* Coral Rose */
  --accent-3:       #ffc07a;                          /* Warm Amber */
  --mint:           #7fe0c3;
  --grad-primary:   linear-gradient(100deg, #7c6cf0, #ff8a9b);
  --grad-hairline:  linear-gradient(90deg, transparent, rgba(124, 108, 240, 0.5), rgba(255, 138, 155, 0.5), transparent);

  --success:        #168045;
  --danger-ink:     #c92d35;
  --warning:        #9a6012;

  --font-sans:      'Inter', 'Plus Jakarta Sans', -apple-system, sans-serif;
  --font-display:   'Space Grotesk', 'Inter', -apple-system, sans-serif;
}

[data-theme="dark"] {
  color-scheme: dark;
  --bg-body:        #0d0b16;                          /* Iridescent Noir */
  --glass:          rgba(255, 255, 255, 0.05);
  --glass-2:        rgba(255, 255, 255, 0.035);
  --gborder:        rgba(255, 255, 255, 0.10);
  --border:         rgba(255, 255, 255, 0.09);
  --border-subtle:  rgba(255, 255, 255, 0.06);
  --surface:        rgba(19, 16, 38, 0.92);
  --bg-input:       rgba(255, 255, 255, 0.05);
  --ink:            #f4f2fb;
  --mut:            #b9b5d0;
  --dim:            #7f7b99;
  --text-muted:     #8f8bab;
  --accent:         #8d7bff;
  --accent-ink:     #a293ff;
  --success:        #4be08e;
  --danger-ink:     #ff8f8f;
  --warning:        #ffcf8e;
  --grad-primary:   linear-gradient(100deg, #8d7bff, #ff8a9b);
}
```
Quy ước:
- Nền 3 quả cầu aura (`.iridescent-blob` + `body::before`/`body::after`) dùng `radial-gradient` thuần (`z-index: -1`), còn `backdrop-filter` chỉ bật cho `.sidebar`, `.topbar`, `.modal-overlay`, `.theme-toggle-btn` và tự tắt trên `@media (hover: none), (max-width: 768px)` và `prefers-reduced-motion: reduce` để giữ mượt GPU Mali trên Termux.
- **FOUC Guard & `theme.js`**: mọi trang non-legal chèn inline script `localStorage.getItem('zeryn-theme')` trong `<head>` **trước** `style.css`, gắn `#theme-i18n` (`| tojson` gồm `theme.to_light`, `theme.to_dark`, `theme.auto`, `theme.tooltip`), nút `[data-theme-toggle]`, và nạp `js/theme.js`. Khi chuyển giao diện, `theme.js` phát `CustomEvent('zeryn:themechange', { detail: { mode, resolved }, bubbles: false, composed: false })` để biểu đồ Chart.js (`server.html`) hoặc observer cập nhật màu từ `getComputedStyle(document.documentElement)`.
- **Trang pháp lý đóng băng (`tos.html`, `privacy.html`)**: dùng riêng `dashboard/static/css/theme_legal.css?v=1.0` (bản V17 đóng băng), **tuyệt đối không** nhúng `style.css`, `theme.js`, FOUC script, hay `[data-theme="dark"]`.

### 1.2 Asset Versioning
Mọi liên kết CSS/JS trong thẻ `<head>` / cuối `<body>` **BẮT BUỘC** gắn phiên bản (hiện hành: `style.css?v=20.0`, `theme.js?v=18.0`; riêng trang pháp lý giữ `theme_legal.css?v=1.0`, trang Server Builder dùng thêm `server_builder.js?v=16.0`):
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v=20.0">
<script src="{{ url_for('static', filename='js/theme.js') }}?v=18.0"></script>
```
Khi bump: đổi đồng bộ trong TẤT CẢ template không phải legal (`base_server.html`, `home.html`, `login.html`, `admin.html`, `admin_support.html`, `docs.html`, `support.html`, và `landing.html` cho `theme.js`).

---

## 🧱 2. Khung Command Rail (V20) — cấu trúc bắt buộc của trang dashboard

Khung nằm ở `dashboard/templates/base_server.html` (mọi trang `server_*`/module kế thừa nó). Lớp CSS cấu trúc ở **cuối `style.css`** (mục `COMMAND RAIL — STRUCTURAL LAYER (V20)`):

- **Rail biểu tượng** `.cr-rail` (76px, trái): 24 mục khai báo trong biến Jinja `rail_items` (bi icon + t() + route + page key + chấm `nav-dot-<module>`). Thêm/bớt mục = sửa list này, KHÔNG viết tay HTML. Giữ nguyên class `nav-dot-<module>` — `main.js` cập nhật dot qua đó.
- **Thanh lệnh** `.cr-cmdbar` (sticky): breadcrumb = guild + `{% block page_title %}`. Mỗi trang con BẮT BUỘC khai báo `{% block page_title %}{{ t('key') }}{% endblock %}` ngay sau `{% block title %}`; KHÔNG lặp lại `<h1 class="page-title">` trong nội dung (giữ dòng subtitle nếu có).
- **Lưới nội dung 2 cột**: bọc `<div class="cr-grid"><section>…</section><aside class="cr-side">…</aside></div>`; cột phải `.cr-side` (330px, sticky) chứa khối ngữ cảnh CÓ SẴN (tóm tắt/trạng thái/xem trước/thao tác nhanh). Trang không có khối phù hợp → cột đơn `style="grid-template-columns:minmax(0,1fr)"`. Riêng trang Server Builder dùng workspace riêng (`sb-panel`), KHÔNG dùng cr-grid.
- Nút Sáng/Tối + burger mobile nằm trong cmdbar; lang switcher + avatar/logout ở đáy rail (giữ nguyên class `lang-switcher`/`lang-dropdown`).
- Trang KHÔNG kế thừa base_server (login/home/docs/support/admin) giữ lối trình bày riêng, KHÔNG thêm rail.
- Sửa CSS khung → bump `style.css?v=` đồng bộ mọi template: `grep -rl "style.css" dashboard/templates/`.
- Bố cục chuẩn tham chiếu: mockup đã duyệt trong `zeryn-redesign\cr-pages\pNN-*.html` + `r4-struct-2-command-rail.html`.

## 🛠️ 3. Checklist 7 Bước Khi Tạo Trang Quản Lý Module Mới

Khi tạo thêm trang cài đặt module mới trong Dashboard:

1. **Bước 1**: Đăng ký Module trong `DEFAULT_MODULES` (`database/guilds.py`).
2. **Bước 2**: Viết hàm CSDL `get_<module>_settings()` & `update_<module>_settings()` trong `database/<domain>.py`.
3. **Bước 3**: Thêm Route Flask trong blueprint phù hợp (`dashboard/blueprints/{guild,music,admin,support}.py`) với decorator `@login_required` và `@guild_access_required`.
4. **Bước 4**: Tạo template HTML `dashboard/templates/server_<module>.html` kế thừa từ layout chuẩn hoặc dùng `base_server.html`.
5. **Bước 5**: Thêm link vào Sidebar trong các template server tương ứng.
6. **Bước 6**: Bổ sung từ điển đa ngôn ngữ (`<module>.*`) vào đủ **6 file JSON** trong `locales/` (hiện hành **2177 keys/file**).
7. **Bước 7**: Chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py`.

---

## 📡 4. Quy Chuẩn AJAX API JSON Response

Tất cả API endpoint trong `dashboard/api.py` hoặc AJAX POST trong `dashboard/blueprints/*` phải trả về đúng cấu trúc:
- **Thành công**: `jsonify({"ok": True, "message": "Thông báo thành công", "data": ...})`
- **Thất bại**: `jsonify({"ok": False, "message": "Mô tả lỗi"})`

---

## 🔁 5. Server Builder Studio — Bất biến của Diff Engine & Role Studio

`bot/server_builder_engine.py::compute_diff` **PHẢI idempotent**: sau khi "Tải lên từ Server thật" (target = cây live), `total_operations` bắt buộc bằng **0** — thanh dưới cùng không được hiện thay đổi nào. Khi sửa logic so sánh, tránh các bẫy đã từng gây ops ảo:

1. **Tên có emoji/`・`**: không bao giờ so `sanitize_channel_name(target)` với tên gốc — chỉ tính rename khi raw target name khác tên hiện tại (người dùng thực sự sửa) VÀ tên sanitize khác tên hiện tại.
2. **Bindings (Kênh & Role)**: op `bind_modules` chỉ sinh khi bindings target khác bindings hiện tại (`compute_diff` đọc `current_tree["bindings"]`; caller phải gắn `current_tree["bindings"] = _bindings(guild_id)` gồm cả 4 role bindings `autoroles_user`, `verify_verified`, `verify_pending`, `automod_immune` trước khi gọi).
3. **Type lạ (15 forum / 13 stage / 20 hub...)**: client coerce về 0 trước khi gửi; không để validation chặn oan cây import.
4. **Role Studio & 52-bit Permissions**: chuẩn hóa màu mặc định `#99aab5 <-> 0` (cùng `#000000`/`""`/`0` về `#99aab5` ở JS/Blueprint/Engine, và Cog `_color()` map `#99aab5` về `discord.Color.default()`), dùng chung bảng `PERMISSION_BITS` (52-bit, bảo toàn bit lạ dạng `bit_<b>`), giữ `@everyone` chỉ sửa `permissions`, khóa chỉnh/xóa `managed` & role `>= min(bot_top_role_pos, user_top_role_pos)`, và khóa chỉnh role khi `live_source == "cache"` (`_cache_readonly`) để tránh xóa nhầm quyền khi offline fallback.
5. Regression tests chuẩn: `test_engine_import_live_tree_is_idempotent_for_decorated_names`, `test_engine_unchanged_current_bindings_emit_no_bind_op`, và nhóm test Role Studio / Escalation Gates trong `tests/test_server_builder.py`.
6. **Reorder kênh đổi danh mục (Discord 40009)**: `bulk_channel_update` chỉ cho phép **1 kênh đổi `parent_id` mỗi request** — job apply có ≥2 kênh chuyển danh mục sẽ chết với `40009 Only one channel can have a parent_id modified at a time`. Nhánh `bulk_reorder` trong `_run_operation` đã xử lý: so `fetch_channels`/cache để tìm kênh đổi parent THẬT SỰ → chuyển lần lượt qua `http.edit_channel(channel_id, parent_id=..., position=...)` → khoá thứ tự bằng ĐÚNG 1 bulk call **không kèm `parent_id`**. Khi sửa nhánh này phải giữ nguyên quy tắc đó — test: `test_cog_bulk_reorder_splits_multi_parent_moves` + `test_cog_bulk_reorder_and_deletion_guard`.

---

## 🎨 6. Không để mất class CSS khi đổi theme

Commit đồng bộ theme từng **xoá nhầm** các selector class dùng chung (`.send-section`, `.empty-state`, `.section-header`, `.section-title`, `.divider`, `.color-text-input`) khỏi `style.css` → khối "Gửi đến Discord" và "Embeds đã lưu" của trang Embeds bị mất style mà không test nào bắt được.

Trước khi commit thay đổi lớn về `style.css` (đổi theme/refactor CSS), chạy checker diff-aware:

```bash
python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py          # so với HEAD
python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py HEAD~1   # so với commit cụ thể
```

Script trích các selector class bị xoá trong diff của `style.css`, đối chiếu với nơi còn dùng trong `dashboard/templates/*.html` + `dashboard/static/js/*.js` (đã lọc Jinja/JS template) — lớp nào vừa bị xoá vừa còn dùng thì báo đỏ (exit 1). Class tự định nghĩa inline trong template và bootstrap-icons `bi-*` không bị tính.

---

## 🌐 7. i18n trong ngữ cảnh JavaScript (`<script>`) — luôn dùng `|tojson`

Chuỗi i18n chèn vào block `<script>` **BẮT BUỘC** qua `|tojson`, không bọc nháy tay:

```js
ok:  const I18N = { key: {{ t('x.key')|tojson }} };   // ✅ xuất chuỗi JS hợp lệ
bad: const I18N = { key: "{{ t('x.key') }}" };        // ❌ autoescape ra entity
```

Vì autoescape (đúng cho HTML) biến `< > & ' "` thành entity **ngay trong JS string**: chuỗi chứa `<:name:id>` sẽ hiển thị nguyên chữ `&lt;:name:id&gt;` khi gán bằng `textContent`, dấu nháy trong bản dịch có thể phá cú pháp JS. `|tojson` escape về dạng `\u003c...` — hiển thị đúng trên cả 6 locale. (Trong HTML text/attribute bình thường thì `{{ t(...) }}` giữ nguyên là đúng.)

---

## 🚦 8. Kinh nghiệm chạy pre-commit gate (`dual_model_mcp.py --pre-commit-check`)

- **Diff staged quá lớn → 413**: tier Groq trả `413 Request too large` khi diff dài (nhất là dòng siêu dài như dataset emoji) → tách commit theo chủ đề, mỗi commit ≲ ~300 dòng diff.
- **Reviewer không hội tụ với code hạ tầng mới**: các roll có thể đưa lý do trôi dạt/mâu thuẫn nhau (roll sau phản đối cả pattern có sẵn trong repo, thậm chí đòi ngược roll trước). Quy trình đúng: sửa hết điểm actionable (lock/subprocess/cache chuẩn, validate input, escape, debounce...), chạy lại vài roll; nếu vẫn đỏ vì lý do không đúng thực tế → chốt bằng bằng chứng độc lập (full pytest + render/browser thật) và ghi chú minh bạch khi báo cáo.
- Chuỗi i18n đổi → nhớ chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` (đủ 6 locale) trước khi commit.

# 📋 KẾ HOẠCH TRIỂN KHAI CHI TIẾT — ZerynBot V2

> **Bản:** v1.0  ·  **Ngày:** 2026-09-02  ·  **Branch làm việc:** `arena/01a062d4-zerynbot`
> **Nguyên tắc xuyên suốt:** tuân thủ tuyệt đối `AGENTS.md` + SOP 5 bước thêm lệnh + 7 bước Dashboard trong `.agents/`, và **đồng bộ tài liệu trong cùng một commit** (Conventional Commits).

---

## 0. Tổng quan & Phạm vi

Kế hoạch này gồm **4 phần** (A, B, C, D) triển khai chi tiết, cộng **E/F** là lộ trình tiếp theo. Mỗi phần được chia nhỏ thành các nhóm công việc độc lập, đều có **phạm vi rõ, file đụng tới, cách kiểm chứng** để không gây hồi quy — và tất cả đều tuân theo **SOP 5 bước** (cog → db → i18n → dashboard → docs) / **7 bước Dashboard**.

| Phần | Nội dung | Ưu tiên |
|---|---|---|
| **Phần A — Sửa nền & dọn nợ kỹ thuật** | sửa lệch `busy_timeout`, auto-prune (đúng bảng), dọn lỗi ruff nghiêm trọng, cache LRU thật | Làm **trước** |
| **Phần B — Kinh tế 2.0** | `/work`, `/fish`, `/inventory`, `/sell` + bảng `items`/`user_inventory`/`user_jobs`, i18n, Dashboard, docs | **Chính** (Phase 1 của bạn) |
| **Phần C — Cổng xác thực & Anti-Raid** | Verify Gate (kênh `#xac-thuc`, nút/captcha, gán role) + Anti-Nuke/Anti-Raid + Auto-Prune task | **Nhóm 2** kế hoạch của bạn |
| **Phần D — AI 2.0** | `/ask web:true` (DuckDuckGo search) + `/summarize url:<link>` (tóm tắt trang, chống SSRF) | **Nhóm 3** kế hoạch của bạn |

> **E/F** (Live Log Viewer, Announcement Scheduler) là nhóm 4 của bạn — sẽ mở rộng sau khi B/C/D xong.

---

## 1. TRẠNG THÁI THỰC TẾ (ground truth, đã kiểm chứng)

- 42 file `.py`; i18n **6 ngôn ngữ × 1510 key** (parity 100%).
- `_COMMANDS_DATA` trong `dashboard/app.py:698` = **16 danh mục / 87 lệnh**; mục **"Kinh tế & Shop"** (icon 🪙) hiện có: `daily, balance, deposit, withdraw, pay, rich, coinflip, slots, blackjack, shop, buy` (11 lệnh).
- `bot/cogs/economy.py` dùng `@commands.hybrid_command`, có `cog_check` chặn khi module `economy` tắt, dùng `tr(settings, key, **kwargs)`.
- CSDL: 36 bảng; `economy_users(guild,user,wallet,bank,daily_streak,last_daily_at)`, `economy_shop(id,guild,role,name,price,stock)`.
- **Lệch thật:** `database.py:23` = `busy_timeout=5000` trong khi `AGENTS.md:50`, `llms.txt:19` và `check_db_schema.py` đều kỳ vọng `15000`.
- Bảng phình to thật: `guild_stats`, `user_levels`, `fun_interactions`, `automod_warnings`, `economy_users`. **KHÔNG có** `audit_logs`/`server_stats_hourly` (log sự kiện ghi qua tin nhắn Discord, bảng thống kê là `guild_stats`).

## 1.5. BẢNG ĐỐI CHIẾU TRẠNG THÁI TRÊN `origin/main` (commit `e044afd`) — đã kiểm chứng

> Kiểm tra thực tế trên nhánh `main` (đã `git fetch`): đây là những gì bạn đã TRIỂN KHAI và những gì CÒN THIẾU.

| Hạng mục | Trạng thái trên `main` | Chi tiết |
|---|---|---|
| **56 custom emoji** | ✅ Đã có | `emojis.py` (root) và `bot/emojis.py` (giống hệt nhau) — `EMOJIS` có đúng **56** emoji, gồm `zb_coin`, `zb_work`, `zb_fish`, `zb_hunt`, `zb_inventory`, `zb_sell`, `zb_web_search`, `zb_verified`, `zb_cat_*`, … Có hàm `e()`, `partial()`, `clean_title()`, `embed_title()` |
| **Phần B — Kinh tế 2.0** | ⚠️ **Đã làm gần xong** | `/work`, `/fish`, `/hunt`, `/inventory`, `/sell` đã có trong `economy.py` (92 lệnh tổng → 16 danh mục). Bảng `user_inventory` + `economy_cooldowns` (với `sell_price`, `rarity`) + index `idx_inventory_lookup` đã có. **Emoji đã gắn** `zb_inventory`, `zb_work`, `zb_fish`, `zb_sell` vào title embed. **Chưa thấy** bảng `items` (catalog) tách riêng — dữ liệu vật phẩm đang lưu inline trong `user_inventory` |
| **Phần D — AI 2.0** | ⚠️ **Đã làm gần xong** | `/ask` có param `web: bool` (dùng `_fetch_duckduckgo_search`), `/summarize` có param `url` (dùng `_fetch_url_article_content`), `zb_web_search` gắn vào footer. **Cần kiểm tra** phần SSRF (`is_safe_http_url`) có được áp dụng cho `url` chưa |
| **Phần A1 — busy_timeout** | ✅ Đã sửa | `database.py:23` = `PRAGMA busy_timeout=15000;` (khớp tài liệu) |
| **Phần A2 — Auto-prune** | ❌ **Chưa có** | Không tìm thấy task dọn dữ liệu cũ (`grep prune/maintenance` = không có) |
| **Phần A4 — Cache LRU** | ❌ **Chưa có** | `cache.py` vẫn dùng `dict` + evict 20% đầu khi đầy (chưa phải LRU thật, `max_size=3000`) |
| **Phần A3 — ruff** | ⚠️ Chưa hoàn toàn | Chưa kiểm chứng đầy đủ; nhiều `blind-except`/`try-except-pass` còn tồn tại |
| **Phần C — Verify Gate / Captcha / Anti-Raid** | ❌ **CHƯA CÓ (quan trọng)** | **Không có** cog `verify.py`, **không có** `verify_settings`, **không có** `on_member_join` gán role sau xác thực, **không có** captcha/`setup_verify`, `DEFAULT_MODULES` chưa có `"verify"`, **không có** template `server_verify.html`. Đây chính là thứ bạn hỏi "chưa có authentication/xác minh trước khi vào server" |

> **KẾT LUẬN (trả lời câu hỏi của bạn):** Bạn đã thêm 56 custom emoji đúng và triển khai **Kinh tế 2.0 + AI 2.0** khá tốt. Nhưng **`/setup_verify` + cổng xác minh (captcha/button) trước khi vào server VẪN CHƯA được code** — đây là phần quan trọng cần làm (Phần C). Ngoài ra còn thiếu Auto-prune (A2) và cache LRU (A4).

### 🔎 Chi tiết kiểm chứng đã chạy (để bạn yên tâm)
- **`_COMMANDS_DATA` trên `main`** = **16 danh mục / 92 lệnh** (Kinh tế & Shop = 16, đã gồm `work`, `fish`, `hunt`, `inventory`, `sell`).
- **`emojis.py` và `bot/emojis.py`** = **giống hệt nhau** (diff = 0), 56 emoji, có `e()`, `partial()`.
- **Đếm số emoji** bằng regex `^\s+"<key>": <id 15+ chữ số>` = **56**.
- **`economy.py`** trên `main` có: `/daily`, `/balance`, `/deposit`, `/withdraw`, `/pay`, `/rich`, `/coinflip`, `/slots`, `/blackjack`, `/shop`, `/buy`, **`/work`**, **`/fish`**, **`/hunt`**, **`/inventory`**, **`/sell`** (16 lệnh).
- **`database.py`** trên `main` đã có: `user_inventory` (kèm `item_id/item_name/item_type/rarity/quantity/sell_price`), `economy_cooldowns`, index `idx_inventory_lookup`; đã có các hàm `async_get_inventory`, `async_add_inventory_item`, `async_sell_inventory_item`, `async_sell_all_inventory`, `async_get_economy_cooldown`, `async_set_economy_cooldown`.
- **`ai.py`** trên `main` đã có `_fetch_duckduckgo_search`, `_fetch_url_article_content`, `/ask web=`, `/summarize url=`, và dùng `e('zb_web_search')`.
- **`busy_timeout`** trên `main` = `15000` (đã khớp docs).
- **`DEFAULT_MODULES`** trên `main` chỉ có 19 module gốc — **chưa có `verify`**.

---

# PHẦN A — Sửa nền tảng & dọn nợ kỹ thuật

> **Mục tiêu:** ổn định nền trước khi thêm tính năng mới, vì ogni tính năng `/work`/`/fish` sẽ tăng ghi DB & tải cache. Làm xong phần A, hệ thống chạy sạch hơn, các con số trong `validate_all.py` đạt PASS.

## A1. Sửa `busy_timeout` lệch nhau (bắt buộc, dễ)

- **File:** `database.py:23`
- **Sửa:** `conn.execute("PRAGMA busy_timeout=5000;")` → `conn.execute("PRAGMA busy_timeout=15000;")`
- **Lý do:** khớp `AGENTS.md`, `llms.txt`, và `check_db_schema.py` (nó sẽ báo WARN nếu không phải 15000). Tránh deadlock trên Termux chậm.
- **Kiểm chứng:** `python .agents/skills/zerynbot_architecture_context/assets/check_db_schema.py` → không còn WARN về busy_timeout; `pytest -q` xanh.

## A2. Auto-prune dữ liệu cũ (task ngầm 04:00) — ở đúng bảng

- **Cơ chế:** dùng pattern `auto_backup_task` của `bot/cogs/admin.py` (task ngầm chạy định kỳ), thêm **một** task dọn dẹp hoặc gộp vào task hiện có.
- **Bảng thật cần dọn (quy tắc: giữ N ngày, mặc định 60):**
  - `guild_stats` → xoá `date_hour < datetime(now, '-60 days')`.
  - `automod_warnings` → xoá `created_at <= datetime(now, '-2 day')` (cảnh cáo automod chỉ có ý nghĩa trong cửa sổ 24h).
  - `fun_interactions` → xoá bản ghi > 60 ngày (không bắt buộc, tuỳ dung lượng — đây là bảng tích luỹ).
  - `user_levels`, `economy_users` → **không dọn theo thời gian** (vì là dữ liệu member); chỉ dọn khi member rời server (gắn vào `events.on_guild_remove` / `on_member_remove` nếu muốn).
- **File đụng tới:** `bot/cogs/admin.py` (nơi có task) + `database.py` (thêm hàm `async_*` purge, ví dụ `async_prune_old_stats(guild_id, days)`), hoặc tạo `bot/cogs/maintenance.py` mới.
- **Lưu ý:** KHÔNG tạo bảng `audit_logs`/`server_stats_hourly` — chúng không tồn tại và không cần thiết.
- **Kiểm chứng:** chạy hàm với dữ liệu test; kiểm tra kích thước `data/bot.db` giảm; `pytest` xanh.

## A3. Dọn lỗi ruff nghiêm trọng (202 sửa được tự động)

- **File:** toàn repo (ưu tiên các file `database.py`, `dashboard/app.py`, `bot/cogs/*.py`).
- **Làm thủ công (không tự sửa):**
  - `BLE001` (blind-except) / `S110` (try-except-pass) / `E722` (bare-except) / `S112` (try-except-continue): tối thiểu **log `logger.exception`** thay vì `pass`, để không che lỗi thật. Đây là nhóm quan trọng nhất.
  - `DTZ005` / `DTZ001` (`datetime.now()` không tzinfo): đổi thành `datetime.now(timezone.utc)`.
  - `ASYNC230` (`open()` trong async): dùng `asyncio.to_thread` hoặc `aiofiles`.
  - `PLW1510` (`subprocess.run` không check): thêm `check=True` hoặc xử lý rc.
- **Làm tự động (`ruff --fix`, 202 fix):** `I001` (unsorted-imports), `F401` (unused-import), `F841` (unused-variable), `UP006/UP045/UP035` (annotations), `SIM117`, `SIM114`…
- **Kiểm chứng:** `ruff check .` giảm còn 0 lỗi nghiêm trọng; `pytest -q` xanh; bot vẫn load được 22 cogs (`test_cogs_smoke`).

## A4. Cache LRU thật (hiện chỉ là "evict 20%" khi đầy)

- **File:** `cache.py`
- **Sửa:** `_store` dùng `collections.OrderedDict`; khi `len > max_size` → `popitem(last=False)` (evict entry cũ nhất) thay vì xoá 20% đầu. Giữ nguyên TTL + periodic cleanup.
- **Tăng `max_size`** (mặc định 3000) lên giá trị hợp lý cho bot đa server (VD 10.000) — vì mỗi guild/user đều tạo cache `settings:{guild}`, `level:{guild}:{user}`, `global_setting:*`.
- **Kiểm chứng:** `tests/test_cache.py` xanh; viết thêm test cho LRU eviction.

> ✅ **Kết thúc Phần A:** chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_all.py` → kỳ vọng `100%` (i18n parity, py_compile, commands, doc-sync). Chạy `pytest -q` → 55 test (hoặc hơn nếu thêm test mới) xanh. `ruff check .` sạch nhóm nghiêm trọng.

---

# PHẦN B — Hệ thống Kinh tế 2.0 (`/work`, `/fish`, `/inventory`, `/sell`)

> **Mục tiêu:** tăng tương tác, tái sử dụng đúng hệ economy hiện có, **bám sát quy tắc kinh tế**: mini-game cược bằng Ví; vật phẩm bán lấy Coin vào Ví; mua Role bằng Bank. Tuân thủ **SOP 5 bước** + **7 bước Dashboard**.

## B0. Quyết định thiết kế (trước khi code)

- **Thêm catalog vật phẩm** (bảng `items`) thay vì nhồi tên/giá/độ hiếm vào `user_inventory` → dễ cân bằng & đổi giá. `user_inventory` chỉ lưu `item_id + quantity`.
- **Phân loại nghề:** lưu nghề của user (`user_jobs`) để `/work` ổn định, trả lương theo nghề + trắc nghiệm nhỏ.
- **Cooldown per-command** (không dùng chung global 3s): `/work` 1h, `/fish` 15ph — dùng `commands.cooldown`/`BucketType.user` hoặc bảng riêng.
- **Vật phẩm ≠ Role Shop:** `/sell` trả Coin (Ví); `/inventory` chỉ hiển thị + bán. Không ảnh hưởng `/shop`/`/buy`.

## B1. Bước 2 (SOP) — CSDL `database.py`

### B1.1 Migration an toàn (thêm bảng, theo mẫu `CREATE TABLE IF NOT EXISTS` trong `init_db()`)

```sql
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT NOT NULL,
    item_key     TEXT NOT NULL,          -- 'fish_carp', 'fish_salmon', 'mineral_iron', ...
    name         TEXT NOT NULL,
    item_type    TEXT NOT NULL,          -- 'fish' | 'hunt' | 'mineral' | 'trash'
    rarity        TEXT DEFAULT 'common', -- 'common' | 'rare' | 'epic' | 'legendary'
    sell_price   INTEGER DEFAULT 10,
    emoji        TEXT DEFAULT '🎁',
    UNIQUE(guild_id, item_key)
);

CREATE TABLE IF NOT EXISTS user_inventory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    item_key    TEXT NOT NULL,
    quantity    INTEGER DEFAULT 1,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, user_id, item_key)
);

CREATE TABLE IF NOT EXISTS user_jobs (
    guild_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    job_key     TEXT NOT NULL,
    last_work_at REAL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
```

- **Chú ý:** dùng `UNIQUE(...)` + `ON CONFLICT ... DO UPDATE SET quantity = quantity + ?` khi cộng dồn.
- Đồng thời sửa `busy_timeout` (A1) đã nêu.

### B1.2 Hàm sync (Dashboard) + async (Bot)

| Nhóm | Sync (sqlite3) | Async (aiosqlite) |
|---|---|---|
| Danh sách item | `get_items(guild_id)` | `async_get_items(guild_id)` |
| Nhận vật phẩm | `add_inventory_item(guild_id,user,key,qty)` | `async_add_inventory_item(...)` |
| Túi đồ | `get_inventory(guild_id,user)` | `async_get_inventory(...)` |
| Bán vật phẩm | `sell_item(guild_id,user,key,qty)` | `async_sell_item(...)` |
| Nghề | `get_job(guild_id,user)` | `async_get_job(...)` |
| Làm việc | `set_job_last_work(guild_id,user,ts)` | `async_set_job_last_work(...)` |
| Tiền thưởng | — (dùng `async_modify_wallet`) | `async_modify_wallet` |

- Bán vật phẩm → **cộng Coin vào Ví** qua hàm `async_modify_wallet` (đã có), đúng quy tắc.

## B2. Bước 1 (SOP) — Cog `bot/cogs/economy.py`

Thêm 4 lệnh `hybrid_command` (đặt cùng nhóm với các lệnh kinh tế hiện có):

| Lệnh | Cú pháp | Cooldown | Cơ chế |
|---|---|---|---|
| `/work` | `/work` | 1h | Chọn/gán nghề (hoặc đổi nghề); trả lương `job_pay`; tuỳ chọn trắc nghiệm mini + bonus |
| `/fish` | `/fish` | 15 ph | Random item theo `rarity` (common/rare/epic/legendary) với tỉ lệ & giá bán giảm dần; đưa vào `user_inventory` |
| `/inventory` | `/inventory [@user]` | — | Embed phân trang/nút bấm, hiện từng nhóm `item_type` & `rarity` |
| `/sell` | `/sell <item_key> [qty]` hoặc `/sell all` | — | Bán vật phẩm → cộng Coin Ví; trừ `quantity` |

- **Bọc Module Guard:** đầu mỗi lệnh `if not await async_is_module_enabled(guild_id, "economy"): return`.
- **Dùng `tr(settings, key, **kwargs)`** cho toàn bộ thông báo (KHÔNG hardcode).
- **Bắt lỗi + `logger.exception`** (theo code_style).
- **Cooldown:** dùng `@commands.cooldown(1, 3600, commands.BucketType.user)` cho `/work`; `(1, 900, BucketType.user)` cho `/fish`. Cân nhắc lưu `last_work_at`/`last_fish_at` trong DB để đồng bộ khi bot restart.

> 💡 Để giảm lặp code, **tách logic** vào helper trong `economy.py` (hoặc thêm file `bot/cogs/_minigames.py`) — nhưng giữ trong `economy.py` là đúng SOP (một module tương đối gọn).

## B3. Bước 3 (SOP) — i18n `locales/*.json`

Thêm bộ key mới vào **đủ 6 file** (parity 100%, tổng sẽ là 1510 + N). Ký hiệu đề xuất (namespace theo module `economy` để không đụng key cũ):

```
economy.work.*        → economy.work.title, .done, .cooldown, .no_job, .assign, .salary, .quiz_*
economy.fish.*        → economy.fish.caught, .none, .legendary, .cooldown, .added
economy.inventory.*   → economy.inventory.title, .empty, .page, .category
economy.sell.*        → economy.sell.done, .not_found, .empty, .zero
economy.items.*       → item names + rarity labels: item.fish_carp, item.fish_salmon, rarity.common/rare/epic/legendary
```

- **Bắt buộc chạy:** `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` → `100% 6 ngôn ngữ đồng bộ`.
- **Cập nhật con số key** trong `ARCHITECTURE.md`, `.agents/AGENTS.md`, `llms.txt`, `README.md`.

## B4. Bước 4 (SOP + 7 bước) — Dashboard

### B4.1 `_COMMANDS_DATA` (`dashboard/app.py`)
- Thêm 4 lệnh mới vào danh mục **"Kinh tế & Shop"** (đúng cấu trúc `name/emoji/desc/usage/example/args/preview`), 87 → **91 lệnh**.
- Preview embed theo design system (VD `/work`: color `#57F287`, title `💼 Làm Việc — Nghề: Lập trình viên`, desc `+120 🪙 …`).

### B4.2 Trang module (`server_economy.html`)
- Thêm **Bảng vật phẩm server** (hiện `items` + `sell_price` + hiếm) và **Bảng nghề** (job + pay). Có thể dùng AJAX endpoint nếu cần cập nhật catalog.
- Tuân thủ CSS tokens (`--accent`, glassmorphism) + version `?v=9.2`.

### B4.3 Route/API (theo 7 bước Dashboard)
- Route Flask `@login_required` + `@guild_admin_required`: `GET/POST /dashboard/<guild_id>/economy` (đã có — mở rộng), thêm endpoints AJAX trong `api.py`: `GET /guild/<guild_id>/items`, `POST .../items` (thêm/xoá item trên catalog), `GET /guild/<guild_id>/inventory?user=...`.

## B5. Bước 5 (SOP) — Đồng bộ docs (cùng commit)

- `README.md`: mô tả `/work`, `/fish`, `/inventory`, `/sell`; cập nhật số lệnh.
- `ARCHITECTURE.md`: thêm bảng `items`, `user_inventory`, `user_jobs` vào "Core Database Schema"; cập nhật số lệnh = 91, số bảng = 39.
- `.agents/AGENTS.md`, `llms.txt`: cập nhật số lệnh & key.
- `.agents/skills/economy_system/SKILL.md`: bổ sung quy tắc mới (nghề, cá, túi đồ, bán vật phẩm).

## B6. Kiểm chứng Phần B (bắt buộc trước khi xong)

1. `python .agents/skills/zerynbot_architecture_context/assets/validate_all.py` → 100%.
2. `python .agents/skills/zerynbot_architecture_context/assets/check_db_schema.py` → không WARN.
3. `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` → 6 ngôn ngữ đồng bộ.
4. `pytest -q` → xanh (thêm test mới cho inventory/sell if có pipeline).
5. `ruff check .` → không còn lỗi nghiêm trọng.
6. **Manual:** `python main.py --bot`, gọi `/work`, `/fish`, `/inventory`, `/sell` trong Discord; kiểm tra `data/bot.db` (đúng số dư Ví, quantity của `user_inventory`).

---

# PHẦN C — Cổng Xác Thực & Anti-Raid (Verification Gate & Anti-Raid)  ⭐ CÒN THIẾU

> **Mục tiêu:** chặn bot rác/spam khi thành viên mới vào server, đồng thời bảo vệ server khỏi các hành vi "nuke" (mass-kick/ban, xoá role/kênh hàng loạt). **Đây là module mới hoàn toàn** → theo **SOP 5 bước** + **7 bước Dashboard** (thêm vào `DEFAULT_MODULES` là bắt buộc).
> **Trạng thái:** ✅ Bạn đã có sẵn **56 custom emoji** (trong đó có `zb_verified`), nên phần captcha/button sẽ dùng chính các emoji đó, không cần thêm asset mới.

## C0. Quyết định thiết kế

- **Verify = module riêng** (cog `verify.py`), **không** gộp vào `automod` — vì cơ chế gán role + quyền kênh khác hẳn bộ lọc tin nhắn.
- **Anti-Nuke / Anti-Raid** → **tích hợp vào `automod`** (dùng `automod_settings` + `immune_roles`) để không phình thêm module.
- **Cần quyền bot:** `Manage Roles`, `Manage Channels`, `Ban Members`, `Kick Members`, `Manage Guild`. Báo lỗi rõ nếu thiếu (dùng `BotMissingPermissions`).
- **Hai bước cho Verify:** ① setup kênh/role (tự động qua `/setup_verify` hoặc Dashboard) → ② member join → bị hạn chế → bấm nút/captcha → được gán role `verified`.
- **Dùng emoji sẵn có:** nút chính dùng `e('zb_verified')`; nếu chế độ captcha (chọn đúng emoji), dùng nhiều emoji trong `EMOJIS` (VD `zb_coin`, `zb_fish`, `zb_fun`, …) làm phương án — lấy từ `emojis.py` qua `e()`/`partial()`. Nếu `partial()` trả `None` (emoji không khả dụng ở server), fallback về emoji Unicode mặc định.
- **Lưu ý kỹ thuật quan trọng:** đây là **Application (bot) emoji** — chúng chỉ hiện diện/được dùng nếu bot đã vào server đó và Discord cho phép `PartialEmoji(name, id)` trong Button/Select. Trong captcha nên dùng **Button với `PartialEmoji`** (không phải reaction của user, vì user có thể không có emoji đó trong server). Nếu cần reaction thật, phải chọn emoji **guild** (không phải application emoji).

## C1. Bước 2 (SOP) — CSDL `database.py`

### C1.1 Migration an toàn (thêm bảng, theo mẫu `CREATE TABLE IF NOT EXISTS`)

```sql
CREATE TABLE IF NOT EXISTS verify_settings (
    guild_id            TEXT PRIMARY KEY,
    enabled             INTEGER DEFAULT 0,
    channel_id          TEXT,                -- kênh #xac-thuc
    verified_role_id    TEXT,                -- role được gán sau khi xác thực
    pending_role_id     TEXT,                -- (tuỳ chọn) role tạm cho member chưa verify
    guild_role_id       TEXT,                -- (tuỳ chọn) thay verified_role nếu muốn giữ nguyên
    mode                TEXT DEFAULT 'button', -- 'button' | 'captcha'
    message_title       TEXT,
    message_desc        TEXT DEFAULT 'Bấm nút bên dưới để xác thực và nhận role thành viên.',
    button_label        TEXT DEFAULT 'Tôi đã đọc nội quy & Xác thực',
    captcha_options     TEXT DEFAULT '[]',   -- JSON mảng emoji ứng viên cho captcha
    log_channel_id      TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Auto-Prune cấu hình (toàn hệ thống, dùng cho C6 — dọn dữ liệu cũ)
CREATE TABLE IF NOT EXISTS maintenance_jobs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT UNIQUE NOT NULL,
    last_run_at REAL DEFAULT 0
);
```

### C1.2 Các cột **anti-raid/anti-nuke** bổ sung cho `automod_settings` (migration an toàn trong `init_db()`)

```sql
-- thêm cột nếu chưa tồn tại (giống các ALTER đang có)
ALTER TABLE automod_settings ADD COLUMN anti_raid_enabled INTEGER DEFAULT 0;
ALTER TABLE automod_settings ADD COLUMN raid_join_per_window INTEGER DEFAULT 5;   -- số join/60s
ALTER TABLE automod_settings ADD COLUMN raid_action TEXT DEFAULT 'lockdown';      -- 'lockdown'|'verify_only'|'none'
ALTER TABLE automod_settings ADD COLUMN anti_nuke_enabled INTEGER DEFAULT 0;
ALTER TABLE automod_settings ADD COLUMN nuke_actions TEXT DEFAULT '["channel_delete","role_delete","guild_update"]';
```

### C1.3 Hàm sync (Dashboard) + async (Bot)

| Nhóm | Sync (sqlite3) | Async (aiosqlite) |
|---|---|---|
| Verify settings | `get_verify_settings(guild_id)` | `async_get_verify_settings(guild_id)` |
| Lưu verify settings | `upsert_verify_settings(guild_id, **fields)` | `async_upsert_verify_settings(...)` |
| Anti-raid/anti-nuke | mở rộng `upsert_automod_settings` (đã có) | `async_get_automod_settings` (đã có) |
| Auto-prune | `prune_old_data(days)` (maintenance) | `async_prune_old_data(days)` |
| Theo dõi join nhanh | `record_join_ts(guild_id, ts)` / `count_joins_window(guild_id, window)` | `async_record_join_ts` / `async_count_joins_window` |

## C2. Bước 1 (SOP) — Cog `bot/cogs/verify.py` (mới)

Các thành phần:

- **`on_member_join`**: nếu `verify.enabled` → (1) gán `pending_role_id` (nếu có) và **giới hạn kênh** (xem C3), (2) ghi nhận timestamp vào `raid_joins` để Auto-Raid đếm.
- **View Verify** (nút bấm "Tôi đã đọc nội quy & Xác thực"): `Button(custom_id="verify_accept")` → gán `verified_role_id`, gỡ `pending_role_id`, gửi thông báo chào mừng, log.
- **Captcha mode**: gửi một message gồm N emoji, thành viên chọn đúng emoji (button/emoji đúng) → mới được gán role. `captcha_answer` được tạo ngẫu nhiên mỗi lần.
- **Lệnh `/setup_verify`** (chỉ Bot Admin): tự tạo kênh `#xac-thuc` (nếu chưa có) + tạo role `Verified` (nếu chưa có) + thiết lập overrides + tự động gửi panel verify. Hoặc nếu muốn cấu hình thủ công thì bật trên Dashboard.
- **Lệnh `/verify panel`** (re-send panel khi mất); **`/verify test`**; **`/verify disable`**.
- **Module Guard:** đầu lệnh `if not await async_is_module_enabled(guild_id, "verify"): return`. Dùng `tr(settings, key, **kwargs)`.

## C3. Cơ chế "chỉ thấy 1 kênh #xac-thuc" (quan trọng)

Để thành viên mới **chỉ nhìn thấy** kênh xác thực:

- **Cách chuẩn (khuyên dùng):** chỉnh quyền override của kênh:
  - Với **mọi kênh khác** `#xac-thuc`: `@everyone` → **Deny** `View Channel` và `Send Messages`; role `verified_role` → **Allow** `View Channel` + `Send Messages`.
  - Với **kênh `#xac-thuc`**: `@everyone` → **Allow** `View Channel`, **Deny** `Send Messages` (chỉ để đọc + bấm nút).
- **Bắt buộc bot có `Manage Channels` + `Manage Roles`** — nếu thiếu, báo lỗi rõ qua `check`.
- **Cần cân nhắc:** cách override trên sẽ ảnh hưởng **toàn bộ kênh** của guild. Khi tắt verify phải **khôi phục** quyền (lưu snapshot overrides trước khi đổi, hoặc chỉ dừng ở mức "giữ nguyên quyền + chặn gửi tin" — nhẹ nhàng hơn, đủ chặn spam).

> 💡 **Khuyến nghị an toàn (P0):** Phiên bản đầu tiên nên làm chế độ **"chặn gửi tin + bắt buộc verify"** (không ẩn kênh triệt để) để tránh phá vỡ cấu hình quyền có sẵn của server. Chế độ **"chỉ thấy 1 kênh"** để là **tuỳ chọn nâng cao** (chạy sau khi đã kiểm thử kỹ).

## C4. Bước 3 (SOP) — i18n `locales/*.json`

Thêm bộ key `verify.*` vào **đủ 6 file**:

```
verify.title, verify.msg_default, verify.button_label, verify.accepted,
verify.already_verified, verify.role_assigned, verify.setup_done,
verify.setup_missing_perm, verify.captcha_prompt, verify.captcha_wrong,
verify.auto_raid.triggered, verify.anti_nuke.triggered, verify.log_join
```

- Chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` → `100% 6 ngôn ngữ đồng bộ`.
- Cập nhật số key trong `ARCHITECTURE.md`, `AGENTS.md`, `llms.txt`.

## C5. Bước 4 (SOP + 7 bước) — Dashboard

- **Module `verify`** → thêm vào `DEFAULT_MODULES` (`database.py`), bật/tắt trên trang `/dashboard/<guild_id>/modules`.
- **Trang `server_verify.html`** (theo 7 bước): cấu hình kênh (#xac-thuc), role verified, mode (button/captcha), text, nút "Sign up verify panel". Tuân thủ CSS tokens + `?v=9.2`.
- **`_COMMANDS_DATA`**: thêm `/setup_verify`, `/verify` vào danh mục phù hợp (VD "Quản trị" hoặc tạo danh mục "Bảo mật & An toàn"); cập nhật số lệnh.

## C6. Auto-Prune Database (nằm trong Nhóm 2 của bạn)

> Phần này **đã nêu ở A2** (dọn `guild_stats`, `automod_warnings`, `fun_interactions` theo thời gian). Tại đây chỉ **bổ sung cơ chế ghi nhớ lần chạy** để không trùng lặp:
- **Task ngầm 04:00** dùng `maintenance_jobs.last_run_at` để đảm bảo **chạy đúng 1 lần/ngày**.
- **Bảng cần dọn (đúng hiện trạng):** `guild_stats` (>60 ngày), `automod_warnings` (>24h), `fun_interactions` (>60 ngày). Không có `audit_logs`/`server_stats_hourly`.

## C7. Kiểm chứng Phần C

1. `validate_all.py`, `check_db_schema.py`, `validate_i18n.py` → pass.
2. `pytest -q` → xanh (thêm smoke test cho `verify.py` load).
3. **Manual:** tạo server test → bật verify → member mới vào bị hạn chế → bấm nút/captcha → được gán role; bật anti-raid → gửi 6 join/60s → lockdown kích hoạt; bật anti-nuke → thử xoá role/kênh → bị chặn/log.

---

# PHẦN D — Trí Tuệ Nhân Tạo 2.0 (AI Web Search & Link Summarizer)

> **Mục tiêu:** mở rộng `/ask` thành tra cứu thông tin trực tuyến (DuckDuckGo, miễn phí), và mở rộng `/summarize` thành tóm tắt bài báo/trang web (chống SSRF). **Tái sử dụng `call_ai_api` + routing Groq/Gemini/OpenRouter đã có**, không thêm provider mới.
>
> ⚠️ **Trạng thái trên `main`:** `/ask web=` và `/summarize url=` **đã có** (dùng `_fetch_duckduckgo_search` + `_fetch_url_article_content`). **NHƯNG `_fetch_url_article_content` CHƯA chặn SSRF** — nó `session.get(url)` trực tiếp, không gọi `is_safe_http_url`, không chặn `localhost`/IP private/link-local. → **Cần bổ sung bước validate URL trước khi tải.**

## D0. Quyết định thiết kế

- **Không phá vỡ cú pháp cũ.** `/ask [prompt] [image]` giữ nguyên; thêm **optional param `web: bool = False`**. `/summarize [limit]` giữ nguyên; thêm **optional param `url: str = None`**.
- **DuckDuckGo Instant Answers** là API miễn phí, **trả về JSON gọn** — phù hợp Termux, không cần key. Nhưng **không phải lúc nào cũng có kết quả** → cần fallback & thông báo rõ.
- **An toàn SSRF:** tái sử dụng `is_safe_http_url` (đã có ở `dashboard/auth.py:203`) → **port sang bot** (hoặc helper chung), chỉ cho http/https public. Thêm rate-limit + giới hạn độ dài trang.

## D1. Helper mới

| Helper | Vị trí | Chức năng |
|---|---|---|
| `web_search_ddg(query) -> list[str]` | `bot/cogs/ai.py` (hoặc `bot/utils_ai.py`) | Gọi DDG Instant Answer, trả danh sách đoạn ngắn/topic/answer |
| `fetch_and_extract_text(url) -> str` | `bot/cogs/ai.py` | Validate URL (SSRF), tải nội dung, strip HTML tag, giới hạn ~8000 ký tự |
| `summarize_text(text, lang="vi")` | `bot/cogs/ai.py` | Gọi `call_ai_api` để tóm tắt 3–5 ý + dịch tiếng Việt |

- **SSRF:** dùng `is_safe_http_url` (copy sang helper chung, tránh phụ thuộc dashboard), hoặc import từ `dashboard.auth` nếu đảm bảo không tạo vòng lặp. Chặn localhost/private/link-local; timeout ngắn (8s); chỉ http/https.

## D2. Bước 1 (SOP) — Mở rộng Cog `bot/cogs/ai.py`

### D2.1 `/ask` thêm `web: bool = False`
```python
@commands.hybrid_command(name="ask", description="Đặt câu hỏi thông minh (hỗ trợ tra cứu web: web=True)")
@app_commands.describe(prompt="Câu hỏi cần giải đáp", image="Ảnh đính kèm (tuỳ chọn)", web="Bật tra cứu web (True/False)")
async def ask(self, ctx, prompt: str, image: discord.Attachment = None, web: bool = False):
    ...
    if web:
        snippets = await web_search_ddg(prompt)
        if snippets:
            prompt = f"Người dùng hỏi: {prompt}\nKết quả web (DuckDuckGo):\n{chr(10).join(snippets)}\nHãy tổng hợp thành câu trả lời chính xác, nêu nguồn nếu có."
        else:
            # fallback: báo không có kết quả web, vẫn trả lời từ kiến thức
            prompt = f"Người dùng hỏi: {prompt}. (Không tìm thấy kết quả web — hãy trả lời từ kiến thức và nói rõ.)"
```
- **RATE-LIMIT + giới hạn:** đặt `web` chỉ cho phép gọi với tần suất thấp (VD `@commands.cooldown(1, 30, BucketType.user)`); bool param mặc định `False`.
- **Module Guard, `tr()`** như hiện tại.

### D2.2 `/summarize` thêm `url: str = None`
```python
@commands.hybrid_command(name="summarize", description="Tóm tắt tin nhắn trong kênh, hoặc tóm tắt 1 trang web (url=...)")
@app_commands.describe(limit="Số tin nhắn (mặc định 30)", url="URL trang web cần tóm tắt (tuỳ chọn)")
async def summarize(self, ctx, limit: int = 30, url: str = None):
    if url:
        text = await fetch_and_extract_text(url)   # chống SSRF bên trong
        summary = await summarize_text(text)
        await ctx.send(embed=discord.Embed(title=f"📄 Tóm tắt: {url}", description=summary, color=0xFEE75C))
        return
    # ... nhánh cũ (tóm tắt kênh chat) giữ nguyên
```
- **Chống lạm dụng:** rate-limit `@commands.cooldown(1, 30, BucketType.user)` cho nhánh `url`; giới hạn độ dài trang → parse `<title>` + 3–5 đoạn đầu để không tốn token.

## D3. Bước 3 (SOP) — i18n `locales/*.json`

Thêm key `ai.web.*` và `ai.summarize_url.*` vào **đủ 6 file**:

```
ai.web.searching, ai.web.no_results, ai.web.footer,
ai.summarize_url.title, ai.summarize_url.invalid_url,
ai.summarize_url.too_long, ai.summarize_url.done
```

- Chạy `validate_i18n.py` → 100% đồng bộ. Cập nhật số key trong docs.

## D4. Bước 4 (SOP) — Dashboard & `_COMMANDS_DATA`

- **`_COMMANDS_DATA`:** cập nhật mô tả + args của `/ask` (thêm `web`) và `/summarize` (thêm `url`). Số lệnh **không đổi** (chỉ sửa param) — nếu tách thành lệnh `/search` riêng thì +1.
- **Trang `server_ai.html`:** thêm switch "Cho phép tra cứu web" và mô tả tính năng tóm tắt URL; cập nhật theo 7 bước + CSS tokens.

## D5. Bước 5 (SOP) — Đồng bộ docs

- `README.md`, `ARCHITECTURE.md`, `.agents/AGENTS.md`, `llms.txt`, và `ai_provider_routing/SKILL.md` (nếu đổi cấu hình provider).

## D6. Kiểm chứng Phần D

1. `validate_all.py` / `validate_i18n.py` / `check_db_schema.py` → pass.
2. `pytest -q` → xanh.
3. **Security test mới:** gửi `/summarize url=http://localhost` / `http://192.168.1.1` / `file:///etc/passwd` → **bị chặn** (kiểm tra SSRF). **Hiện tại trên `main` chưa chặn** → cần thêm test + fix.
4. **Manual:** `/ask web:true "Thủ đô của Úc"` trả kết quả từ web; `/summarize url:https://en.wikipedia.org/wiki/Python` trả 3–5 ý.

> 🔒 **Việc cần làm ngay (Phần D):** thêm bước validate trong `_fetch_url_article_content`:
> ```python
> from dashboard.auth import is_safe_http_url  # hoặc copy helper sang bot để tránh phụ thuộc
> if not is_safe_http_url(url):
>     return None
> ```
> và thêm test assert rằng `localhost`/`127.0.0.1`/`file://` bị loại bỏ.

---

# Phần E/F — Các giai đoạn tiếp theo (lộ trình tổng, chưa code chi tiết)

> Nhóm 4 (Live Log Viewer + Announcement Scheduler) — sẽ mở rộng thành plan riêng khi bạn yêu cầu.

## E. Live Web Log Viewer
- **Live log:** endpoint `/admin` chỉ cho owner, tail `data/bot.log` (đã có RotatingFileHandler). Trả về **trang** (không stream vô hạn), hỗ trợ auto-refresh.
- **File đụng tới:** `dashboard/app.py` (route `/admin/system/log`), `admin.html`.

## F. Announcement Scheduler
- **Lập lịch thông báo:** tái sử dụng cơ chế reminder / `guild_stats` / task loop (giống birthday/backup). Bảng `scheduled_announcements(guild, channel, message, at, created_by)`.
- **File đụng tới:** cog mới `announce.py`, bảng mới, `_COMMANDS_DATA`, trang `server_announce.html`.

---

## 🧭 Quy trình git (theo AGENTS.md, nhưng lưu ý branch)

- **Mỗi nhóm công việc = 1 commit** với Conventional Commits:
  - `fix(db): align busy_timeout to 15000 per docs` (A1)
  - `feat(maintenance): add auto-prune scheduled task` (A2)
  - `refactor: clean up critical ruff issues` (A3)
  - `feat(cache): implement true LRU eviction` (A4)
  - `feat(economy): add /work /fish /inventory /sell + update docs` (B)
  - `feat(verify): add verification gate & anti-raid + update docs` (C)
  - `feat(ai): add web search & url summarize + update docs` (D)
- **Branch:** phiên này bị khoá ở `arena/01a062d4-zerynbot`. Tôi **commit trên branch này**, sau đó **gửi PR từ `arena/...` về `main`** (hoặc hướng dẫn bạn merge). KHÔNG đẩy thẳng lên `main` từ đây.
- Luôn chạy `validate_all.py` + `pytest -q` **trước khi commit** (kiểm tra `py_compile` + docs sync).

---

## 📌 Thứ tự thực hiện đề nghị

> ⚠️ Bạn đã triển khai **A1**, **B** (gần xong) và **D** (gần xong) trên `main`. Các mục còn lại:

1. **C (Verify Gate / Captcha / Anti-Raid)** — ⭐ **quan trọng nhất, đang thiếu**, là thứ bạn hỏi "chưa có xác minh trước khi vào server". Dùng 56 emoji sẵn có (`zb_verified`).
2. **A2 (Auto-prune)** + **A4 (Cache LRU)** — dọn nền, chạy song song.
3. **B hoàn thiện**: (a) xem có nên thêm bảng `items` catalog hay giữ inline `user_inventory`; (b) bổ sung phần i18n nếu thiếu, Dashboard `server_economy.html`, `_COMMANDS_DATA` (đã 92), docs.
4. **D hoàn thiện**: (a) **thêm SSRF check cho `/summarize url=`**; (b) i18n + `server_ai.html` + docs nếu thiếu.
5. **A3 (ruff)** — dọn lỗi nghiêm trọng trên toàn repo.
6. (tuỳ chọn) **E/F** — Live Log, Announcement Scheduler.

> **Khuyến nghị bắt đầu:** làm **C → A2/A4** trước (C là thứ bạn đang cần; A2/A4 giúp nền ổn định khi thêm module mới). Mỗi bước xong tôi báo cáo và luôn chạy `validate_all.py` + `pytest` trước khi commit.

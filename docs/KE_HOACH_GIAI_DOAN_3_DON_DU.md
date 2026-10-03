# Kế Hoạch Đóng Dư Giai Đoạn 3 — Kiểm Chứng & Sửa Nốt Tài Liệu

> Ngày kiểm chứng: 2026-10-03 · Branch: `main` · HEAD: `0982874`
> Phạm vi: đóng nốt phần **tài liệu + 1 điểm code còn nợ** sau khi tách 3 file lớn.
> Quy tắc: chỉ sửa tài liệu/nhãn sai + 1 sửa code an toàn. **KHÔNG commit/push** nếu chưa được yêu cầu.

---

## 0. Kết luận ngắn

**Code Giai đoạn 3 đã hoàn thành và đã được commit.** Phần còn lại **không phải lỗi runtime** mà là
**tài liệu chưa đồng bộ 100%** (còn ~24 dòng tham chiếu tới `database.py` / `dashboard/app.py` /
tên class `MusicVoiceMixin` không tồn tại) + **1 điểm code nhỏ** trong blueprint `guild` đang mở
SQLite thô (vi phạm quy tắc PRAGMA của chính tài liệu).

Không có lỗi chức năng nào cần sửa. Không có file nào hỏng.

---

## 1. Bằng chứng đã kiểm chứng (chạy thật hôm nay)

| Hạng mục | Lệnh | Kết quả |
|---|---|---|
| Test suite | `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q -p no:cacheprovider --no-header` | ✅ **154 passed** (5.4s) |
| Self-test hệ thống | `python main.py --test` | ✅ **11/11 nhóm, 141 assertions** |
| Trạng thái tiến trình | `python main.py --status` | ✅ OK (Bot/Dashboard STOPPED — đúng, không ai chạy) |
| Watchdog | `bash -n scripts/watchdog.sh` | ✅ Syntax OK |
| Skill validator | `python .agents/skills/zerynbot_architecture_context/assets/validate_all.py` | ✅ 122 file .py biên dịch sạch, 6 locale đồng bộ 1694 keys, docs nhất quán |
| Skill DB schema | `python .agents/skills/zerynbot_architecture_context/assets/check_db_schema.py` | ✅ Đã được sửa sang đọc `database/schema.py` + `database/conn.py` |
| Dashboard thật (waitress) | boot `dashboard.app:app` trên `127.0.0.1:5097` | ✅ **80 rules / 79 endpoints**, blueprint = {admin, api, guild, music, public, static, support} |
| HTTP smoke | `/` 200 · `/tos` 200 · `/privacy` 200 · `/login` 200 · `/docs` 200 · `/support` 200 · `/dashboard` 200 · `/ui/language/en` 200 · `/health` 503 (đúng — bot chưa chạy) | ✅ |
| Cô lập DB khi test | mtime `data/bot.db` trước/sau full suite | ✅ **không đổi** (1791019300.6110282 → giữ nguyên) |
| Working tree | `git status --porcelain \| wc -l` | ✅ **0** — sạch, `.tmp_gd3/` đã được xoá |

**Ghi chú `/commands` trả 404**: không phải lỗi — route thật là `/dashboard/<guild_id>/commands`
(`guild.server_commands`), kiểm tra bằng `app.url_map`.

**Commit chứa phần tách**: `3d71d8b feat(arch): modularize database, music, and dashboard blueprints (phase 3)`.
Kích thước gốc (lấy từ `git show 3d71d8b^`): `database.py` **4262** dòng → package 14 module;
`dashboard/app.py` **2238** dòng → 93 dòng shim + 5 blueprint; `bot/cogs/music.py` **3025** dòng → 964 dòng facade + `bot/music/` 7 module.

---

## 1.1 ✅ Kết quả thực thi (đã áp dụng xong, 2026-10-03)

| Hạng mục | Kết quả |
|---|---|
| B1 `ARCHITECTURE.md` | ✅ 13 chỗ sửa (A1–A11 + changelog v3.2: 4262 dòng / 2238 dòng / 79 endpoint / `VoiceLifecycleMixin` + bullet **Safety Net**) + ghi chú ngoại lệ connection thô ở §8 |
| B2 `llms.txt` + `README.md` | ✅ `llms.txt:61` tách registry sang `commands_data.py`; `README.md` thêm `commands_data.py`, `extensions.py`, `web_helpers.py` |
| B3 `.agents/` | ✅ 9 file: AGENTS.md (78, 107), rules/doc_sync.md, rules/critical_inquiry.md, 4 SKILL.md, validate_all.py |
| B4 Code P2 | ✅ `database/events.py` thêm `delete_tempvoice_channel()` (dùng `get_db_connection()`); `dashboard/blueprints/guild.py` bỏ `sqlite3.connect` thô + bỏ import `sqlite3`; `database/__init__.py` re-export + `__all__` |
| B4b Ngoài kế hoạch | ✅ `main.py:393` comment trỏ `dashboard/extensions.py`; 2 script `scratch/` (gitignored) trỏ `commands_data.py`, script sinh file cũ thêm chặn deprecated |
| Cổng kiểm chứng | ✅ `154 passed` · `main.py --test` 11/11 (141 asserts) · `validate_all` / `check_db_schema` / `validate_i18n` 100% · boot waitress **80 rules / 79 endpoints** · `data/bot.db` mtime **không đổi** · `bash -n watchdog.sh` OK |
| Kiểm chứng riêng P2 | ✅ Xoá đúng channel của guild; **cross-guild guard** giữ nguyên channel của server khác; DELETE không tồn tại không lỗi; PRAGMA `busy_timeout=15000` + `cache_size=-8000` vẫn áp dụng |

---

## 2. Danh sách việc còn lại

Mỗi mục có: **Vị trí → Hiện trạng → Sửa thành**.

### P0 — `ARCHITECTURE.md` (nguồn chân lý, sai thì AI sửa sai theo)

| # | Dòng | Hiện trạng | Sửa thành |
|---|---|---|---|
| A1 | 42–43 | `` `aiosqlite` via `database.py` `async_*` `` / `` `sqlite3` via `database.py` sync `` | `database/` package (`conn.py` cho kết nối, module theo domain cho truy vấn) |
| A2 | 88 | `cog_voice.py  # MusicVoiceMixin (...)` | **`VoiceLifecycleMixin`** (tên class thật trong [bot/music/cog_voice.py](bot/music/cog_voice.py)) |
| A3 | 109 | `music.py # Music Cog controller inheriting MusicVoiceMixin` | `inheriting VoiceLifecycleMixin` |
| A4 | 121 | `app.py # Entrypoint facade (app = create_app()), _COMMANDS_DATA central registry` | Bỏ `_COMMANDS_DATA` khỏi mô tả `app.py`; thêm dòng `commands_data.py # _COMMANDS_DATA — registry 110 lệnh / 17 danh mục` |
| A5 | 162 | `` created automatically on startup by `init_db()` in `database.py` `` | `... in `database/schema.py`` |
| A6 | 278 | Bảng cog: `| **Music** | bot/cogs/music.py |` | Thêm ghi chú facade → `bot/cogs/music.py` (facade, 964 dòng) + `bot/music/*` (7 module) |
| A7 | 312 | `` All 110 active commands ... registered in `dashboard/app.py` `` | `` registered in `commands_data.py` (rendered by `dashboard/commands_catalog.py`) `` |
| A8 | 398 | `` aiosqlite thread pool executors (`database.py` async methods) `` | `` (`database/` async helpers) `` |
| A9 | 414 | `` (2MB × 2 backups) in `bot/bot.py` and `dashboard/app.py`. `` | `` in `bot/bot.py` and `dashboard/extensions.py`. `` |
| A10 | 471 | Rule 8: `` wrap ... inside `init_db()` in `database.py` `` | `` in `database/schema.py` `` |
| A11 | 497 | Anti-pattern #17: `` Always register new commands in `_COMMANDS_DATA` (`dashboard/app.py`) `` | `` (`commands_data.py`) `` |

### P0 — Changelog v3.2 (ARCHITECTURE.md dòng 553–555): số liệu sai cần chỉnh

| Sai | Đúng |
|---|---|
| `database.py` (4263 lines) | **4262 lines** |
| `dashboard/app.py` (2215 lines, 64 routes) | **2238 lines, 79 endpoints** (80 rules) |
| `MusicVoiceMixin` | **`VoiceLifecycleMixin`** |
| *(thiếu)* | Bổ sung 1 bullet: **Safety Net (Bước 0)** — `set_db_path()/get_db_path()` là nguồn DB path duy nhất cho test; 44 test mới bảo vệ hành vi (`tests/test_music_behavior.py` 28, `tests/test_database_api_surface.py` 8, `tests/test_dashboard_routes.py` 8) — tổng 110 → **154 test**. |
| *(thiếu)* | Bổ sung: `database/conn.py` giữ DB_PATH; `dashboard/app.py` còn 93 dòng làm shim tương thích. |

### P1 — `llms.txt` + `README.md`

| File:line | Hiện trạng | Sửa thành |
|---|---|---|
| `llms.txt:61` | `` `dashboard/app.py`: Web dashboard entrypoint facade and `_COMMANDS_DATA` central registry. `` | Tách 2 dòng: `dashboard/app_factory.py` (+ `blueprints/`) = app factory & routes; `commands_data.py` = `_COMMANDS_DATA` registry. |
| `README.md:339` | `│   ├── app.py           # Facade entrypoint & _COMMANDS_DATA registry` | `# Shim tương thích (app = create_app())`; thêm dòng `commands_data.py # _COMMANDS_DATA — registry 110 lệnh`. |
| `README.md:336–340` | Thiếu 2 module mới | Thêm `extensions.py` (logger/limiter/CSRF) và `web_helpers.py` (decorator + cache). |

### P1 — `.agents/` (quy tắc & skill cho AI)

| File:line | Hiện trạng | Sửa thành |
|---|---|---|
| `.agents/AGENTS.md:78` | link `_COMMANDS_DATA` → `dashboard/app.py` | → `commands_data.py` |
| `.agents/AGENTS.md:107` | `` Cập nhật Cog logic + `_COMMANDS_DATA` trong `dashboard/app.py` `` | `` trong `commands_data.py` `` |
| `.agents/rules/doc_sync.md:8` | `` Đăng ký lệnh vào `_COMMANDS_DATA` trong `dashboard/app.py` `` | `` trong `commands_data.py` `` |
| `.agents/rules/critical_inquiry.md:35` | `` đăng ký vào `_COMMANDS_DATA` trong `dashboard/app.py` `` | `` trong `commands_data.py` `` |
| `.agents/skills/dashboard_dev_guide/SKILL.md:52` | `` Đăng ký Module trong `DEFAULT_MODULES` (`database.py`) `` | `` (`database/guilds.py`) `` |
| `.agents/skills/dashboard_dev_guide/SKILL.md:53` | `` Viết hàm CSDL ... trong `database.py` `` | `` trong `database/<domain>.py` `` |
| `.agents/skills/dashboard_dev_guide/SKILL.md:54` | `` Thêm Route Flask trong `dashboard/app.py` `` | `` trong blueprint phù hợp `dashboard/blueprints/{guild,music,admin,support}.py` `` |
| `.agents/skills/dashboard_dev_guide/SKILL.md:64` | `` AJAX POST trong `dashboard/app.py` `` | `` trong `dashboard/blueprints/*` `` |
| `.agents/skills/zerynbot_architecture_context/SKILL.md:69` | `` `_COMMANDS_DATA` trong `dashboard/app.py` `` | `` trong `commands_data.py` `` |
| `.agents/skills/zerynbot_architecture_context/assets/validate_all.py:7,108` | nhắc `dashboard/app.py` chứa `_COMMANDS_DATA` | chỉ còn `commands_data.py` (file này **đã** ưu tiên `commands_data.py` nên vẫn chạy đúng) |
| `.agents/skills/ai_provider_routing/SKILL.md:12` | liệt kê `dashboard/app.py` là nơi chứa AI layer | → `dashboard/blueprints/admin.py` + `dashboard/app_factory.py` |
| `.agents/skills/music_audio_pipeline/SKILL.md:12,77` | `` Module Music (`bot/cogs/music.py`) `` | thêm `` (`bot/cogs/music.py` facade + `bot/music/*`); `MAX_PLAYERS` ở `bot/music/config.py` `` |

### P2 — Code: 1 điểm mở SQLite thô (mang từ bản cũ)

**File:** [dashboard/blueprints/guild.py:593-600](dashboard/blueprints/guild.py#L593-L600) — `server_tempvoice_delete_channel`

```python
import database as db_mod
with sqlite3.connect(db_mod.DB_PATH) as conn:      # ❌ không PRAGMA, không busy_timeout
    conn.execute("DELETE FROM tempvoice_active WHERE channel_id = ? AND guild_id = ?", (channel_id, guild_id))
    conn.commit()
```

Vi phạm đúng quy tắc **PER-CONNECTION PRAGMA RULE** mà `ARCHITECTURE.md` §8 đang viết: kết nối này
không có `busy_timeout=15000`, nên khi bot đang ghi `tempvoice_active` có thể ném
`sqlite3.OperationalError: database is locked` và trả 500 cho admin.

**Cách sửa đề xuất (đúng nguyên tắc "route through the helpers"):**

1. Thêm vào [database/community.py](database/community.py) (nơi đang giữ tempvoice):
   ```python
   from .conn import get_db_connection   # thêm vào khối import hiện có

   def delete_tempvoice_channel(guild_id: str, channel_id: str) -> None:
       """Xoá phòng voice tạm (scope theo guild_id). Sync cho dashboard."""
       with get_db_connection() as conn:
           conn.execute(
               "DELETE FROM tempvoice_active WHERE channel_id = ? AND guild_id = ?",
               (channel_id, guild_id),
           )
           conn.commit()
   ```
2. Blueprint gọi `db.delete_tempvoice_channel(guild_id, channel_id)`, bỏ `import sqlite3` / `import database as db_mod` cục bộ.

> Lưu ý API: `_connect_sync()` ([database/conn.py:68](database/conn.py#L68)) trả về `conn` thô và **không phải** context manager —
> dùng `get_db_connection()` ([database/conn.py:93](database/conn.py#L93)) đã là `@contextmanager`, tự set PRAGMA,
> tự `close()` trong `finally` (tránh rò file descriptor trên waitress).
> **Không** sửa logic nghiệp vụ, chỉ đổi đường lấy connection.

### P3 — Ngoại lệ cần ghi rõ (không sửa code)

`bot/tester.py` (6 chỗ: dòng 135, 347, 368, 445, 599, 616) và `database/maintenance.py:179`
cố ý mở connection thô (self-test đo đúng mức tuning thật; `VACUUM` phải tắt `temp_store=MEMORY`).
→ **Không sửa**, nhưng nên thêm 1 dòng chú thích ở `ARCHITECTURE.md` §8 rằng đây là ngoại lệ có chủ đích.

---

## 3. Test hardening đề xuất (P3 — làm sau khi đóng docs)

Ba "điểm mù" còn lại sau khi tách, chưa có test canh:

| # | Ý nghĩa | Test đề xuất |
|---|---|---|
| T1 | Shim `dashboard/app.py` có thể mất tên re-export mà không ai biết | `tests/test_dashboard_routes.py`: assert tập `_FACADE_EXPORTS`/`__all__` của [dashboard/app.py](dashboard/app.py) ⊆ `dir(dashboard.app)` và import được từng tên |
| T2 | Vòng import ở `bot/music/` chỉ lộ ra khi import theo thứ tự khác | Test subprocess: `import bot.music.views` / `player` / `cog_voice` **độc lập**, mỗi cái 1 process sạch → phải OK |
| T3 | `database/` có thể sót module khỏi `__all__` | Test: mỗi `database/*.py` (trừ `__init__`) phải import được standalone và tên public của nó phải xuất hiện trong `dir(database)` |

---

## 4. Thứ tự thực hiện đề xuất

- [x] **B1** — `ARCHITECTURE.md`: A1–A11 + sửa số liệu changelog v3.2 + thêm bullet Safety Net.
- [x] **B2** — `llms.txt:61`, `README.md:336–340`.
- [x] **B3** — `.agents/`: `AGENTS.md` (78, 107), `rules/doc_sync.md:8`, `rules/critical_inquiry.md:35`, `dashboard_dev_guide/SKILL.md` (52, 53, 54, 64), `zerynbot_architecture_context/SKILL.md:69` + `assets/validate_all.py:7,108`, `ai_provider_routing/SKILL.md:12`, `music_audio_pipeline/SKILL.md:12,77`.
- [x] **B4** — Code P2: `database/events.py` (`delete_tempvoice_channel`) + `dashboard/blueprints/guild.py`.
- [ ] **B5** — (tuỳ chọn) P3: thêm T1–T3 vào `tests/`.
- [x] **B6** — Dọn file tạm và chạy cổng kiểm chứng.

> Mỗi bước phải xanh mới đi tiếp (theo nguyên tắc đã chốt của Giai đoạn 3).

---

## 5. Cổng kiểm chứng cuối (chạy hết trước khi chốt)

```bash
# 1. Test suite — kỳ vọng 154 passed (hoặc 157 nếu đã làm P3)
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q -p no:cacheprovider --no-header

# 2. Self-test hệ thống — kỳ vọng 11/11 nhóm, 141 assertions
python main.py --test

# 3. Skill validators — kỳ vọng 100% HOÀN HẢO
python .agents/skills/zerynbot_architecture_context/assets/validate_all.py
python .agents/skills/zerynbot_architecture_context/assets/check_db_schema.py
python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py

# 4. Trạng thái + script vận hành
python main.py --status
bash -n scripts/watchdog.sh

# 5. Cô lập DB (phải KHÔNG đổi)
python -c "import os;print(os.path.getmtime('data/bot.db'))"   # trước & sau pytest

# 6. Quét tài liệu còn tham chiếu file đã xoá — kỳ vọng 0 kết quả
python - <<'PY'
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pat = re.compile(r"database\.py|dashboard/app\.py|MusicVoiceMixin")
bad = 0
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "data", ".pytest_cache")]
    for fn in files:
        if not fn.endswith((".md", ".txt", ".py", ".yml")):
            continue
        p = os.path.join(root, fn)
        for i, l in enumerate(open(p, encoding="utf-8", errors="replace").read().splitlines(), 1):
            if pat.search(l):
                print(f"{p}:{i}: {l.strip()[:110]}"); bad += 1
print("con sot:", bad)
PY

# 7. Working tree sạch (trừ file kế hoạch này nếu chưa commit)
git status --porcelain
```

---

## 6. Definition of Done

1. Lệnh mục **6** in `con sot: 0` (trừ các dòng nói chủ đích về lịch sử trong changelog v3.1).
2. `154 passed` (hoặc `157 passed` nếu có P3) — không test nào bị xoá/lỏng.
3. `python main.py --test` vẫn **11/11**.
4. `dashboard` boot thật: `80 rules / 79 endpoints`, các trang public trả 200.
5. `data/bot.db` mtime không đổi sau full test suite.
6. Thay đổi nằm trong working tree — **chưa commit/push** nếu chủ dự án chưa yêu cầu.
# BÁO CÁO AUDIT — ZerynBot V2: Quét toàn repo tìm lỗi ẩn

**Ngày audit:** 18/10/2026 · **Commit:** `c2dec62` (main) · **Phạm vi:** toàn bộ 138 file `.py` (~42.3k LOC)

**Kết luận nhanh:** Repo đã qua nhiều đợt hardening (`46622f6`→`c2dec62`), các "hình mẫu" lỗi kinh điển (prune epoch-vs-`datetime()`, backup fallback sang webhook log, step-up fail-open, persistent views chết, FK OFF) **đã được sửa và xác minh tại chỗ**. **Không phát hiện CRITICAL.** Còn lại **3 HIGH** (2 trong `remind.py` — đã repro bằng code thật, 1 trong music player — đã repro cơ chế), cùng một loạt MEDIUM/LOW.

---

## 1. Cách đã kiểm tra

| Bước | Kết quả |
|---|---|
| `python -m compileall` | ✅ sạch, 138 file `.py`, ~42.3k dòng |
| `python -m pytest` | ✅ **301 passed** trong 24s |
| `scripts/command_registry_audit.py` | ✅ 128/128 lệnh (script tự nó crash cp1252 trên Windows — xem L3) |
| `scripts/i18n_audit.py` | ✅ DISCORD hardcoded = 0 (budget đã đóng) |
| Probe DB live (chỉ đọc, `file:...?mode=ro`) | journal=WAL, FK bật trong `database/conn.py`, **0 hàng mồ côi** trên cả 3 chuỗi FK, kiểu cột epoch/TEXT nhất quán với mọi vị từ prune |
| Route inventory dashboard | 79 route liệt kê đầy đủ; mọi route mutating có guard (`_require_guild_access` × 17, `owner_required`, `guild_access_required`, `stepup_required`) |
| Grep log tìm key prefix (`gsk_`, `AIza`, `sk-or-`, token) | 0 hit trong `data/*.log` |
| Repro bằng code thật | **3 lỗi chứng minh được** bằng cách chạy chính callback cog/player: `scratch/audit_repro_remind.py`, `scratch/audit_repro_player_skip.py` |

> Một suite sạch **không phải** bằng chứng về tính đúng — 3 lỗi HIGH dưới đây đều compile pass, test pass, và vẫn gây mất dữ liệu phía người dùng.

---

## 2. P0 — CRITICAL

**Không tìm thấy.** Không có lỗi phá hủy dữ liệu hàng loạt, không có lỗ hổng bảo mật bypass auth/IDOR/CSRF/timetravel, không có rò rỉ secret trong log.

---

## 3. P1 — HIGH (đã repro)

### H1. Reminder bị XÓA kể cả khi chưa gửi thành công

- **Vị trí:** `bot/cogs/remind.py` → `reminder_task` (L90–L153), dòng xóa L151.
- **Chuỗi lỗi:** gửi kênh fail (mạng chợp/lost permission) → fallback DM fail (user tắt DM — trạng thái **bình thường**, không phải edge case) → `async_delete_reminder(remind_id)` chạy **vô điều kiện** → reminder biến mất, user không được báo gì.
- **Repro (chạy code cog thật):**
  ```
  A) channel send failed: True | DM failed: yes | reminder deleted anyway: True
  A) CONFIRMED: reminder #7 was DELETED even though delivery never happened.
  ```
- **Root cause:** bước "Xóa nhắc nhở" (comment số 4 trong code) không được gate bởi cờ `sent`.
- **Fix:** chỉ xóa khi `sent=True`; ngược lại giữ hàng đợi retry cycle sau, xóa sau N lần thử (khuyến nghị N=3) + `logger.warning`.

### H2. Một "poison row" âm thầm chặn TOÀN BỘ batch reminder mãi mãi

- **Vị trí:** cùng hàm — `try` bọc vòng `for` (L93) và `except Exception: pass` (L152–153).
- **Chuỗi lỗi:** bất kỳ row nào raise (`int(r["user_id"])` với user_id không số, embed build lỗi, `tr()` thiếu key…) → whole loop abort → **không log gì** → cycle sau vẫn dừng đúng ở row đó → mọi reminder xếp sau bị chặn vĩnh viễn.
- **Repro:**
  ```
  B) CONFIRMED: healthy reminder #2 never delivered, no log, exception swallowed.
  ```
- **Fix:** hạ `try/except` vào **từng vòng lặp** + `logger.exception`, row lỗi vẫn delete (hoặc chuyển trạng thái) để không chặn hàng đợi.

### H3. Bấm /skip đúng lúc đang recovery → cờ `_skipped` treo → hàng đợi chết đến khi skip lần 2

- **Vị trí:** `bot/music/player.py` — guard `_after_play` L397, nhánh recovery kiểm tra `_skipped` rồi `return` ở L477 và L525, guard `_play` L698, đường cứu trong `skip()` L854–872.
- **Chuỗi lỗi:** `skip()` set `_skipped=True` + `vc.stop()` → after-callback bị lớp chống zombie **bỏ qua** khi `_recovering=True` → coroutine recovery đang chờ wake lên, thấy `_skipped` thì `return` mà **không tiêu cờ, không dispatch bài kế** → mọi `_play()` sau đó early-return ở L698.
- **Repro cơ chế (chạy MusicPlayer thật với FakeVC):**
  ```
  _skipped stuck: True | _play() played anything: False
  CONFIRMED (mechanism): skip during recovery leaves _skipped=True; all _play() blocked;
                         queue only revives if the user presses skip again while nothing plays.
  ```
- **Vì sao test không bắt:** `test_music_behavior.py` chỉ cover skip khi `_recovering=False`. Cửa sổ thực tế (backoff 2s + cleanup source tới 5s) chính là lúc user hay bấm skip nhất (stream kẹt).
- **Fix:** ở cả 2 nhánh recovery, khi thấy `_skipped` thì reset cờ + `await self._dispatch_next_async()` (đúng pattern đang có ở `_handle_after_play_async` L442–445). Test behavior mới dựng nguyên scenario của repro.

---

## 4. P2/P3 — MEDIUM & LOW (rút gọn, đã cắt bớt một số ghi chú nhỏ)

| # | Mức | Phát hiện | Vị trí |
|---|---|---|---|
| M1 | MEDIUM | `economy_transactions` + `mod_warnings` **không có retention** (grep `DELETE FROM economy_transactions` = 0 hit) → phình vô hạn trên máy 6GB chạy 24/7 | `database/maintenance.py` |
| M2 | MEDIUM | `asyncio.create_task()` fire-and-forget không giữ strong reference (event loop chỉ giữ weak ref → task có thể bị GC giữa chừng): `player.py` L733, L914; `bot.py` L534, L560; `cog_voice.py` L51; `stats.py` L21 | nhiều nơi |
| M3 | MEDIUM | `upsert_guild` nội suy **tên cột** từ key của `**fields` vào SQL — hiện an toàn vì cả 8 call site đều static/whitelisted, nhưng là bom hẹn giờ: một call site tương lai nhận key từ user = SQLi. Cần whitelist cột theo `PRAGMA table_info(guilds)` | `database/guilds.py` L68–82 |
| L1 | LOW | `int(request.args.get("after_id"))` không bắt lỗi → trang 500 khi query `?after_id=abc` | `dashboard/blueprints/support.py` L55 |
| L2 | LOW | `toggle_module` nhận `module_name` bất kỳ → rác trong `guild_modules` | `dashboard/api.py` L125 |
| L3 | LOW | `scripts/command_registry_audit.py` crash `UnicodeEncodeError` cp1252 trên Windows (phải tự set `PYTHONIOENCODING` mới chạy được) — nên `sys.stdout.reconfigure` như `app_factory.py` | scripts/ |
| L4 | LOW | `termux_mcp.py` L39 gọi `paramiko.SSHClient()` **trước** `try` — thiếu paramiko là crash, nhánh fallback Cloudflare tunnel không bao giờ chạy | scripts/ |
| L5 | LOW | `watchdog.sh` tin `kill -0 $pid` mà không check cmdline (`/proc/<pid>`) → PID reuse sau reboot có thể SIGTERM nhầm process lạ | scripts/watchdog.sh |

### Đã xác minh OK (không cần sửa)

- FK enforcement bật qua `_connect_async`/`_connect_sync`, DB live 0 hàng mồ côi.
- Backup: snapshot nhất quán qua SQLite backup API, chỉ gửi về `BACKUP_DB_URL`, **không fallback** sang webhook log.
- Step-up fail-closed (`_admin_password_ready` + 503), `secrets.compare_digest`, TTL 15 phút, audit trail `activity_logs`.
- OAuth: `state` chống login-CSRF, token vault trong tiến trình (cookie chỉ mang con trỏ), logout thu hồi token.
- Persistent views: music/tempvoice/verify/giveaway đều `bot.add_view`; ticket đi qua global `on_interaction` listener (custom_id tĩnh) — không cần add_view, không overlap với listener của `bot.py`.
- AI: ngân sách sync 20s / async 45s, `timeout=` mọi request, `allow_redirects=False`, SSRF guard, chặn ảnh >cap, redact key (`prefix****last4`).
- Cache LRU thread-safe (RLock), TTL 30s cho settings; `music_song_cache`/`activity_logs` dùng REAL epoch — vị từ prune khớp kiểu dữ liệu.
- PRAGMA per-connection (busy_timeout 15s, cache 8MB, mmap 64MB) tập trung một chỗ duy nhất.

### Không xác minh được (cần thiết bị)

- Hành vi stall-watchdog với ffmpeg kẹt D-state thật trên Termux.
- Rate-limiter key đúng remote-IP hay không sau Cloudflare (cần probe `CF-Connecting-IP` trên device).

---

## 5. Kế hoạch sửa theo phase

Mỗi phase = 1 commit, test-first (test phải **đỏ** nếu revert fix), chạy `py_compile` + `pytest`, gate Model-2 `python scripts/dual_model_mcp.py --pre-commit-check` trước commit, sync số liệu README/ARCHITECTURE/llms.txt theo `.agents/AGENTS.md`.

| Phase | Nội dung | Effort |
|---|---|---|
| **1** | **Remind delivery guarantee (H1+H2):** retry policy + per-row try/except + log; port 2 scenario repro thành invariant test: *"reminder gửi fail không bị xóa"*, *"poison row không chặn row sau"* | ~1h |
| **2** | **Music skip/recovery race (H3):** tiêu `_skipped` trong 2 nhánh recovery rồi dispatch; behavior test mở rộng harness `_FakeVC` hiện có | ~1.5h |
| **3** | **Retention (M1):** prune `economy_transactions` (+`mod_warnings` nếu duyệt) bằng cutoff epoch an toàn trong job `maintenance.py` | ~30m |
| **4** | **Task-GC + input hygiene (M2+M3+L1+L2):** helper task-bag (tái dùng pattern `_bg_tasks` của cog music); whitelist cột cho `upsert_guild`; guard `after_id`; validate `module_name` ∈ `DEFAULT_MODULES` | ~45m |
| **5** | **Ops nits (L3+L4+L5):** reconfigure UTF-8 script audit; guard paramiko; PID identity check trong watchdog | ~30m |

**Tổng: ~4.5h.**

### Tối ưu code (theo yêu cầu)

- **O1:** 82 chỗ `with _connect_sync()` chỉ commit mà không *close* (fd tự đóng nhờ refcount GC) — chuyển hết sang helper `get_db_connection()` có sẵn để đóng deterministic dưới 4 thread của Waitress.
- **O2:** `cache.get("settings:<id>")` trả **đúng object dict** đang cache cho mọi caller — một lần mutate nhầm là poisoning cache 30s; trả `dict.copy()` hoặc snapshot đóng băng khi set.
- **O3:** gom 2 lớp zombie-guard (`_recovering` + so `bound_source`) trong `_after_play` thành một counter `_play_generation` tăng mỗi lần `_play()` — đơn giản hóa và triệt tiêu cả họ lỗi cờ kiểu H3.
- **O4:** dashboard overview + `_require_guild_access` mỗi request có thể re-fetch guild Discord theo TTL; nên dùng lại kết quả đã refresh trong cùng phiên poll để giảm API call khi bot tải cao.
- **O5:** 3 block `requests.post` trùng lặp trong `scripts/dual_model_mcp.py` (3 tier) — gom vào 1 helper để chống drift giữa các chuỗi fallback.

---

## 6. Câu hỏi cần quyết định trước khi code

1. **Retry policy cho reminder:** retry vô hạn (risk: row kẹt quét mãi mỗi 60s) **hay xóa sau 3 lần thử + log (khuyến nghị)**?
2. **Retention `economy_transactions`:** prune 365 ngày (mất lịch sử xa hơn) hay giữ vĩnh viễn và chấp nhận phình?
3. **Phạm vi:** làm cả 5 phase, hay chỉ Phase 1–3 (3 HIGH + data growth) trước?
4. **Cadence deploy:** `termux_deploy` + verify trên device sau **mỗi** phase, hay gộp một đợt cuối?

---

*File production **không bị sửa** trong quá trình audit. Chỉ thêm các probe dùng-one-run dưới `scratch/`: `audit_db_probe.py`, `audit_routes.py`, `audit_repro_remind.py`, `audit_repro_player_skip.py`, `routes.txt` — có thể xóa hoặc giữ lại làm hạt giống regression test sau khi duyệt kế hoạch.*

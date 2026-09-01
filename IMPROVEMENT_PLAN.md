# 📋 BÁO CÁO ĐÁNH GIÁ & KẾ HOẠCH CẢI THIỆN — ZerynBot

> Ngày kiểm tra: 2026-09-01 · Branch: `arena/01a05b79-zerynbot` · Commit: `424dbe6`
>
> ⚠️ **LƯU Ý**: File này liệt kê các lỗ hổng bảo mật của dự án. **Nên hoàn thành Phase 1 (vá bảo mật)
> trước khi repo public**, hoặc giữ file này ở chế độ private/internal (thêm vào `.gitignore` cho
> tới khi vá xong).

---

## 1. Đánh Giá Tổng Quan

| Tiêu chí | Điểm | Ghi chú |
|---|---|---|
| Tính hoàn chỉnh chức năng | 8.5/10 | 21/21 cogs load thành công, 85 lệnh slash top-level (111 kể cả subcommand) |
| Khả năng build/cài đặt | ✅ | `requirements.txt` cài sạch trên Python 3.11, mọi file compile OK |
| Bảo mật | ⚠️ 5/10 | Có **3 lỗ hổng Critical** + 1 lỗ hổng High cần vá ngay |
| Kiểm thử | 4/10 | Chỉ có runtime self-diagnostic, **không có unit test** |
| CI/CD | 0/10 | Không có `.github/workflows` |
| Chất lượng code | 6.5/10 | 2 "god file" >2400 dòng, 201/242 except-clause là broad `Exception` |
| Tài liệu | 7.5/10 | README đẹp & chi tiết nhưng số liệu "trang trí" đã lệch sự thật |

**Kết luận**: Repo **ở trạng thái tốt về mặt chức năng** — code chạy được, kiến trúc hợp lý
(3 lớp bảo vệ uptime, in-memory cache, i18n chuẩn), nhưng **CHƯA an toàn để vận hành công khai**
vì các lỗ hổng bảo mật dashboard, và thiếu hạ tầng quy trình (tests, CI, LICENSE) của một
dự án open-source chuyên nghiệp.

---

## 2. Những Gì Đang Làm TỐT (giữ nguyên)

1. ✅ Toàn bộ 16 file Python + 21 cogs **compile & load sạch**, không lỗi import.
2. ✅ SQL dùng **parameterized queries** nhất quán — không phát hiện SQL injection.
3. ✅ i18n tốt: 6 ngôn ngữ × **1510 keys khớp 100%**, placeholder `{var}` thống nhất giữa các file.
4. ✅ **Không lộ secret/token** trong git history hay source code; `.gitignore` chặn `.env`, `data/`, `*.db`.
5. ✅ `.env.example` rõ ràng, có chú thích từng biến.
6. ✅ Kiến trúc tự phục hồi 3 lớp (bot watchdog → `watchdog.sh` health-check → Termux:Boot) rất chu đáo.
7. ✅ Web Terminal đã chặn lệnh TTY tương tác và giới hạn quyền Owner.
8. ✅ Database per-call connection + WAL mode + timeout 15s — pattern đúng cho SQLite.
9. ✅ Self-Diagnostic Tester chạy lúc boot giúp chẩn đoán môi trường (FFmpeg, DB, cache).
10. ✅ Giveaway có chống race-condition; health endpoint trả 503 đúng chuẩn.

---

## 3. Các Vấn Đề Cần Sửa (theo mức độ ưu tiên)

### 🔴 P0 — CRITICAL (bảo mật — vá trong 24–48h)

#### P0.1 · `FLASK_SECRET_KEY` fallback tĩnh → giả mạo session → RCE
- **File**: `config.py`
- **Hiện trạng**: `os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")`. Nếu người triển khai
  quên đổi, **bất kỳ ai** cũng có thể tự ký session cookie giả mạo `session["user"]["id"] = BOT_OWNER_ID`
  → vào `/admin/system/terminal` → **chạy lệnh shell tùy ý trên máy chủ (RCE)**.
- **Cách sửa**:
  ```python
  _secret = os.getenv("FLASK_SECRET_KEY", "").strip()
  if not _secret or _secret == "change_this_to_a_random_secret_key_32chars":
      import secrets
      _secret = secrets.token_hex(32)
      logging.getLogger("config").warning(
          "⚠️ FLASK_SECRET_KEY chưa cấu hình — dùng key ngẫu nhiên mỗi phiên "
          "(mọi user sẽ bị đăng xuất khi dashboard restart). Hãy đặt trong .env!"
      )
  FLASK_SECRET_KEY = _secret
  ```
- **Acceptance**: không còn chuỗi secret hardcode nào trong repo; boot không cần `.env` vẫn an toàn.

#### P0.2 · OAuth2 thiếu `state` parameter → Login CSRF
- **Files**: `dashboard/auth.py` (`get_oauth2_url`), `dashboard/app.py` (`callback`)
- **Hiện trạng**: không tạo/kiểm `state` → kẻ tấn công ép nạn nhân đăng nhập bằng tài khoản
  Discord của attacker (session fixation kiểu OAuth).
- **Cách sửa**: sinh `secrets.token_urlsafe(32)` lưu `session["oauth_state"]`, gắn vào URL;
  ở `/callback` so khớp `request.args["state"]` với session, sau đó `session.pop("oauth_state")`.

#### P0.3 · Route xóa dữ liệu chấp nhận method GET → CSRF thực sự
- **File**: `dashboard/app.py`
- **Hiện trạng**: các route `methods=["POST", "GET"]` thay đổi dữ liệu:
  - `/dashboard/<gid>/music/playlist/<id>/delete`
  - `/dashboard/<gid>/music/playlist/track/<id>/delete`
  - `/dashboard/<gid>/economy/delete_item/<id>`
- Kẻ tấn công chỉ cần nhúng `<img src="https://dashboard/…/delete">` hoặc lừa bấm link
  (cookie SameSite=Lax vẫn gửi kèm GET top-level) → xóa dữ liệu server nạn nhân.
- **Cách sửa**: đổi thành `methods=["POST"]` duy nhất; ở template chuyển `<a href=…delete>` thành
  `<form method="POST">`.

#### P0.4 · IDOR cross-server: `channel_id` không được kiểm thuộc Guild
- **File**: `dashboard/api.py` — `send_embed_to_channel`, `send_ticket_panel`,
  `send_reaction_role_panel`, `send_test_card`
- **Hiện trạng**: `_require_guild_access()` chỉ kiểm user có quyền với `guild_id` trong URL, nhưng
  `channel_id` lấy từ body được POST thẳng tới Discord API bằng bot token. Admin của server A
  có thể truyền channel_id của server B → **bot spam nhúng embed vào server người khác**.
- **Cách sửa**: trước khi gửi, verify channel nằm trong guild:
  ```python
  valid = {str(c["id"]) for c in db.get_guild_channels(guild_id)}
  if str(channel_id) not in valid:
      return jsonify({"error": "Channel không thuộc server này"}), 403
  ```

#### P0.5 · Thiếu CSRF token cho toàn bộ form Dashboard
- **Cách sửa**: tích hợp `flask-wtf` (`CSRFProtect(app)`) hoặc tự implement token trong session
  + hidden input `_csrf_token` cho mọi `<form method="POST">`.
- Mức rủi ro giảm nhiều sau khi sửa P0.3, nhưng vẫn nên có để defense-in-depth.

---

### 🟠 P1 — HIGH (hạ tầng bắt buộc — hoàn thành trong tuần đầu)

| # | Vấn đề | File/Vị trí | Hành động |
|---|---|---|---|
| P1.1 | **Thiếu file LICENSE** dù README tuyên bố MIT | root | Tạo `LICENSE` (MIT, năm 2025–2026, tên tác giả) |
| P1.2 | **Không có CI/CD** | `.github/workflows/` | Workflow `ci.yml`: Python 3.10–3.12, `ruff check`, smoke-load 21 cogs, và **tái sử dụng luôn 2 validator có sẵn trong `.agents/`** (`validate_all.py` — i18n parity + py_compile 37 file + đếm lệnh + đồng bộ số liệu docs; `validate_i18n.py` — flattened key parity) |
| P1.3 | **Không có unit test** | `tests/` | pytest: `test_cache.py` (TTL/eviction), `test_i18n.py` (parity + fallback), `test_database.py` (CRUD guilds/economy/levels), `test_oauth_security.py` (state, secret-key fail-closed). **Lợi thế: `E2E_TESTING.md` đã có sẵn mock session + 4 kịch bản** (module toggle, module 403 khi không có quyền, `/admin` chặn non-owner, Web Terminal) → chuyển thẳng thành Flask test-client tests |
| P1.4 | Flask **dev server** chạy production (single-thread) | `main.py`, `dashboard/app.py` | Dùng `waitress` (cross-platform Windows/Linux/Termux): `waitress.serve(app, host, port, threads=4)` |
| P1.5 | `requirements.txt` **chưa pin version** (`>=`) | requirements.txt | Sinh `requirements.lock` pin exact版本 + bật Dependabot cập nhật định kỳ |
| P1.6 | Không **rate limit** cho dashboard | Flask app | `flask-limiter`: 30 req/phút cho `/login`, `/callback`, `/admin/system/terminal`, các API POST |
| P1.7 | Session cookie chưa harden | `dashboard/app.py` | `SESSION_COOKIE_HTTPONLY=True`, `SAMESITE='Lax'`, `SECURE=True` khi HTTPS, `PERMANENT_SESSION_LIFETIME=timedelta(days=7)` |
| P1.8 | SSRF qua music search từ dashboard | `dashboard/app.py` (`fetch_track_info_simple`) | Chặn URL private IP/localhost/non-http(s) trước khi đưa cho yt-dlp |
| P1.9 | Session guild perms bị **cache cũ** | `_get_guild_from_session` | Re-verify `get_manageable_guilds` định kỳ (vd >15 phút) hoặc khi vào trang admin của từng server |

### 🟡 P2 — MEDIUM (chất lượng code — tuần 2–4)

| # | Vấn đề | Hành động |
|---|---|---|
| P2.1 | **God files**: `database.py` 2465 dòng, `dashboard/app.py` 2550 dòng, `music.py` 1562 dòng | Tách `db/guilds.py`, `db/economy.py`, `db/levels.py`, `db/tickets.py`…; dashboard tách Flask Blueprints theo module (`routes/moderation.py`, `routes/economy.py`…) |
| P2.2 | **201/242 except là broad `Exception`** → lỗi thật bị nuốt | Audit dần theo module, catch exception cụ thể (`sqlite3.Error`, `aiohttp.ClientError`, `discord.HTTPException`), log kèm `exc_info` |
| P2.3 | `main.py --sync` append thừa vào `sys.argv` (dòng duplicate) | Xóa `sys.argv.append("--sync")` vì flag đã có sẵn |
| P2.4 | `bot.py on_ready`: `sum(g.member_count for g in self.guilds)` — `member_count` có thể `None` trên guild chưa chunk → crash presence loop | Đổi thành `sum((g.member_count or 0) for g in self.guilds)` |
| P2.5 | **Số liệu tài liệu lệch nhau giữa 4 nguồn**: README badge "1509 keys" & "88 commands" (thực tế i18n **1510 keys** — validator xác nhận; bot tree **85 top-level** slash + 2 lệnh owner prefix-only = `_COMMANDS_DATA` **87**); E2E_TESTING.md ghi "**57 lệnh**"; ARCHITECTURE.md vẫn nhắc "clear **Redis** cache" dù đã bỏ Redis và mô tả decorators/routes cũ | ✅ Đã chuẩn hóa: README (1510 keys / 87 lệnh), E2E (87 lệnh, đường dẫn `/dashboard/...`), ARCHITECTURE (bỏ Redis, đúng tên decorator + route). Còn lại: script `gen_repo_stats.py` tự sinh số liệu (nice-to-have) |
| P2.6 | `.env.example` **thiếu `GEMINI_API_KEY`** dù `config.py` đọc biến đó; README env mẫu thiếu `DEV_GUILD_ID`, `BACKUP_DB` | Đồng bộ 3 nơi: `.env.example`, README, `config.py` |
| P2.7 | README thiếu hướng dẫn bật **Privileged Intents** (Presences / Members / Message Content) trong Discord Developer Portal — thiếu là bot không login được | Thêm mục "2.5 Cấu hình Intents" kèm ảnh chụp màn hình |
| P2.8 | Dashboard lỗi không có file log riêng | Thêm `RotatingFileHandler` cho Flask app giống `bot/bot.py` |
| P2.9 | **Lộ đường dẫn máy cá nhân trong file public** (phát hiện sau khi user push `.agents/` + tài liệu): `ARCHITECTURE.md` ghi cây thư mục `d:/Project/Discord Bots/v2/`; `.agents/AGENTS.md`, `doc_sync.md`, `security_and_api_rules.md` chứa link `file:///d:/Project/Discord%20Bots/v2/...` (vừa lộ path vừa là link hỏng với người khác); `scripts/termux_boot.sh` hardcode `/storage/emulated/0/Project/Discord Bots/v2` | Thay tất cả bằng đường dẫn tương đối/biến môi trường (`ZERYN_HOME`); link tài liệu đổi sang relative path (`./ARCHITECTURE.md`) |
| P2.10 | **`dashboard/commands_data.py` là dead code** (117 dòng, không file nào import; dữ liệu thật nằm ở `_COMMANDS_DATA` trong `app.py` + `commands_catalog.py`) | Xóa file hoặc hợp nhất, tránh 2 nguồn dữ liệu lệch nhau |

### 🟢 P3 — LOW / Enhancement (tháng 2 trở đi)

1. **Formatter & lint**: thêm `ruff` (+ config `pyproject.toml`), pre-commit hooks (ruff, detect-secrets, trailing-whitespace).
2. **Typing**: bật `mypy --strict` từng module một, bắt đầu với `cache.py`, `i18n.py`, `config.py`.
3. **Docker**: `Dockerfile` + `docker-compose.yml` (bot + dashboard + volume `data/`) cho người dùng VPS.
4. **GitHub hygiene**: `SECURITY.md` (hướng dẫn báo cáo lỗ hổng), `CONTRIBUTING.md`, issue/PR templates, topics (`discord-bot`, `flask`, `termux`), description + website URL.
5. **i18n regression CI**: script kiểm parity keys + placeholder mismatch chạy trên mọi PR.
6. **Health/Metrics endpoint mở rộng**: uptime, số guild, queue nhạc, DB size (cho dashboard `/admin`).
7. **E2E test nhẹ**: pytest + Flask test client cho các route critical (`/health`, `/login` redirect…).
8. Gắn tag **release** (`v2.x.y`) + GitHub Releases kèm changelog.

---

## 4. Lộ Trình Triển Khai (Timeline)

### 🗓️ Tuần 1 — "Đóng cửa chợ" (Security Hotfix)
| Ngày | Việc | Nhóm |
|---|---|---|
| 1–2 | P0.1 secret key fail-closed · P0.2 OAuth state · P0.3 xóa GET-delete routes · P0.4 channel IDOR check | P0 |
| 3 | P0.5 CSRF token (flask-wtf) + P1.6 rate limit + P1.7 cookie hardening | P0/P1 |
| 4 | P1.4 waitress · P1.5 pin requirements + Dependabot | P1 |
| 5 | P1.1 LICENSE · P1.2 CI workflow đầu tiên · review & release `v2.0.1-security` | P1 |

**Tiêu chí hoàn thành tuần 1**: không còn secret mặc định; OAuth có state; mọi mutation đều POST + CSRF token; CI xanh; dashboard chạy qua waitress.

### 🗓️ Tuần 2 — "Đặt nền móng"
- P1.3 viết pytest cho `cache.py`, `i18n.py`, `database.py` (target coverage > 50% cho 3 file lõi).
- P1.8 chặn SSRF music. P1.9 refresh guild session.
- P2.3 → P2.6 (docs/params dễ).

### 🗓️ Tuần 3–4 — "Dọn nhà"
- P2.1 refactor god files theo từng PR nhỏ (db trước, dashboard sau) — mỗi PR phải giữ CI xanh.
- P2.2 audit except theo module; P2.7 docs intents; P2.8 logging dashboard.

### 🗓️ Tháng 2 — "Nâng cấp trải nghiệm"
- Toàn bộ P3: ruff/mypy/pre-commit, Docker, SECURITY.md, templates, release pipeline.

---

## 5. Đề Xuất Cấu Trúc Mới Sau Refactor (tham khảo)

```text
ZerynBot/
├── .github/workflows/ci.yml       # lint + tests + i18n parity
├── tests/                         # pytest (db, i18n, cache, security)
├── db/                            # tách từ database.py
│   ├── __init__.py  ├── guilds.py ├── economy.py
│   ├── levels.py    ├── tickets.py└── automod.py
├── dashboard/
│   ├── routes/                    # tách Blueprints từ app.py
│   │   ├── auth.py  ├── admin.py  ├── moderation.py
│   │   ├── economy.py└── ...
│   └── app.py                     # chỉ còn app factory + blueprint registry
├── scripts/
│   ├── gen_repo_stats.py          # tự động đếm lệnh/keys → chèn README
│   └── check_locales.py           # CI: i18n parity
├── LICENSE                        # MIT
├── SECURITY.md  CONTRIBUTING.md
├── Dockerfile  docker-compose.yml
└── requirements.lock              # pinned
```

---

## 6. Công Cụ Đề Xuất Thêm (goes to requirements-dev.txt)

```
pytest>=8.0       # unit tests
pytest-asyncio>=0.23
ruff>=0.6         # lint + format (thay black/flake8/isort)
flask-wtf>=1.2    # CSRF
flask-limiter>=3.0# rate limiting
waitress>=3.0     # production WSGI (Termux-friendly)
mypy>=1.10        # typing (optional, từng bước)
pre-commit>=3.7
```

---

---

## ✅ Trạng Thái Triển Khai — Sprint 1 (2026-09-01, branch `arena/01a05b79-zerynbot`)

**ĐÃ SỬA XONG (27 mục)** — mọi thay đổi đã qua `pytest` (55/55 ✔), `validate_all.py` (4/4 ✔),
`ruff --select E9,F63,F7,F82` (0 lỗi ✔):

| Trạng thái | Mục | Chi tiết commit |
|---|---|---|
| ✅ | P0.1 | `config.py`: secret key fail-closed, random 64-hex khi thiếu + cảnh báo lớn qua `warnings` |
| ✅ | P0.2 | `auth.py` + `app.py`: OAuth `state` bắt buộc (pop-once, `compare_digest`) |
| ✅ | P0.3 | 5 route delete (music playlist/track, economy item, tempvoice channel, custom command) → **POST-only**; `music.html` chuyển link `<a>` → `<form method=POST>` |
| ✅ | P0.4 | `auth.channel_belongs_to_guild` (Discord REST + cache 5 phút, fail-closed) gác 4 endpoint gửi tin trong `api.py`; `_safe_channel()` gác toàn bộ form lưu channel_id trong `app.py`; thêm guild-scope cho music track delete & tempvoice channel delete |
| ✅ | P0.5 | CSRF tự quản: `before_request` + token per-session + `_csrf_bootstrap.html` (auto-inject vào fetch + form POST) cho mọi trang |
| ✅ | P1.1 | `LICENSE` MIT |
| ✅ | P1.2 | `.github/workflows/ci.yml` (py3.10–3.12: validators + ruff fatal + pytest) |
| ✅ | P1.3 | `tests/` — 55 tests (cache/i18n/database/bảo mật dashboard/smoke 22 cogs) bám theo kịch bản `E2E_TESTING.md` |
| ✅ | P1.4 | `main.py` chạy Waitress (4 threads), fallback Flask dev kèm cảnh báo |
| ✅ | P1.5 | `requirements.txt` pin `==` toàn bộ + `requirements-dev.txt` + Dependabot |
| ✅ | P1.6 | Flask-Limiter: `/login` 20/m, `/callback` 30/m, terminal 30/m, git-pull 5/m, restart 10/m |
| ✅ | P1.7 | Cookie HttpOnly + SameSite=Lax + Secure(auto theo https) + session 7 ngày; `BEHIND_PROXY` bật ProxyFix tường minh |
| ✅ | P1.8 | `is_safe_http_url()` chặn IP private/localhost/metadata — áp cho bg_url card & music search dashboard |
| ✅ | P1.9 | Guild session tự refresh mỗi 15 phút (token Discord bị thu hồi → tự đăng xuất) |
| ✅ | P2.3, P2.4 | Bỏ `--sync` append thừa; `member_count or 0` |
| ✅ | P2.5 | Đồng bộ số liệu 1510 keys / 87 lệnh xuyên suốt README+E2E+ARCHITECTURE |
| ✅ | P2.6 | `.env.example` + README: thêm `GEMINI_API_KEY`, `DEV_GUILD_ID`, `BACKUP_DB` + hướng dẫn Privileged Intents (P2.7 phần docs) |
| ✅ | P2.9 | Scrub `d:/Project/...` trong ARCHITECTURE.md; 4 file `.agents` đổi link `file:///d:/...` → URL GitHub; `termux_boot.sh` dùng `$ZERYN_HOME` |
| ✅ | P2.10 | Xóa dead code `dashboard/commands_data.py` |
| ✅ | Bonus | Fix NameError `_req`→`requests` trong `api.py` (luôn lỗi ngầm); `import sqlite3` thiếu trong `app.py` (route tempvoice delete 500); template mẫu `.agents` dùng sai `false/true`; annotation `"Image"` lơ lửng |

**CÒN LẠI** (theo lộ trình): P2.1 (tách god files), P2.2 (audit 201 broad except), P2.8 (dashboard file log),
`gen_repo_stats.py`, và toàn bộ P3 (Docker, SECURITY.md, mypy, E2E browser test thật).
**Lưu ý vận hành**: nếu `.env` thật của bạn chưa có `FLASK_SECRET_KEY` → sau khi deploy bản này,
mọi phiên đăng nhập dashboard sẽ bị reset mỗi lần restart; hãy đặt key cố định trong `.env`.

---

*Báo cáo được tạo tự động bằng cách: compile toàn bộ mã nguồn, cài dependencies trong venv sạch,
load smoke-test 22/22 cogs, đếm slash commands (85 top-level), kiểm i18n parity (1510×6, 0 mismatch),
rà Git history tìm secret bị lộ, và review bảo mật toàn bộ route dashboard.*

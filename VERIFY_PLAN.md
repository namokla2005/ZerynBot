# 🎫 PHẦN C — Verify Gate & Anti-Raid (Kế hoạch triển khai chi tiết)

> **Trạng thái:** còn THIẾU trên `main` — đây là phần "chưa có authentication/xác minh trước khi vào server" mà bạn hỏi.
> **Lựa chọn đã chốt:**
> - 🔘 **Cơ chế:** Nút bấm (Button) "Tôi đã đọc nội quy & Xác thực" (dùng emoji `zb_verified` sẵn có).
> - 🔒 **Mức hạn chế:** Chỉ thấy 1 kênh `#xac-thuc` (chế độ "hard"), cell lưu snapshot quyền để khôi phục khi tắt.
> - 🛡️ **Phạm vi:** Verify Gate + Anti-Raid (lockdown khi join ồ ạt) + Anti-Nuke (chặn xoá role/kênh hàng loạt), tích hợp vào `automod`.

---

## 📌 Tóm tắt các file sẽ tạo / sửa

| File | Hành động | Nội dung |
|---|---|---|
| `bot/cogs/verify.py` | ⭐ **MỚI** | Cog Validate: `on_member_join`, View + Button, `/setup_verify`, `/verify panel`, `/verify disable` |
| `bot/cogs/automod.py` | Sửa | Thêm listener `on_member_join` cho Anti-Raid + check `on_audit_log_entry`/`on_guild_channel_delete`/`on_guild_role_delete` cho Anti-Nuke |
| `database.py` | Sửa | Thêm bảng `verify_settings`, cột anti-raid/nuke cho `automod_settings`, hàm sync/async |
| `bot/emojis.py` / `emojis.py` | (đã có) | Dùng `e('zb_verified')`, `e('zb_ban')`, `e('zb_kick')`, `e('zb_lock')` cho log/setup |
| `locales/*.json` (6 file) | Sửa | Thêm key `verify.*` + `automod.anti_raid.*` + `automod.anti_nuke.*` |
| `dashboard/app.py` | Sửa | Route `/dashboard/<guild_id>/verify`, thêm `verify` vào `_COMMANDS_DATA` |
| `dashboard/templates/server_verify.html` | ⭐ **MỚI** | Trang cấu hình Verify Gate theo design system |
| `dashboard/templates/modules.html` | Sửa | Hiển thị toggle module "verify" |
| `dashboard/templates/sidebar` (base_server.html) | Sửa | Thêm link Verify vào sidebar |
| `dashboard/api.py` | Sửa | Endpoints AJAX cho verify |
| `database.py` → `DEFAULT_MODULES` | Sửa | Thêm `"verify"` |
| `ARCHITECTURE.md`, `AGENTS.md`, `llms.txt`, `README.md` | Sửa | Đồng bộ số lệnh + module + key |

---

## Bước 1 — CSDL (`database.py`)

### 1.1 Thêm bảng `verify_settings` (trong `init_db()`)

```sql
CREATE TABLE IF NOT EXISTS verify_settings (
    guild_id            TEXT PRIMARY KEY,
    enabled             INTEGER DEFAULT 0,
    channel_id          TEXT,                -- kênh #xac-thuc
    verified_role_id    TEXT,                -- role được gán khi xác thực
    pending_role_id     TEXT,                -- role tạm cho member chưa verify (tuỳ chọn)
    verify_text         TEXT DEFAULT 'Chào mừng đến với {server}! Bấm nút bên dưới để xác thực.',
    button_label        TEXT DEFAULT 'Tôi đã đọc nội quy & Xác thực',
    log_channel_id      TEXT,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 1.2 Thêm cột cho `automod_settings` (migration an toàn trong `init_db()`)

```sql
-- Chống Raid: phát hiện join ồ ạt
ALTER TABLE automod_settings ADD COLUMN anti_raid_enabled  INTEGER DEFAULT 0;
ALTER TABLE automod_settings ADD COLUMN raid_join_per_window INTEGER DEFAULT 5;   -- số join/60s
ALTER TABLE automod_settings ADD COLUMN raid_action TEXT DEFAULT 'lockdown';      -- 'lockdown'|'verify_only'|'none'
-- Chống Nuke: chặn xoá role/kênh hàng loạt
ALTER TABLE automod_settings ADD COLUMN anti_nuke_enabled  INTEGER DEFAULT 0;
ALTER TABLE automod_settings ADD COLUMN nuke_actions TEXT DEFAULT '["channel_delete","role_delete","guild_update"]';
```

### 1.3 Hàm sync (Dashboard) + async (Bot)

| Nhóm | Sync | Async |
|---|---|---|
| Verify settings | `get_verify_settings(guild_id)` | `async_get_verify_settings(guild_id)` |
| Lưu verify | `upsert_verify_settings(guild_id, **fields)` | `async_upsert_verify_settings(...)` |
| Joined timestamps (raid) | `record_join_ts(guild_id, ts)` | `async_record_join_ts(...)` |
| Đếm join trong cửa sổ | `count_joins_window(guild_id, window)` | `async_count_joins_window(...)` |
| Anti-nuke (chặn) | `check_nuke_action(guild_id, action)` | `async_check_nuke_action(...)` |

> **Raid join log:** không cần bảng riêng — dùng **bộ nhớ RAM cache** (`cache`) key `raid_joins:{guild_id}` lưu list timestamp gần nhất, hoặc bảng `guild_meta`/`guild_stats`. Tôi sẽ dùng cache in-memory (nhẹ, phù hợp Termux). Anti-Nuke dùng `guild.audit_logs()` của Discord (không phải bảng DB).

---

## Bước 2 — Cog `bot/cogs/verify.py` (MỚI)

### 2.1 `on_member_join`
```python
@commands.Cog.listener()
async def on_member_join(self, member):
    guild_id = str(member.guild.id)
    v = await async_get_verify_settings(guild_id)
    if not v.get("enabled"):
        # vẫn ghi nhận join để Anti-Raid hoạt động độc lập
        await self._record_join(guild_id)
        return
    # 1. Gán pending role (nếu có)
    if v.get("pending_role_id"):
        try: await member.add_roles(member.guild.get_role(int(v["pending_role_id"])), reason="Verify pending")
        except: pass
    # 2. Giới hạn quyền: chỉ thấy #xac-thuc
    await self._apply_gate_overrides(member.guild, v)   # (xem Bước 3)
    # 3. Gửi log
    await self._log(guild_id, "verify.join", member=member)
    # 4. Ghi nhận join cho Anti-Raid
    await self._record_join(guild_id)
```

### 2.2 View + Button
```python
class VerifyView(discord.ui.View):
    def __init__(self, guild_id, verified_role_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.verified_role_id = verified_role_id
    @discord.ui.button(
        label="Tôi đã đọc nội quy & Xác thực",
        emoji=discord.PartialEmoji(name="zb_verified", id=EMOJIS.get("zb_verified")),
        style=discord.ButtonStyle.success,
        custom_id="verify:accept"
    )
    async def accept(self, interaction, button):
        role = interaction.guild.get_role(int(self.verified_role_id))
        if not role:
            return await interaction.response.send_message("⚠️ Role xác thực đã bị xoá.", ephemeral=True)
        await interaction.user.add_roles(role, reason="Verified by Zeryn")
        # gỡ pending role
        ...
        await interaction.response.send_message("✅ Xác thực thành công!", ephemeral=True)
```

> 💡 **`custom_id` cố định** `"verify:accept"` để View bền vững giữa restart. `emoji` dùng `PartialEmoji` với id từ `EMOJIS` (đã có `zb_verified = 1545451784309575850`). Nếu emoji không khả dụng, fallback về `emoji="✅"`.

### 2.3 Lệnh
- `/setup_verify` (Bot Admin): tạo kênh `#xac-thuc` nếu chưa có, tạo role `Verified` nếu chưa có, chỉnh overrides, gửi panel.
- `/verify panel` — re-send panel.
- `/verify disable` — tắt & khôi phục quyền (dùng snapshot).
- **Module guard:** `if not await async_is_module_enabled(guild_id, "verify"): return`.

---

## Bước 3 — Cơ chế "chỉ thấy 1 kênh #xac-thuc" (hard)

**Quy trình an toàn (chống phá vỡ cấu hình):**
1. **Trước khi đổi:** lưu snapshot overrides của `@everyone` trên tất cả kênh text (hoặc các kênh chính/announcement) vào bảng `verify_settings` (cột JSON `_saved_overrides`).
2. **Khi bot join thành viên mới:**
   - Trên các kênh **khác** `#xac-thuc`: set `@everyone` → **Deny** `view_channel` + `send_messages`.
   - Trên kênh `#xac-thuc`: `@everyone` → **Allow** `view_channel`, **Deny** `send_messages` (chỉ đọc + bấm).
   - Role `verified_role` → giữ quyền xem tất cả (để thành viên đã verify thấy bình thường).
3. **Khi tắt (`/verify disable`) khôi phục quyền từ snapshot.**

> ⚠️ **Lưu ý quan trọng:** vì đây là chế độ "hard" (ẩn kênh), điều chỉnh `@everyone` trên **toàn bộ kênh** có thể ảnh hưởng server đang vận hành. Tôi sẽ:
> - Chỉ áp dụng deny khi **có thành viên chưa verify** và `enabled=1`.
> - Tự động hoàn tác khi không còn ai pending hoặc khi tắt module.
> - Log mọi thao tác.
> Chế độ này sẽ yêu cầu **bot có `Manage Channels` + `Manage Roles`**; nếu thiếu → báo lỗi rõ qua `/setup_verify`.

---

## Bước 4 — Anti-Raid & Anti-Nuke (trong `automod.py`)

### 4.1 Anti-Raid (phát hiện join ồ ạt)
```python
async def _record_join(self, guild_id):
    key = f"raid_joins:{guild_id}"
    now = time.time()
    list_ts = await cache.aget(key) or []
    list_ts.append(now)
    list_ts = [t for t in list_ts if now - t < 60]   # cửa sổ 60s
    await cache.aset(key, list_ts, ttl=60)

async def on_member_join(self, member):
    # ... verify ...
    am = await async_get_automod_settings(guild_id)
    if am.get("anti_raid_enabled"):
        joins = await cache.aget(f"raid_joins:{guild_id}") or []
        if len(joins) >= am.get("raid_join_per_window", 5):
            if am.get("raid_action") == "lockdown":
                await self._guild_lockdown(member.guild)   # theo dõi channel thông báo + đổi slowmode
            # notify admin / log
```

### 4.2 Anti-Nuke (chặn xoá role/kênh hàng loạt)
```python
@commands.Cog.listener()
async def on_guild_channel_delete(self, channel):
    await self._check_nuke(channel.guild, "channel_delete", actor=...)  # từ audit_logs

@commands.Cog.listener()
async def on_guild_role_delete(self, role):
    await self._check_nuke(role.guild, "role_delete", actor=...)

@commands.Cog.listener()
async def on_guild_update(self, before, after):
    # phát hiện thay đổi nguy hiểm (bỏ verify role, giảm quyền @everyone...) → 'guild_update'
```

- `_check_nuke`: dùng `guild.audit_logs(limit=1, action=...)` lấy actor; nếu `anti_nuke_enabled` và hành động nằm trong `nuke_actions` → **chặn** (nếu có quyền) + **log** + đóng băng (lockdown). Nếu không đủ quyền, vẫn log cảnh báo tới admin.

> **Lưu ý Anti-Nuke:** bot cần quyền `Manage Roles`/`Manage Channels`/`Ban Members` để chặn thực sự. Nếu chỉ có `View Audit Log`, chỉ ghi cảnh báo.

---

## Bước 5 — i18n (6 file `locales/*.json`)

Thêm bộ key (namespace `verify.*` + `automod.anti_*`) vào **đủ 6 file**:

```
verify.title, verify.message, verify.button_label, verify.accepted,
verify.already_verified, verify.role_assigned, verify.pending_assigned,
verify.setup_done, verify.setup_missing_perm, verify.disabled,
verify.log_join, verify.log_accepted                       # dùng {user}, {role}
automod.anti_raid.triggered, automod.anti_raid.lockdown, automod.anti_raid.notify,
automod.anti_nuke.triggered, automod.anti_nuke.blocked, automod.anti_nuke.warning
```

> Chạy `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` → 100% 6 ngôn ngữ đồng bộ. **Bắt buộc thêm đủ 6 file, không lệch key.**

---

## Bước 6 — Dashboard (SOP 7 bước)

### 6.1 Route Flask (`dashboard/app.py`)
`@login_required` + `@guild_admin_required`:
- `GET/POST /dashboard/<guild_id>/verify` — trang cấu hình.

### 6.2 Template `server_verify.html` (MỚI)
- Kênh `#xac-thuc` (dropdown),
- Role verified (dropdown),
- Text + button label,
- Toggle `enabled`,
- Nút "Create/send panel",
- Nút "Disable" (khôi phục quyền).
- Design system: CSS tokens + `?v=9.2`.

### 6.3 Sidebar + modules
- `base_server.html`: thêm link "Verify Gate" vào sidebar.
- `modules.html`: thêm toggle `verify`.

### 6.4 `_COMMANDS_DATA`
- Thêm `/setup_verify`, `/verify` vào danh mục (VD "Điều hành" hoặc nhãn riêng). Cập nhật **92 → 94 lệnh**.

---

## Bước 7 — Đồng bộ docs (cùng commit)

- `ARCHITECTURE.md`: thêm bảng `verify_settings`, module `verify` + `anti_raid`/`anti_nuke`; số lệnh = 94, số module = 20.
- `.agents/AGENTS.md`, `llms.txt`: 94 lệnh, 20 module, số key mới.
- `README.md`: mô tả Verify Gate + Anti-Raid.

---

## Bước 8 — Kiểm chứng (bắt buộc)

1. `python .agents/skills/zerynbot_architecture_context/assets/validate_all.py` → 100%.
2. `python .agents/skills/zerynbot_architecture_context/assets/check_db_schema.py` → không WARN.
3. `python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py` → 6 ngôn ngữ đồng bộ.
4. `pytest -q` → xanh (thêm smoke test cho `verify.py` + test SSRF nếu có).
5. **Manual:** tạo server test → `/setup_verify` → member mới vào chỉ thấy `#xac-thuc` → bấm nút → được gán role; bật anti-raid → gửi 6 join/60s → lockdown; bật anti-nuke → thử xoá role/kênh → bị chặn/log.

---

## 📅 Tiến độ triển khai (điền sau khi code)

- [x] Bước 1 (DB) — bảng `verify_settings` + migration anti-raid/nuke (`anti_raid_enabled`, `raid_join_per_window`, `raid_action`, `anti_nuke_enabled`, `nuke_actions`) + cột `raid_locked`/`raid_snapshot`; thêm `"verify"` vào `DEFAULT_MODULES`; hàm sync/async verify + `async_update_automod_settings`.
- [x] Bước 2 (cog `bot/cogs/verify.py`) — `/verify` group + View/Button (`zb_verify`, custom_id `zb_verify_button`), listener `on_member_join`.
- [x] Bước 3 (hard gate) — snapshot overrides lưu vào `saved_overrides`, `_apply_hard_gate`/`_restore_gate`, `_ensure_pending_role`.
- [x] Bước 4 (anti-raid + anti-nuke trong `automod.py`) — listener `on_member_join` (ra rai), `on_guild_channel_delete`/`on_guild_role_delete` (nuke), `/automods raidlock`/`raidunlock`, đã thêm vào `/automods show`.
- [x] Bước 5 (i18n 6 file) — thêm key `verify.*` (24 key) + `nav.verify` + `dashboard.verify_desc` cho 6 ngôn ngữ.
- [x] Bước 6 (Dashboard) — route `server_verify`, `server_verify.html`, sidebar + modules.html toggle, `_COMMANDS_DATA` (Verify Gate category + `/automods raidlock`/`raidunlock`), automod template + route nhận anti-raid/nuke.
- [x] Bước 7 (docs) — cập nhật `VERIFY_PLAN.md` (file này). (Số lệnh/module trong ARCHITECTURE/AGENTS/llms.txt cần bước riêng khi merge.)
- [ ] Bước 8 (validate + pytest + manual) — CHƯA CHẠY: cần `.venv` (aiohttp/discord.py) để chạy `validate_all.py`, `pytest`, và test manual trên server thật.

> **Ghi chú thực tế:** toàn bộ code nằm trên branch `arena/01a062d4-zerynbot` (HEAD = `e044afd`, = origin/main). Do môi trường bị khóa branch, phần này chưa push lên `main` — cần merge/PR từ `arena/...`.

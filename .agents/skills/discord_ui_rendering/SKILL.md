---
name: discord_ui_rendering
description: >
  Guidelines and best practices for Discord Embeds, Pillow dynamic card generation
  (Rank Cards, Welcome Banners), and interactive Discord UI Components (Views, Modals, Selects).
---

# Skill: Discord UI Design & Card Rendering

## 🎯 1. Mục Đích & Phạm Vi

Tài liệu này chuẩn hóa toàn bộ trải nghiệm thị giác (Visual UX) của ZerynBot trên Discord:
1. **Dynamic Image Cards** (Pillow / PIL)
2. **Rich Localized Embeds**
3. **Interactive Components** (Buttons, Select Menus, Modals)

---

## 🖼️ 2. Quy Chuẩn Sinh Ảnh Bằng Pillow (`card_generator.py`)

> [!IMPORTANT]
> **Quy Tắc Vàng: KHÔNG NGHẼN EVENT LOOP**:
> Các tác vụ đọc ảnh qua HTTP (avatar người dùng), giải nén, bo góc tròn, vẽ text bằng Pillow là các tác vụ đồng bộ nặng (CPU-bound / I/O-bound).
> **BẮT BUỘC** phải bọc hàm sinh ảnh trong thread pool bằng `asyncio.to_thread` hoặc `run_in_executor`:
> ```python
> image_bytes = await asyncio.to_thread(generate_rank_card, member_name, avatar_bytes, level, xp, rank)
> file = discord.File(fp=io.BytesIO(image_bytes), filename="rank.png")
> await ctx.send(file=file)
> ```

### 2.1 Các Loại Card Trong Hệ Thống:
- 🏆 **Rank Card (Thẻ Cấp Độ)**:
  - Tỷ lệ: 934 x 282px
  - Nền: Dark Violet Gradient (`#120e24` ➔ `#1d1538`)
  - Thanh tiến trình XP bo tròn phát sáng (Sakura Pink `#f4a7bb` hoặc Blurple `#5865f2`)
  - Avatar bo tròn kèm viền phát sáng (Glow border)
- 🌸 **Welcome & Goodbye Banner**:
  - Tỷ lệ: 1024 x 500px
  - Chữ chào mừng/tạm biệt phân tầng sắc nét, tên thành viên và số thứ tự server.

---

## 🎨 3. Tiêu Chuẩn Thiết Kế Discord Embed (Midnight Obsidian)

Mọi Embed gửi trong Discord phải tuân theo bảng mã màu thống nhất:

| Mục đích | Mã màu Hex | Ý nghĩa |
|:---|:---|:---|
| **Thương hiệu / Thông tin chung** | `0x5865F2` / `0x9D8DF1` | Discord Blurple / Royal Violet |
| **Thành công / Xác nhận** | `0x57F287` | Emerald Green |
| **Cảnh báo / Nhắc nhở** | `0xFEE75C` | Amber Gold |
| **Lỗi / Xử phạt / Bị phạt** | `0xED4245` | Crimson Red |
| **Âm nhạc / Mini-games** | `0xF4A7BB` | Sakura Pink |
| **Giveaway & Sự kiện** | `0x2F3136` / `0x120E24` | Dark Obsidian Slate |

### 3.1 Quy Tắc Định Dạng Văn Bản Trong Embed
- Dùng `**In đậm**` cho tiêu đề trường (Field title).
- Dùng `` `code block` `` cho giá trị ngắn (ID, số tiền, ping, prefix).
- Sử dụng Emoji trực quan ở đầu mỗi dòng.
- Luôn đặt `timestamp=datetime.now(timezone.utc)` và `embed.set_footer()` hiển thị người thực hiện lệnh.

---

## 🔘 4. Kiến Trúc Interactive UI Components (`discord.ui`)

### 4.1 Persistent Views (Nút bấm không mất tác dụng khi bot restart)
- Luôn truyền `timeout=None` vào class kế thừa `discord.ui.View`.
- Mọi nút bấm hoặc dropdown phải có `custom_id` tĩnh, không đổi (ví dụ: `custom_id="ticket:create:support"`).
- Đăng ký view tĩnh trong sự kiện `on_ready()` hoặc `setup_hook()` của `bot.py`:
  ```python
  self.add_view(DynamicTicketView())
  self.add_view(ReactionRoleView())
  ```

### 4.2 Temporary Views (Hết hạn sau thời gian nhất định)
- Đặt `timeout=60` hoặc `timeout=120`.
- Override hàm `on_timeout()` để tự động làm mờ (disable) các nút bấm, tránh lỗi `Interaction Failed`:
  ```python
  async def on_timeout(self):
      for child in self.children:
          child.disabled = True
      if self.message:
          try:
              await self.message.edit(view=self)
          except Exception:
              pass
  ```

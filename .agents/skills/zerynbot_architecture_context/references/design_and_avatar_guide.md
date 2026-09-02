# 🎨 Hướng Dẫn Thiết Kế Web & Quy Chuẩn Tạo Avatar Mascot Zeryn

Tài liệu này cung cấp các tiêu chuẩn thiết kế giao diện Web Dashboard và quy tắc tạo ảnh đại diện (Avatar / Mascot) chuẩn nhận diện thương hiệu cho **ZerynBot V2**.

---

## 🌐 1. Hệ Thống Thiết Kế Giao Diện Web (Web Design System)

Giao diện Web Dashboard tuân thủ triết lý thiết kế **Midnight Obsidian Glassmorphism**:

### 1.1 Bảng Màu Cốt Lõi (Color Palette)
- **Nền chính (Obsidian Dark Background)**: `#120e24` (Midnight Violet Slate) kết hợp `#131217`.
- **Bề mặt kính mờ (Glassmorphism Surface)**: `rgba(25, 24, 34, 0.85)` kèm hiệu ứng `backdrop-filter: blur(16px)`.
- **Màu nhấn thương hiệu (Brand Accents)**:
  - 🌸 **Sakura Pink**: `#f4a7bb` (Màu điểm xuyết, huy hiệu, nút chính).
  - 🔮 **Royal Violet / Purple**: `#9d8df1` & `#7c5cfc`.
  - 💙 **Discord Blurple**: `#5865f2`.
  - 🟢 **Success Emerald**: `#57f287`.
  - 🟡 **Warning Amber Gold**: `#fee75c`.
  - 🔴 **Danger Crimson**: `#ed4245`.

### 1.2 Kiểu Chữ (Typography)
- Sử dụng Google Fonts: **`Plus Jakarta Sans`** cho tiêu đề & số liệu thống kê; **`Inter`** cho nội dung văn bản.
- Kích thước phân cấp rõ ràng, dễ đọc trên cả màn hình di động (Mobile) và máy tính (Desktop).

### 1.3 Quy Tắc CSS & Không Dùng Framework Dư Thừa
- Sử dụng **Vanilla CSS** thuần túy có cấu trúc biến (`var(--bg-primary)`).
- **Không tự ý dùng TailwindCSS** nếu chưa có yêu cầu từ người dùng.
- Mọi liên kết stylesheet trong template Jinja2 phải được gắn phiên bản: `href="{{ url_for('static', filename='css/style.css') }}?v=9.2"`.

---

## 🌸 2. Quy Chuẩn Thiết Kế Avatar Mascot Nữ Sinh Zeryn (Minimal Chibi Style)

> [!IMPORTANT]
> **Quy Tắc Tối Giản Hiệu Ứng (Phong cách chuẩn "Uyên Sư Muội")**:
> - **Chỉ có DUY NHẤT 1 hiệu ứng**: **Ngôi sao vàng lấp lánh (1-2 golden sparkle stars)** ở gần cử chỉ tay (như giơ Like, 2 tay chữ V, vẫy tay).
> - **Tuyệt đối KHÔNG thêm hiệu ứng rườm rà**: Không vẽ mặt trăng khuyết to, không vẽ bụi sao dày đặc làm chói mắt, không vẽ vòng hoa rực rỡ hay cánh hoa bay kín màn hình làm rối nhân vật.
> - **Phông nền**: Nền tròn tím đêm huyền ảo (Dark midnight violet circle `#120e24`), sạch sẽ, nổi bật trọn vẹn khuôn mặt và biểu cảm của nhân vật.

### 2.1 Đặc Điểm Nhận Diện Của Nhân Vật Nữ Sinh Zeryn:
1. **Mái tóc**: Tóc nâu hạt dẻ mềm mại, uốn gợn sóng nhẹ tự nhiên.
2. **Phụ kiện tóc**: 1 chiếc kẹp **bông hoa anh đào (sakura)** màu hồng phấn nhẹ nhàng bên tai.
3. **Khuôn mặt & Ánh mắt**: Mắt nâu hổ phách to tròn, long lanh lấp lánh, má ửng hồng ngọt ngào, miệng cười tươi vui vẻ.
4. **Trang phục**: **Đồng phục nữ sinh thủy thủ Nhật Bản (Seifuku)** xanh navy, cổ áo viền sọc trắng, thắt nơ/khăn quàng đỏ rực rỡ.
5. **Nét vẽ**: Chibi sticker tròn trịa, tỷ lệ đầu to đáng yêu, đường nét vector anime kỹ thuật số sắc nét.

---

## 📝 3. Mẫu Prompt Tạo Ảnh Chuẩn Cho AI (Image Generation Template)

Khi cần tạo thêm ảnh Avatar mới cho Zeryn, AI sử dụng mẫu prompt tối giản sau:

```text
Super cute clean chibi anime avatar of the schoolgirl mascot Zeryn, in the adorable minimalist sticker style of 'Uyen su muoi'. She has soft dark brown wavy hair with a small pink sakura hairpin, big sparkling warm amber-gold anime eyes, blushing rosy cheeks, and a joyful smile. Wearing a classic navy blue Japanese school sailor uniform (seifuku) with white collar stripes and a red ribbon neckerchief. [MÔ TẢ CỬ CHỈ TAY VÍ DỤ: Giving a cute thumbs up / double peace sign]. ONLY a single tiny golden sparkle star near her hand. Clean standalone circular sticker avatar portrait on a solid deep dark violet night circle background, minimal and clean, absolutely no moon, no heavy floral rings, no cluttered flying petals, crisp kawaii anime art.
```

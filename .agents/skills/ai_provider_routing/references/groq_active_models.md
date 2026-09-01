# 📋 Danh Sách Mô Hình Groq Cloud Khả Dụng & Bị Vô Hiệu Hóa

> **Cập nhật lần cuối:** 2026-08-29  
> **Trạng thái:** Đồng bộ hoàn toàn với giao diện Admin Dashboard và `bot/cogs/ai.py`.

---

## ✅ 1. Danh Sách Mô Hình Khả Dụng (Active Models)

| Mã Model (Model ID) | Tham Số | Tốc Độ | Đặc Điểm & Đánh Giá |
|:-------------------|:--------|:-------|:---------------------|
| `qwen/qwen3.8-27b` | 27B | ~800 tps | 🌟 **Bản mới nhất của Qwen**. Hiểu tiếng Việt cực đỉnh, hành văn tự nhiên, đối thoại dí dỏm. **(KHUYÊN DÙNG SỐ 1)** |
| `qwen/qwen3.6-27b` | 27B | ~800 tps | 💬 Bản 27B ổn định, nói tiếng Việt mượt mà. |
| `openai/gpt-oss-20b` | 20B | ~1000 tps | ⚡ **Siêu nhẹ & Siêu tốc**. Phản hồi gần như tức thì, tiết kiệm token tối đa. |
| `groq/compound` | — | Tích hợp công cụ | 🌐 Hỗ trợ **duyệt web tự động và thực thi code** thông minh. |
| `groq/compound-mini` | Mini | Siêu tốc | 🚀 Bản rút gọn siêu tiết kiệm tài nguyên. |
| `openai/gpt-oss-120b` | 120B | ~500 tps | 💎 **Mạnh và thông minh nhất**. Suy luận sâu, giải toán, viết code phức tạp. |
| `openai/gpt-oss-safeguard-20b` | 20B | — | 🛡️ Bộ lọc kiểm duyệt an toàn nội dung. |

---

## ❌ 2. Danh Sách Mô Hình Bị Vô Hiệu Hóa (Disabled / Broken Models)

> [!CAUTION]
> **TUYỆT ĐỐI KHÔNG** thêm các model sau vào danh sách dropdown hoặc chuỗi fallback của bot vì chúng đã bị gỡ hoặc gây lỗi 404/Disabled trên endpoint:

- `llama-3.2-11b-vision-preview` (Đã bị disabled trên endpoint)
- `llama-3.2-90b-vision-preview` (Đã bị disabled trên endpoint)
- `llama-3.3-70b-versatile` (Đã bị disabled)
- `llama-3.1-8b-instant` (Đã bị disabled)
- `meta-llama/llama-4-maverick-17b-128e-instruct` (Không khả dụng)
- `deepseek-r1-distill-llama-70b` (Không khả dụng)

---

## 🔄 3. Cơ Chế Dual Prefix
Khi gọi Groq API, hệ thống tự động đối chiếu cả 2 tiền tố:
1. `groq/<model_id>` (ví dụ: `groq/qwen/qwen3.8-27b`)
2. `<model_id>` (ví dụ: `qwen/qwen3.8-27b`)
Đảm bảo 100% không bao giờ gặp lỗi HTTP 404 Model Not Found.

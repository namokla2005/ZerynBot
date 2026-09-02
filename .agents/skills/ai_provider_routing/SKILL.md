---
name: ai_provider_routing
description: >
  Guide and reference for ZerynBot V2 AI provider routing layer, model selection,
  multimodal vision, Groq Cloud, Gemini, and OpenRouter integration.
---

# Skill: AI Provider Routing & Model Management

## 🎯 1. Mục Đích & Tổng Quan

Tài liệu này cung cấp hướng dẫn kiến trúc và quy trình làm việc khi sửa đổi hoặc mở rộng tầng AI của **ZerynBot V2** (`bot/cogs/ai.py`, `dashboard/app.py`, `dashboard/templates/admin.html`).

---

## 🏗️ 2. Luồng Xử Lý AI Đa Nhà Cung Cấp (Multi-Provider Architecture)

Hàm trung tâm `call_ai_api()` tự động điều hướng request dựa vào tiền tố API Key:

```
[call_ai_api(prompt, system_prompt, api_key, image_url, preferred_model)]
   │
   ├─ Không có Key? ──────────────► Smart Local Responder (_local_smart_reply)
   ├─ Key bắt đầu `gsk_` ────────► Groq Cloud API (_call_groq_api)
   ├─ Key bắt đầu `sk-or-` ──────► OpenRouter API (_call_openrouter_api)
   └─ Key bắt đầu `AIzaSy` ──────► Google Gemini API (gemini-2.0-flash / 1.5)
```

---

## ⚡ 3. Quy Chuẩn Groq Cloud Model Routing

### 3.1 Model Ưu Tiên & Cài Đặt Toàn Cục (`global_ai_model`)
1. **Lấy cấu hình**: Đọc `global_ai_model` từ bảng `bot_global_settings` trong SQLite. Mặc định là `qwen/qwen3.8-27b`.
2. **Dual-Prefix Matching**: Groq API có thể nhận dạng model theo cả 2 định dạng:
   - Có tiền tố: `groq/qwen/qwen3.8-27b`
   - Không tiền tố: `qwen/qwen3.8-27b`
   Code trong `_call_groq_api` luôn tự động sinh cả 2 dạng vào danh sách fallback để chống lỗi HTTP 404.

### 3.2 Chuỗi Fallback Khi Chat Văn Bản:
```python
models = [
    preferred_model,
    "qwen/qwen3.8-27b",
    "groq/qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "groq/qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "groq/openai/gpt-oss-20b",
    "groq/compound-mini",
    "groq/compound",
    "openai/gpt-oss-120b"
]
```

### 3.3 Chuỗi Fallback Khi Có Ảnh (Multimodal Vision):
Khi người dùng gửi ảnh qua `/ask` hoặc tải ảnh lên kênh `#ai-chat`, tin nhắn được chuyển thành `image_url` block:
```python
models = [
    "groq/compound", "groq/groq/compound",
    "qwen/qwen3.8-27b", "groq/qwen/qwen3.8-27b",
    "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"
]
```

---

## 📋 4. Danh Mục Tài Liệu Tham Khảo

- 📄 [`.agents/skills/ai_provider_routing/references/groq_active_models.md`](references/groq_active_models.md): Bảng tra cứu toàn bộ model Groq đang khả dụng và danh sách model bị disabled.

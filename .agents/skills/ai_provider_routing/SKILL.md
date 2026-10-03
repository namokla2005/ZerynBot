---
name: ai_provider_routing
description: >
  Guide and reference for ZerynBot V2 AI provider routing layer, model selection,
  multimodal vision, Groq Cloud, Gemini, and OpenRouter integration.
---

# Skill: AI Provider Routing & Model Management

## 🎯 1. Mục Đích & Tổng Quan

Tài liệu này cung cấp hướng dẫn kiến trúc và quy trình làm việc khi sửa đổi hoặc mở rộng tầng AI của **ZerynBot V2** (`bot/cogs/ai.py`, `ai_manager.py`, `dashboard/blueprints/admin.py`, `dashboard/templates/admin.html`).

---

## 🏗️ 2. Luồng Xử Lý AI Đa Nhà Cung Cấp & Multi-Key Pool (`ai_manager.py`)

Hệ thống quản lý AI trung tâm hỗ trợ Multi-Key Pool và tự động chuyển tầng failover (Circuit Breaker & 429 Cooldown):

```
[User Request / Assistant Chat / Dashboard Chat]
   │
   ├─ Google Gemini Pool (gemini-3.6-flash / 3.5 / lite)
   │     └─ 429 / Quota Exceeded? ──► Tự động xoay key tiếp theo hoặc chuyển tầng sang Groq
   ├─ Groq Cloud Pool (qwen/qwen3.8-27b, openai/gpt-oss-120b, openai/gpt-oss-20b)
   │     └─ 429 / Quota Exceeded? ──► Tự động xoay key tiếp theo hoặc chuyển tầng sang OpenRouter
   ├─ OpenRouter Pool (nvidia/nemotron-3-ultra-550b-a55b:free, openrouter/free)
   │     └─ Hết hạn ngạch? ─────────► Smart Local Responder (_local_smart_reply)
   └─ Không có Key? ────────────────► Smart Local Responder (_local_smart_reply)
```

---

## 🛡️ 3. Cơ Chế Phản Biện Đa Model 2 (Dual-Model Co-Reasoning Model 2 Hierarchy)

Trong Developer Harness (`scripts/dual_model_mcp.py`), **Model 2 (Independent Reviewer & Security Critic)** vận hành theo chuỗi phân tầng nghiêm ngặt:

1. 🥇 **Tier 1 (Ưu tiên số 1 - Khởi đầu)**:
   - **Model**: `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA: Nemotron 3 Ultra 550B Free) qua OpenRouter.
   - **Mục đích**: Suy luận chuyên sâu, phản biện sắc sảo, không tốn chi phí.
2. 🥈 **Tier 2 (Fallback 1 khi hết Token / HTTP 429)**:
   - **Model**: `qwen/qwen3.8-27b` qua Groq Cloud LPU.
   - **Mục đích**: Tốc độ phản hồi cực nhanh (~300 tps), tiếng Việt chuẩn mực, hỗ trợ cứu nguy tức thì khi OpenRouter free pool bị nghẽn.
3. 🥉 **Tier 3 (Fallback 2 khi hết Token tiếp)**:
   - **Model**: `openai/gpt-oss-120b` qua Groq Cloud LPU.
   - **Mục đích**: Model mã nguồn mở siêu lớn (120B parameters), năng lực suy luận và phát hiện lỗ hổng phức tạp cấp cao.
4. 🛡️ **Tier 4 (Dự phòng an toàn mở rộng)**:
   - `openai/gpt-oss-20b` (Groq siêu tốc ~1000 tps) $\to$ `openrouter/free` (OpenRouter Auto-Router) $\to$ `gemini-3.6-flash` (Google Gemini).

---

## ⚡ 4. Quy Chuẩn Groq Cloud Model Routing

### 4.1 Model Ưu Tiên & Cài Đặt Toàn Cục (`global_ai_model`)
1. **Lấy cấu hình**: Đọc `global_ai_model` từ bảng `bot_global_settings` trong SQLite. Mặc định là `qwen/qwen3.8-27b`.
2. **Dual-Prefix Matching**: Groq API có thể nhận dạng model theo cả 2 định dạng:
   - Có tiền tố: `groq/qwen/qwen3.8-27b`
   - Không tiền tố: `qwen/qwen3.8-27b`
   Code trong `ai_manager.py` luôn tự động xử lý và làm sạch model slug để chống lỗi HTTP 404.

### 4.2 Chuỗi Fallback Khi Chat Văn Bản:
```python
models = [
    preferred_model,
    "qwen/qwen3.8-27b",
    "groq/qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "groq/openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "groq/openai/gpt-oss-20b",
    "groq/compound-mini",
    "groq/compound",
]
```

### 4.3 Chuỗi Fallback Khi Có Ảnh (Multimodal Vision):
Khi người dùng gửi ảnh qua `/ask` hoặc tải ảnh lên kênh `#ai-chat`, tin nhắn được chuyển thành `image_url` block:
```python
models = [
    "groq/compound", "groq/groq/compound",
    "qwen/qwen3.8-27b", "groq/qwen/qwen3.8-27b",
    "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"
]
```

---

## 📋 5. Danh Mục Tài Liệu Tham Khảo

- 📄 [`.agents/skills/ai_provider_routing/references/groq_active_models.md`](references/groq_active_models.md): Bảng tra cứu toàn bộ model Groq đang khả dụng và danh sách model bị disabled.

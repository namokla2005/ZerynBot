# 🤖 Quy Trình Đồng Suy Luận & Phản Biện Đa Model (Dual-Model Co-Reasoning & Debate)

Tài liệu này hướng dẫn cách Antigravity AI kết hợp đồng thời **2 Model AI** trong quá trình cộng sự phát triển dự án **ZerynBot V2**.

---

## 🎯 1. Nguyên Tắc Hoạt Động (Core Principle)

- **Agent Chính (Primary Agent)**: Đóng vai trò **Lead Architect & Coordinator** (suy luận sâu, lập kế hoạch, chỉnh sửa code và điều phối công việc).
- **Model Thứ 2 (Secondary Model / Adversarial Critic)**: Đóng vai trò **Independent Reviewer & Security Auditor** (soi xét độc lập, tìm kiếm lỗ hổng bảo mật, lỗi hiệu năng ARM64, deadlock SQLite và các trường hợp biên).
- Hai model trao đổi thông qua **MCP Server `dual_model`** hoặc CLI trực tiếp `python scripts/dual_model_mcp.py`.

---

## 🛠️ 2. Các Công Cụ Sẵn Có Của Server `dual_model`

1. **`consult_second_model(prompt, role, model)`**:
   - Gửi yêu cầu/đề xuất sang Model thứ 2 để lấy ý kiến phản biện (Second Opinion).
   - Các vai trò (`role`):
     - `critic`: Senior Security Auditor & Code Reviewer (soi xét lỗ hổng, race condition, OOM).
     - `architect`: Senior System Architect (đánh giá kiến trúc, khả năng mở rộng).
     - `tester`: QA Lead (đặt ra kịch bản kiểm thử khắc nghiệt, fuzzing, edge cases).
2. **`run_dual_model_debate(topic, rounds)`**:
   - Chạy tranh biện qua lại giữa 2 model từ 1 đến 4 hiệp và đúc kết bản đồng thuận kỹ thuật cuối cùng (`final consensus`).
3. **`get_dual_model_status()`**:
   - Kiểm tra kết nối API Key của các provider (Groq, Gemini, OpenRouter).

---

## 📋 3. Khi Nào Cần Kích Hoạt Dual-Model

Agent chính chủ động kích hoạt hỏi ý kiến Model thứ 2 trong các tình huống:
1. **Thay đổi cấu trúc CSDL hoặc Transaction**: Khi viết logic giao dịch tiền tệ (`economy`), trừ kho, hoặc câu lệnh SQL phức tạp có nguy cơ gây lock SQLite trên Termux.
2. **Quyết định phân quyền nhạy cảm**: Khi thiết kế các lệnh Admin, check phân quyền, hoặc cơ chế Step-Up Auth.
3. **Thuật toán hoặc luồng xử lý luồng (Async / Threading)**: Khi tối ưu pipeline phát nhạc, giải mã âm thanh FFmpeg, hoặc tải playlist song song.
4. **Khi Người Dùng yêu cầu đối chiếu**: Khi người dùng hỏi *"hai model nghĩ sao về vấn đề này?"* hoặc yêu cầu tranh luận về một hướng tiếp cận.

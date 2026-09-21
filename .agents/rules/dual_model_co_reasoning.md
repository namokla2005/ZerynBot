# 🤖 Quy Trình Đồng Suy Luận & Phản Biện Đa Model (Dual-Model Co-Reasoning & Developer Harness)

Tài liệu này hướng dẫn cách Antigravity AI kết hợp đồng thời **2 Model AI** trong quá trình cộng sự phát triển dự án **ZerynBot V2** trực tiếp trên laptop của lập trình viên.

---

## 🎯 1. Nguyên Tắc Hoạt Động Mặc Định (Mandatory Default Principle)

> [!IMPORTANT]
> **Quy Tắc Mặc Định Bắt Buộc**: AI phải **luôn luôn vận hành song song 2 Model AI** trong toàn bộ vòng đời phát triển (tiếp nhận yêu cầu, phân tích nguyên nhân gốc rễ, lên phương án kiến trúc, phản biện kỹ thuật và rà soát mã nguồn). Không được bỏ qua Model 2 trong bất kỳ tác vụ chỉnh sửa logic nào.

- **Agent Chính (Primary Agent - Gemini 3.8 Flash)**: Đóng vai trò **Lead Architect & Coordinator** trong Antigravity IDE (suy luận ngữ cảnh lớn 1M+ tokens, lập kế hoạch, chỉnh sửa code và điều phối công việc).
- **Model Thứ 2 (Secondary Model - Qwen 3.8 27B / GPT-OSS 20B trên Groq LPU)**: Đóng vai trò **Independent Reviewer & Security Auditor** (soi xét độc lập, tìm kiếm lỗ hổng bảo mật, lỗi hiệu năng ARM64, deadlock SQLite và các trường hợp biên).
- **Kênh Tác Nghiệp**: Hai model trao đổi thông qua **MCP Server `dual_model`** (chuẩn MCP 2.x Stdio) hoặc CLI trực tiếp `python scripts/dual_model_mcp.py` với **Pydantic v2 Type-Safety Schemas**.

---

## 🛠️ 2. Danh Sách Công Cụ Của Developer Harness (`scripts/dual_model_mcp.py`)

### 2.1 Các Tools Tích Hợp Sẵn Cho Antigravity IDE (MCP Tools)
1. **`review_code_file(file_path)`**:
   - Yêu cầu Model 2 đọc và rà soát một tệp mã nguồn cụ thể.
   - Tự động scrub bí mật, chống path traversal, bóc tách lỗi và xuất báo cáo chuẩn Pydantic: Điểm số, Phán quyết (`APPROVED`/`REQUEST_CHANGES`), danh sách lỗi phân cấp (`CRITICAL`/`WARNING`/`INFO`) kèm tác động Termux.
2. **`review_pre_commit_diff()`**:
   - Yêu cầu Model 2 quét toàn bộ `git diff` (staged hoặc unstaged) trước khi commit.
   - Đánh giá rủi ro hồi quy (Regression Risks), kiểm tra checklist quy chuẩn (i18n 1621 keys, SQLite concurrency, module guards).
3. **`consult_second_model(prompt, role, model)`**:
   - Gửi yêu cầu/đề xuất sang Model thứ 2 để lấy ý kiến phản biện (Second Opinion).
   - Vai trò: `critic` (Bảo mật/Hiệu năng), `architect` (Kiến trúc sạch), `tester` (Phá hoại/Fuzzing).
4. **`run_dual_model_debate(topic, rounds)`**:
   - Chạy tranh biện qua lại nhiều hiệp giữa 2 model và đúc kết bản đồng thuận kỹ thuật cuối cùng (`final consensus`).
5. **`get_dual_model_status()`**:
   - Kiểm tra kết nối API Key của các provider (Groq, Gemini, OpenRouter).

### 2.2 Các Lệnh CLI Sử Dụng Trực Tiếp Trên Terminal Laptop
```powershell
# 1. Rà soát nhanh một file mã nguồn trước khi deploy
python scripts/dual_model_mcp.py --review-file bot/cogs/music.py

# 2. Rà soát git diff trước khi commit
python scripts/dual_model_mcp.py --pre-commit-check

# 3. Tham khảo ý kiến phản biện về một ý tưởng kỹ thuật
python scripts/dual_model_mcp.py --consult "Có nên chuyển từ SQLite sang PostgreSQL trên Termux không?" --role critic

# 4. Chạy tranh luận 2 hiệp giữa Architect và Critic
python scripts/dual_model_mcp.py --debate "Kiến trúc Audio Pipeline tối ưu cho Termux ARM64" --rounds 2

# 5. Kiểm tra trạng thái các provider AI
python scripts/dual_model_mcp.py --status
```

---

## 📋 3. Quy Trình Làm Việc Tiêu Chuẩn Trước Khi Đẩy Code Lên Termux (Pre-Deploy Pipeline)

Trước khi thực hiện `git push origin main` lên máy chủ Termux, quy trình 4 bước bắt buộc:
1. **Sửa code cục bộ**: Thực hiện thay đổi trên laptop.
2. **Rà soát tự động với Model 2**:
   - Chạy `python scripts/dual_model_mcp.py --pre-commit-check`
   - Hoặc gọi tool `review_code_file` đối với các file có sửa đổi lớn.
3. **Chạy bộ kiểm thử tự động cục bộ**:
   ```powershell
   python .agents/skills/zerynbot_architecture_context/assets/validate_i18n.py
   python main.py --test
   pytest tests/
   ```
4. **Commit & Tự động triển khai Termux**:
   ```powershell
   git add .
   git commit -m "feat/fix: ..."
   git push origin main
   python scripts/termux_deploy.py
   ```

---

## 💬 4. Cấu Trúc Trình Bày Phản Hồi Bắt Buộc (Mandatory Response Format)

Để đảm bảo người dùng luôn thấy rõ sự tham gia đồng thời của cả 2 model, trong mọi câu trả lời phân tích kỹ thuật hoặc đề xuất giải pháp, AI **BẮT BUỘC** định dạng kết quả theo 3 phần:

1. 🏛️ **Model 1 — Lead Architect (Gemini 3.8)**:
   - Phân tích nguyên nhân gốc rễ, luồng dữ liệu, kiến trúc tổng thể và đề xuất giải pháp.
2. 🛡️ **Model 2 — Security & Systems Critic (Qwen 2.5 / GPT-OSS qua Groq)**:
   - Phản biện độc lập: các rủi ro bảo mật (SSRF, IDOR, XSS), rủi ro SQLite WAL, tắc nghẽn tài nguyên trên Termux ARM64 (Helio G85, 6GB RAM).
3. 🤝 **Đồng Thuận Kỹ Thuật (Consensus & Final Verdict)**:
   - Kết luận thống nhất giữa 2 Model, giải pháp được cả 2 Model thông qua (`APPROVED`) và các bước hành động cụ thể.


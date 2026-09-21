# 🤖 Quy Trình Đồng Suy Luận & Phản Biện Đa Model (Dual-Model Co-Reasoning & Developer Harness)

Tài liệu này hướng dẫn cách Antigravity AI kết hợp đồng thời **2 Model AI** trong quá trình cộng sự phát triển dự án **ZerynBot V2** trực tiếp trên laptop của lập trình viên.

---

## 🎯 1. Nguyên Tắc Hoạt Động Mặc Định (Mandatory Default Principle)

> [!IMPORTANT]
> **Quy Tắc Mặc Định Bắt Buộc**: AI phải **luôn luôn vận hành song song 2 Model AI** trong toàn bộ vòng đời phát triển (tiếp nhận yêu cầu, phân tích nguyên nhân gốc rễ, lên phương án kiến trúc, phản biện kỹ thuật và rà soát mã nguồn). Không được bỏ qua Model 2 trong bất kỳ tác vụ chỉnh sửa logic nào.

- **Agent Chính (Primary Agent - Gemini 3.8 Flash)**: Đóng vai trò **Lead Architect & Coordinator** trong Antigravity IDE (suy luận ngữ cảnh lớn 1M+ tokens, lập kế hoạch, chỉnh sửa code và điều phối công việc).
- **Model Thứ 2 (Secondary Model - Qwen 3.8 27B / GPT-OSS 20B trên Groq LPU)**: Đóng vai trò **Independent Reviewer & Security Auditor** (soi xét độc lập, tìm kiếm lỗ hổng bảo mật, lỗi hiệu năng ARM64, deadlock SQLite và các trường hợp biên).
- **Kênh Tác Nghiệp**: Hai model trao đổi thông qua **MCP Server `dual_model`** (chuẩn MCP 2.x Stdio) hoặc CLI trực tiếp `python scripts/dual_model_mcp.py` với **Pydantic v2 Type-Safety Schemas**.

### 🔍 1.1 Quy Chuẩn Tiếp Nhận Báo Lỗi (Evidence-Based Incident Triage)
Khi Người Dùng thông báo bất kỳ lỗi nào, AI **tuyệt đối không được phỏng đoán mò mẫm hay vội vàng sửa mã nguồn trên máy tính**. AI **bắt buộc** phải lập tức kết nối tới Termux để thu thập dữ liệu thực tế bằng công cụ:
```powershell
python scripts/termux_diag.py
```
Dữ liệu thu thập bao gồm:
1. Trạng thái các dịch vụ (`python main.py --status`, `ps -ef`).
2. 60 dòng log gần nhất (`data/bot.log`, `data/dashboard.log`) kèm trích xuất Traceback.
3. Phản hồi Health Endpoint (`/health`).
4. Kích thước CSDL SQLite WAL và tài nguyên RAM/Swap (`free -h`, `uptime`).

Dựa trên toàn bộ chứng cứ thực tế này, Model 1 và Model 2 mới bắt đầu chu trình phản biện 5 bước.

---

## 🔄 2. Chu Trình Phản Biện 5 Bước Chuẩn (The 5-Step Dual-Model Loop)

Mọi bài toán sửa lỗi hoặc thay đổi logic đều phải tuân thủ nghiêm ngặt chu trình 5 bước sau:

```
┌─────────────────────────┐
│ 1. LÊN KẾ HOẠCH         │  (Model 1 — Dựa trên dữ liệu Termux & Codebase)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 2. KIỂM TRA + PHẢN BIỆN │  (Model 2 — Soi xét bảo mật, ARM64, SQLite WAL)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 3. SỬA KẾ HOẠCH         │  (Model 1 — Tiếp thu phản biện, hoàn thiện Plan v2)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐     [Có lỗi / Còn rủi ro]
│ 4. KIỂM TRA + PHẢN BIỆN ├──────────────────────────┐
│    LẠI                  │                          │
└───────────┬─────────────┘                          │
            │ [Đạt chuẩn]                            ▼
            ▼                               ┌──────────────────┐
┌─────────────────────────┐                 │ Tinh chỉnh lại   │
│ 5. ĐỒNG THUẬN (1 & 2)   │ ◄───────────────┤ (Tối đa 3 vòng)  │
│    (Ký duyệt APPROVED)  │                 └──────────────────┘
└─────────────────────────┘
```

1. **Bước 1 (1 - Lên kế hoạch)**: Model 1 phân tích nguyên nhân gốc rễ (Root Cause) từ log Termux, bóc tách phạm vi ảnh hưởng và phác thảo kế hoạch kỹ thuật (`Plan v1`).
2. **Bước 2 (2 - Kiểm tra + Phản biện)**: Model 2 rà soát độc lập (`Critique v1`) qua `python scripts/dual_model_mcp.py --consult "<kế hoạch>" --role critic`, chỉ ra các điểm mù, rủi ro bảo mật (SSRF, IDOR, XSS), race condition, và nguy cơ nghẽn SQLite WAL.
3. **Bước 3 (1 - Sửa kế hoạch)**: Model 1 tiếp thu phản biện, cập nhật phương án kỹ thuật, bổ sung các lớp bảo vệ và tối ưu hóa (`Plan v2`).
4. **Bước 4 (2 - Kiểm tra + Phản biện lại)**: Model 2 rà soát lại `Plan v2` (`Critique v2`). Nếu vẫn phát hiện lỗ hổng hoặc rủi ro tiềm ẩn, tiếp tục yêu cầu Model 1 chỉnh sửa (tối đa 3 vòng lặp để tránh nghẽn).
5. **Bước 5 (1 & 2 - Đồng thuận)**: Cả 2 Model cùng ký duyệt `APPROVED`, thống nhất phương án tối ưu nhất, sau đó mới tiến hành viết code/triển khai.

---

## 🛠️ 3. Danh Sách Công Cụ Của Developer Harness (`scripts/dual_model_mcp.py`)

### 3.1 Các Tools Tích Hợp Sẵn Cho Antigravity IDE (MCP Tools)
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

### 3.2 Các Lệnh CLI Sử Dụng Trực Tiếp Trên Terminal Laptop
```powershell
# 1. Thu thập dữ liệu chẩn đoán thực tế từ Termux khi có báo lỗi
python scripts/termux_diag.py

# 2. Rà soát nhanh một file mã nguồn trước khi deploy
python scripts/dual_model_mcp.py --review-file bot/cogs/music.py

# 3. Rà soát git diff trước khi commit
python scripts/dual_model_mcp.py --pre-commit-check

# 4. Tham khảo ý kiến phản biện về một ý tưởng kỹ thuật
python scripts/dual_model_mcp.py --consult "Nội dung kế hoạch..." --role critic

# 5. Chạy tranh luận 2 hiệp giữa Architect và Critic
python scripts/dual_model_mcp.py --debate "Kiến trúc Audio Pipeline tối ưu cho Termux ARM64" --rounds 2

# 6. Kiểm tra trạng thái các provider AI
python scripts/dual_model_mcp.py --status
```

---

## 📋 4. Quy Trình Làm Việc Tiêu Chuẩn Trước Khi Đẩy Code Lên Termux (Pre-Deploy Pipeline)

Trước khi thực hiện `git push origin main` lên máy chủ Termux, quy trình 4 bước bắt buộc:
1. **Sửa code cục bộ**: Thực hiện thay đổi trên laptop sau khi 2 model đã đạt đồng thuận.
2. **Rà soát tự động với Model 2**:
   - Chạy `python scripts/dual_model_mcp.py --pre-commit-check`
   - Đạt phán quyết `🟢 SẴN SÀNG COMMIT`.
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

## 💬 5. Cấu Trúc Trình Bày Phản Hồi Bắt Buộc (Mandatory Response Format)

Để đảm bảo người dùng luôn thấy rõ sự tham gia đồng thời của cả 2 model, trong mọi câu trả lời phân tích kỹ thuật hoặc đề xuất giải pháp, AI **BẮT BUỘC** định dạng kết quả theo 3 phần:

1. 🏛️ **Model 1 — Lead Architect (Gemini 3.8)**:
   - Phân tích nguyên nhân gốc rễ (kèm dữ liệu chẩn đoán Termux), luồng dữ liệu, kiến trúc tổng thể và đề xuất giải pháp.
2. 🛡️ **Model 2 — Security & Systems Critic (Qwen 2.5 / GPT-OSS qua Groq)**:
   - Phản biện độc lập: các rủi ro bảo mật (SSRF, IDOR, XSS), rủi ro SQLite WAL, tắc nghẽn tài nguyên trên Termux ARM64 (Helio G85, 6GB RAM).
3. 🤝 **Đồng Thuận Kỹ Thuật (Consensus & Final Verdict)**:
   - Kết luận thống nhất giữa 2 Model, giải pháp được cả 2 Model thông qua (`APPROVED`) và các bước hành động cụ thể.



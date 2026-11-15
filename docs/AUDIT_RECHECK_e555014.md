# Rà soát lại commit e555014

> Báo cáo lịch sử về code TRƯỚC bản sửa. Các lỗi liệt kê bên dưới đã được xử lý trong bản sửa đi kèm: Git chạy từng argv và dừng ở exit code lỗi; cleanup kiểm tra mã thoát và đóng transport; boot kiểm tra main.py và fallback ~/ZerynBot; invite và language routes đã sửa. Không dùng mô tả lỗi cũ bên dưới làm kết luận về code mới. Regression tests nằm trong tests/test_audit_dashboard.py và tests/test_audit_cleanup.py.

## Phạm vi và giới hạn

Danh mục Git: 226 file được theo dõi, trong đó 142 file Python, 30 HTML, 2 JS và 2 shell. Đã chạy kiểm tra tự động toàn repo và rà sâu các đường dẫn dashboard/ops nêu dưới đây. Các nhóm rà độc lập bot/database/music/AI bị gián đoạn dịch vụ, không có báo cáo hoàn tất; vì vậy không tuyên bố đã đọc và chứng minh đúng mọi nhánh logic của mọi file. Không sửa mã production, không commit/push/deploy trong đợt kiểm tra này.

Kiểm thử trên clone riêng không có .env hoặc database production. Bản git archive đầu tiên thiếu .git gây 1 lỗi test SHA; chạy lại trên git clone thật đã hết lỗi môi trường này.

## Kết quả chạy thật

- Pytest: 520 passed, 1 skipped, 8 warnings, 58.23 giây trên Python 3.12.8. Skip là kiểm tra fd Linux /proc; warnings do clone không có cấu hình bí mật và test cấu hình.
- compileall: exit 0.
- Ruff F821/F822/F823/E9: sạch. Ruff theo cấu hình đầy đủ: 246 findings (217 F401, 14 F541, 10 F841, 4 F811, 1 F402); không được coi tất cả là lỗi runtime.
- Registry: 128 lệnh code / 128 entry, không lệch.
- Locale: 6 file, mỗi file 1890 keys, key sets bằng nhau.
- 30 Jinja templates compile; 2 file JS static qua node --check; 2 shell scripts qua bash -n. Chưa kiểm tra mọi inline JS sau render bằng browser.
- Termux tại 2026-11-15 23:26: Bot PID 14633 và Dashboard PID 14638 RUNNING; health online=true; không có traceback trong cửa sổ log diagnostic. Có các lần Discord disconnect rồi resume.

## Phát hiện

### HIGH — Git Pull có thể mất sửa đổi chưa lưu

Vị trí: dashboard/blueprints/admin.py:915–919, 941–945.

Chuỗi shell là `git fetch ... && git stash push ... ; git reset --hard origin/main && ...`. Dấu `;` cho phép reset tiếp tục khi fetch hoặc stash thất bại. Response còn trả ok=true không phụ thuộc returncode.

Probe lấy chính AST của pull_cmd rồi thay git bằng hàm shell giả (không chạy reset thật):
- fetch fail: calls fetch → reset → stash(list), exit 0.
- stash fail: calls fetch → stash(push) → reset → stash(list), exit 0.

Nên chạy từng subprocess argv, kiểm tra từng exit code và dừng trước reset nếu chưa backup/stash thành công.

### MEDIUM — Các nút mời bot trên landing không có đích

Vị trí: dashboard/blueprints/public.py:37–39; dashboard/templates/landing.html:739 và các chỗ dùng invite_url.

index() render landing không truyền invite_url; không có context provider định nghĩa biến này. HTTP GET website thật trả 200 nhưng có 12 anchor href="". Các CTA không mở trang Discord mời bot. Dùng url_for('public.invite') hoặc inject invite_url đúng.

### MEDIUM — Đổi ngôn ngữ Docs/Support trả 404

Vị trí: dashboard/templates/docs.html:570–575; support.html:635–640.

Cả hai template trỏ /set_lang/<lang>; route thật là /ui/language/<lang_code>. Test client thực tế: cả vi/en/zh/es/pt/fr dưới /set_lang đều 404. Dùng url_for('public.set_ui_language', lang_code=...).

### MEDIUM — Script boot sai root khi cài theo hướng dẫn

Vị trí: scripts/termux_boot.sh:2, 22–30.

Copy script vào ~/.termux/boot theo hướng dẫn khiến dirname/.. thành ~/.termux, không phải ~/ZerynBot. Nếu ZERYN_HOME không được export sẵn cho tiến trình Boot, điều kiện chỉ kiểm tra thư mục tồn tại vẫn đi tiếp, chạy main.py và ghi data/boot.log ở sai nơi. Đây là phân tích đường dẫn source; không reboot thiết bị để thử. Cần tìm root có main.py, kiểm tra file, tạo data và báo lỗi rõ.

### MEDIUM — Cleanup bỏ qua exit code và báo thành công giả

Vị trí: scripts/termux_cleanup.py:147–183, 205–210.

Probe thay _Runner bằng transport giả: kết nối thành công nhưng mọi lệnh exec trả exit 1; run_termux_cleanup() vẫn trả True. Nên tổng hợp lỗi, dừng các bước phụ thuộc và trả False khi tác vụ thiết yếu lỗi.

### LOW — Cleanup không xoay log với đường dẫn mặc định ~/ZerynBot

Vị trí: scripts/termux_cleanup.py:167.

Lệnh sinh `f="~/ZerynBot/data/bot.stdout.log"`; dấu ~ trong nháy kép không được Bash expand. Probe Bash trả nguyên chuỗi ~/ZerynBot/data/bot.stdout.log. Nhánh kiểm tra file bỏ qua log thật. Watchdog có cơ chế xoay riêng nên tác động được giảm, nhưng chức năng cleanup này sai. Cần resolve home trước và quote đường dẫn tuyệt đối.

### Nội dung/UI còn thiếu kiểm chứng

support.html còn hardcode nhiều nhãn tiếng Việt và lời hứa 'Thường trả lời trong vòng 1-2 giờ', 'Sẵn sàng làm việc', 'Ticket 24/7'. Những cam kết này đã được thêm trong lần làm trước nhưng chưa có dữ liệu người dùng xác nhận; không nên trình bày như trạng thái online hoặc SLA đo được. CSS contact cũng đang trùng giữa style.css và inline support.html; chưa có kiểm tra browser đa viewport hoàn chỉnh trong đợt này.

## Bằng chứng tái hiện

Script: C:/Users/Nam/AppData/Local/hermes/cache/scratch/zeryn-audit-e555014-evidence/repro_remaining.py
Kết quả JSON: cùng thư mục, repro_remaining.json.

Các probe dùng clone riêng, mock transport/process đối với tác vụ có side effect. Không chạy Git reset hoặc cleanup thật để chứng minh lỗi.

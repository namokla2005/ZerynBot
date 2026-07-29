#!/bin/bash
# termux_boot.sh - Copy file này vào ~/.termux/boot/ để chạy tự động khi tablet khởi động
# Yêu cầu cài ứng dụng "Termux:BOOT" từ F-Droid
#
# ─── LỚP PHÒNG THỦ 3/3 (dự phòng khi tablet REBOOT hoàn toàn) ─────────────────
#   - Lớp 1 (bot.py): bot tự close() khi offline >5 phút → watchdog restart
#   - Lớp 2 (watchdog.sh): health-check + exit-code → restart khi crash/treo
#   - LỚP 3 (file này): CHỈ chạy khi tablet REBOOT HOÀN TOÀN
#     (mất điện lâu → pin kiệt → tablet tắt → có điện khởi động lại).
#     Nếu chỉ mất wifi rồi có lại (tablet vẫn sống) → KHÔNG cần file này,
#     vì Lớp 1+2 đã tự lo restart bot.

# Đợi hệ thống ổn định một chút
sleep 10

# Bật wakelock để Termux luôn chạy nền
termux-wake-lock

# Chuyển đến thư mục bot (tự động nhận diện đường dẫn động hoặc fallback)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
if [ ! -f "$DIR/start.sh" ]; then
    DIR="/storage/emulated/0/Project/Discord Bots/v2"
fi

if [ -d "$DIR" ]; then
    cd "$DIR"
    # Gọi script start.sh
    bash start.sh > data/boot.log 2>&1
else
    echo "Không tìm thấy thư mục bot ở $DIR" > ~/bot_boot_error.log
fi

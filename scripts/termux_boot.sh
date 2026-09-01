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

# Chuyển đến thư mục bot (tự động nhận diện đường dẫn động hoặc dùng biến môi trường)
# Fallback: đặt ZERYN_HOME trong ~/.bashrc / ~/.profile, vd:
#   export ZERYN_HOME="/storage/emulated/0/Project/Discord Bots/v2"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
if [ ! -f "$DIR/main.py" ] && [ -n "$ZERYN_HOME" ]; then
    DIR="$ZERYN_HOME"
fi

if [ -d "$DIR" ]; then
    cd "$DIR"
    # Khởi chạy toàn bộ hệ thống qua main.py
    python main.py > data/boot.log 2>&1
else
    echo "Không tìm thấy thư mục bot ở $DIR" > ~/bot_boot_error.log
fi

#!/bin/bash
# termux_boot.sh — Copy file này vào ~/.termux/boot/ để chạy tự động khi tablet khởi động
# Yêu cầu cài ứng dụng "Termux:Boot" từ F-Droid

# Đợi hệ thống ổn định một chút
sleep 10

# Bật wakelock để Termux luôn chạy nền
termux-wake-lock

# Chuyển đến thư mục bot và chạy script khởi động
# LƯU Ý: Bạn có thể cần sửa lại đường dẫn nếu bot không nằm ở /storage/emulated/0/Project/Discord Bots/v2
BOT_DIR="/storage/emulated/0/Project/Discord Bots/v2"

if [ -d "$BOT_DIR" ]; then
    cd "$BOT_DIR"
    # Gọi script start.sh
    bash start.sh > data/boot.log 2>&1
else
    echo "Không tìm thấy thư mục bot ở $BOT_DIR" > ~/bot_boot_error.log
fi

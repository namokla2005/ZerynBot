#!/bin/bash
# watchdog.sh — Tự động restart bot nếu crash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

echo "[Watchdog] Đã khởi động."
while true; do
    echo "[Watchdog] Đang chạy bot..."
    python run_bot.py
    
    EXIT_CODE=$?
    echo "[Watchdog] Bot đã dừng với mã thoát $EXIT_CODE."
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[Watchdog] Bot đã tắt một cách bình thường. Dừng watchdog."
        break
    else
        echo "[Watchdog] CẢNH BÁO: Bot bị crash! Sẽ khởi động lại sau 5 giây..."
        sleep 5
    fi
done

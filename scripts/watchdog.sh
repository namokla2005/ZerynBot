#!/bin/bash
# watchdog.sh — Tự động restart bot nếu crash HOẶC treo (offline lâu).
#
# 2 cơ chế phát hiện:
#   1) Exit-code (cũ): nếu process bot thoát != 0 → restart (bot đã close() tự sát)
#   2) Health-check (mới): mỗi 90s curl /health, nếu bot báo offline
#      LIÊN TỤC quá 5 phút → kill bot để cơ chế 1 restart.
#      → bắt được trường hợp bot TREO (sống về PID nhưng mất kết nối Discord).
#
# Lớp phòng thủ 2/3: Lớp 1 (bot.py _offline_watchdog_task) + Termux:Boot (reboot tablet).

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

HEALTH_URL="http://localhost:5000/health"
HEALTH_INTERVAL=90        # kiểm tra mỗi 90 giây
HEALTH_FAIL_THRESHOLD=4   # ~6 phút (4 × 90s) → khớp với OFFLINE_THRESHOLD của bot

echo "[Watchdog] Đã khởi động. (exit-code + health-check)"

restart_count=0
get_backoff() {
    # 5s → 10s → 30s (tránh restart liên tục khi mạng thực sự xấu)
    case $1 in
        0|1) echo 5 ;;
        2)   echo 10 ;;
        *)   echo 30 ;;
    esac
}

# ─── Cơ chế 2: Health-check nền ────────────────────────────────────────────────
# Chạy song song với bot. Khi bot bị kill/crash, vòng while chính sẽ restart.
health_loop() {
    local fail_streak=0
    while true; do
        sleep "$HEALTH_INTERVAL"
        # curl -sf: fail (exit != 0) khi HTTP không phải 2xx hoặc lỗi kết nối
        # --max-time 10: chống treo khi dashboard không phản hồi
        if curl -sf --max-time 10 "$HEALTH_URL" >/dev/null 2>&1; then
            fail_streak=0   # bot khỏe (HTTP 200)
        else
            fail_streak=$((fail_streak + 1))
            echo "[Watchdog] Health-check FAIL lần $fail_streak (bot offline hoặc dashboard không phản hồi)"
            # Chỉ kill khi curl ĐỤNG ĐƯỢC dashboard (HTTP 503) nhưng bot offline liên tục.
            # Nếu dashboard cũng down (curl lỗi kết nối) → bỏ qua, không kill nhầm.
            # Phân biệt: -s hiển thị body, ta check HTTP code thực.
            http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null)
            if [ "$http_code" = "503" ] && [ "$fail_streak" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
                echo "[Watchdog] Bot offline liên tục $fail_streak × ${HEALTH_INTERVAL}s → KILL để restart"
                # Kill mọi process 'main.py --bot' (watchdog sẽ pick up ở vòng while chính)
                pkill -f 'main.py --bot' 2>/dev/null
                sleep 2
                pkill -9 -f 'main.py --bot' 2>/dev/null
                fail_streak=0  # reset sau khi kill
            fi
        fi
    done
}

# Khởi động health-check nền
health_loop &
HEALTH_PID=$!
trap 'kill $HEALTH_PID 2>/dev/null; exit 0' INT TERM

# ─── Vòng lặp chính: chạy bot + restart khi crash ──────────────────────────────
while true; do
    echo "[Watchdog] Đang chạy bot..."
    python main.py --bot
    EXIT_CODE=$?
    echo "[Watchdog] Bot đã dừng với mã thoát $EXIT_CODE."

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[Watchdog] Bot đã tắt bình thường. Dừng watchdog."
        break
    fi

    backoff=$(get_backoff $restart_count)
    restart_count=$((restart_count + 1))
    echo "[Watchdog] CẢNH BÁO: Bot bị crash/treo! Restart sau ${backoff}s (lần $restart_count)..."
    sleep "$backoff"
done

# Dọn health-check khi thoát
kill $HEALTH_PID 2>/dev/null

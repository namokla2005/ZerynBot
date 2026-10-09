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

PID_FILE="data/watchdog.pid"
BOT_PID_FILE="data/bot.pid"
DASH_PID_FILE="data/dashboard.pid"
STOPALL_FLAG="data/stopall.flag"
mkdir -p data
termux-wake-lock 2>/dev/null

# ─── Đảm bảo duy nhất 1 watchdog chạy (Singleton Guard) ─────────────────────────
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$old_pid" ] && [ "$old_pid" != "$$" ] && kill -0 "$old_pid" 2>/dev/null; then
        echo "[Watchdog] Đã phát hiện watchdog cũ (PID $old_pid). Đang dừng..."
        # Dọn sạch các tiến trình con của watchdog cũ để tránh mồ côi
        for c in $(pgrep -P "$old_pid" 2>/dev/null); do
            kill -15 "$c" 2>/dev/null
            sleep 1
            kill -9 "$c" 2>/dev/null
        done
        kill -15 "$old_pid" 2>/dev/null
        sleep 2
        kill -9 "$old_pid" 2>/dev/null
    fi
fi
echo $$ > "$PID_FILE"

HEALTH_URL="http://127.0.0.1:5000/health"
HEALTH_INTERVAL=90        # kiểm tra mỗi 90 giây
HEALTH_FAIL_THRESHOLD=4   # ~6 phút (4 × 90s) → khớp với OFFLINE_THRESHOLD của bot

# ─── Cắt log stdout khi phình quá lớn (chống đầy thẻ nhớ trên Termux) ─────────
# Log do ứng dụng tự ghi (data/bot.log, data/dashboard.log) đã có
# RotatingFileHandler tự xoay. Hàm này chỉ chặn phần stdout/stderr của tiến
# trình — thứ không ai quản lý và có thể phình vô hạn.
MAX_STDOUT_LOG_BYTES=$((5 * 1024 * 1024))   # 5MB
rotate_if_big() {
    for f in data/bot.stdout.log data/dashboard.stdout.log; do
        [ -f "$f" ] || continue
        size=$(wc -c < "$f" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_STDOUT_LOG_BYTES" ]; then
            # copytruncate, KHÔNG dùng `mv`: tiến trình bot/dashboard được mở bằng
            # `> file` nên giữ nguyên fd trỏ tới inode cũ. Sau `mv` chúng tiếp tục ghi
            # vào "$f.1", còn "$f" mới tạo thì vĩnh viễn rỗng -> rotation coi như không
            # có tác dụng và .1 phình đến đầy thẻ nhớ.
            cp -f "$f" "$f.1" 2>/dev/null && : > "$f"
            echo "[Watchdog] Đã xoay $f (vượt 5MB, copytruncate)"
        fi
    done
}

echo "[Watchdog] Đã khởi động (PID $$). (exit-code + health-check)"

# ─── Hàm kiểm tra kết nối mạng/DNS Termux tới Discord Gateway (Fallback 2 tầng) ────
check_discord_network() {
    # 1. Thử qua bash /dev/tcp siêu nhẹ (0 overhead)
    if timeout 4 bash -c '(echo > /dev/tcp/gateway.discord.gg/443) 2>/dev/null'; then
        return 0
    fi
    # 2. Fallback qua python socket nếu shell không hỗ trợ /dev/tcp
    python -c "
import socket, sys
try:
    s = socket.create_connection(('gateway.discord.gg', 443), timeout=4)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1
}

# ─── Dashboard tự hồi phục (Phase 5) ──────────────────────────────────────────
restart_dashboard() {
    if [ -f "$DASH_PID_FILE" ]; then
        d_pid=$(cat "$DASH_PID_FILE" 2>/dev/null)
        if [ -n "$d_pid" ] && kill -0 "$d_pid" 2>/dev/null; then
            echo "[Watchdog] Dashboard PID $d_pid còn sống nhưng không trả /health -> SIGTERM..."
            kill -15 "$d_pid" 2>/dev/null
            sleep 3
            kill -9 "$d_pid" 2>/dev/null
        fi
        rm -f "$DASH_PID_FILE" 2>/dev/null
    fi
    echo "[Watchdog] Khởi động lại Dashboard..."
    nohup python main.py --dashboard > data/dashboard.stdout.log 2>&1 &
    echo "$!" > "$DASH_PID_FILE"
}

# ─── Cơ chế 2: Health-check nền ────────────────────────────────────────────────
health_loop() {
    local fail_streak=0
    local dash_fail=0
    while true; do
        sleep "$HEALTH_INTERVAL"
        # Một lần curl duy nhất, lấy cả mã HTTP. Bản cũ gọi `curl -sf` rồi mới gọi lại
        # để lấy http_code: khi dashboard CHẾT hẳn thì http_code rỗng, nhánh "503" không
        # bao giờ chạy và zerynbot.id.vn nằm ngoài không phục vụ vô thời hạn trong khi
        # bot vẫn khỏe (dashboard chỉ được start lại ở vòng chính, sau khi bot exit).
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null)

        if [ "$http_code" = "200" ]; then
            fail_streak=0
            dash_fail=0
            continue
        fi

        if [ -z "$http_code" ] || [ "$http_code" = "000" ]; then
            dash_fail=$((dash_fail + 1))
            echo "[Watchdog] Dashboard không trả lời HTTP (lần $dash_fail) - đang restart..."
            if [ "$dash_fail" -ge 2 ]; then
                restart_dashboard
                dash_fail=0
            fi
            continue
        fi

        # Dashboard còn sống nhưng báo lỗi (503 = bot offline/heartbeat cụt)
        dash_fail=0
        fail_streak=$((fail_streak + 1))
        echo "[Watchdog] Health-check FAIL lần $fail_streak (http=$http_code)"
        if [ "$http_code" = "503" ] && [ "$fail_streak" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
            echo "[Watchdog] Bot offline liên tục $fail_streak × ${HEALTH_INTERVAL}s → Gửi SIGTERM dừng bot..."
            if [ -f "$BOT_PID_FILE" ]; then
                b_pid=$(cat "$BOT_PID_FILE" 2>/dev/null)
                if [ -n "$b_pid" ] && kill -0 "$b_pid" 2>/dev/null; then
                    kill -15 "$b_pid" 2>/dev/null
                    # Chờ tối đa 5 giây cho aiosqlite đóng và Discord ngắt kết nối an toàn
                    for i in 1 2 3 4 5; do
                        if ! kill -0 "$b_pid" 2>/dev/null; then
                            break
                        fi
                        sleep 1
                    done
                    # Nếu vẫn còn sống thì buộc kill -9
                    kill -9 "$b_pid" 2>/dev/null
                fi
                rm -f "$BOT_PID_FILE" 2>/dev/null
            fi
            fail_streak=0  # reset sau khi kill
        fi
    done
}

# Khởi động health-check nền & Dọn dẹp an toàn khi nhận tín hiệu dừng
health_loop &
HEALTH_PID=$!

cleanup_and_exit() {
    [ -n "$HEALTH_PID" ] && kill -15 "$HEALTH_PID" 2>/dev/null
    if [ -f "$BOT_PID_FILE" ]; then
        b_pid=$(cat "$BOT_PID_FILE" 2>/dev/null)
        [ -n "$b_pid" ] && kill -15 "$b_pid" 2>/dev/null
    fi
    rm -f "$PID_FILE" "$BOT_PID_FILE" 2>/dev/null
    termux-wake-unlock 2>/dev/null
    exit 0
}
trap cleanup_and_exit INT TERM EXIT

# ─── Vòng lặp chính: Chạy bot + Supervisor Auto-Recovery ────────────────────────
restart_count=0
get_backoff() {
    case $1 in
        0) echo 30 ;;
        1) echo 60 ;;
        2) echo 120 ;;
        *) echo 180 ;;
    esac
}

while true; do
    # 0. Kiểm tra cờ dừng toàn bộ (--stopall)
    if [ -f "$STOPALL_FLAG" ]; then        echo "[Watchdog] Đã nhận tín hiệu dừng toàn bộ (stopall.flag). Dừng watchdog."
        rm -f "$STOPALL_FLAG" 2>/dev/null
        exit 0
    fi

    # Cắt bớt log stdout nếu phình quá 5MB (rất nhẹ, chạy mỗi vòng lặp)
    rotate_if_big

    # Dọn dẹp tiến trình bot cũ nếu còn sót lại để triệt tiêu 100% duplicate bot
    if [ -f "$BOT_PID_FILE" ]; then
        old_b=$(cat "$BOT_PID_FILE" 2>/dev/null)
        if [ -n "$old_b" ]; then
            if kill -0 "$old_b" 2>/dev/null; then
                echo "[Watchdog] Dọn dẹp tiến trình bot cũ (PID $old_b)..."
                kill -15 "$old_b" 2>/dev/null
                sleep 2
                kill -9 "$old_b" 2>/dev/null
            fi
            rm -f "$BOT_PID_FILE" 2>/dev/null
        fi
    fi

    # Kiểm tra mạng/DNS Termux trước khi chạy bot (chống spam rate limit khi mạng rớt)
    while ! check_discord_network; do
        echo "[Watchdog] ⚠️ Không có kết nối tới Discord gateway (lỗi DNS/Mạng). Chờ 30s..."
        sleep 30
    done

    echo "[Watchdog] Đang chạy bot..."
    START_TIME=$(date +%s)
    python main.py --bot
    EXIT_CODE=$?
    END_TIME=$(date +%s)
    RUNTIME=$((END_TIME - START_TIME))
    rm -f "$BOT_PID_FILE" 2>/dev/null
    echo "[Watchdog] Bot đã dừng với mã thoát $EXIT_CODE (thời gian chạy: ${RUNTIME}s)."

    # Kiểm tra cờ dừng toàn bộ ngay sau khi bot thoát
    if [ -f "$STOPALL_FLAG" ]; then
        echo "[Watchdog] Đã nhận tín hiệu dừng toàn bộ (stopall.flag). Dừng watchdog."
        rm -f "$STOPALL_FLAG" 2>/dev/null
        exit 0
    fi

    # Nếu bot đã chạy ổn định trên 120s thì reset số lần restart
    if [ $RUNTIME -gt 120 ]; then
        restart_count=0
    fi

    backoff=$(get_backoff $restart_count)
    restart_count=$((restart_count + 1))
    echo "[Watchdog] ==========================================================="
    echo "[Watchdog] CẢNH BÁO: Bot bị dừng (mã $EXIT_CODE)! Đợi ${backoff}s trước khi restart..."
    echo "[Watchdog] ==========================================================="

    # Chờ với kiểm tra ngắt stopall tức thời (1s/tick)
    for ((s=0; s<backoff; s++)); do
        if [ -f "$STOPALL_FLAG" ]; then
            echo "[Watchdog] Đã nhận tín hiệu dừng toàn bộ trong khi đợi. Dừng watchdog."
            rm -f "$STOPALL_FLAG" 2>/dev/null
            exit 0
        fi
        sleep 1
    done

    # Kiểm tra cờ một lần nữa trước khi khởi động lại
    if [ -f "$STOPALL_FLAG" ]; then
        echo "[Watchdog] Đã nhận tín hiệu dừng toàn bộ trước khi restart. Dừng watchdog."
        rm -f "$STOPALL_FLAG" 2>/dev/null
        exit 0
    fi

    # Kiểm tra và đảm bảo Dashboard vẫn đang chạy (tránh chạy trùng lặp nếu dashboard đã online)
    dash_running=0
    if [ -f "$DASH_PID_FILE" ]; then
        d_pid=$(cat "$DASH_PID_FILE" 2>/dev/null)
        if [ -n "$d_pid" ] && kill -0 "$d_pid" 2>/dev/null; then
            dash_running=1
        else
            rm -f "$DASH_PID_FILE" 2>/dev/null
        fi
    fi
    # Kiểm tra cổng nếu PID file thất lạc
    if [ $dash_running -eq 0 ] && curl -sf --max-time 3 "http://127.0.0.1:5000/health" >/dev/null 2>&1; then
        dash_running=1
    fi

    if [ $dash_running -eq 0 ]; then
        echo "[Watchdog] Dashboard đang tắt, khởi động lại Dashboard..."
        dash_log="data/dashboard.stdout.log"
        nohup python main.py --dashboard > "$dash_log" 2>&1 &
        DASH_NEW_PID=$!
        echo "$DASH_NEW_PID" > "$DASH_PID_FILE"
    fi

    echo "[Watchdog] Đang khởi động lại Bot Discord..."
done

# Dọn health-check khi thoát
kill $HEALTH_PID 2>/dev/null


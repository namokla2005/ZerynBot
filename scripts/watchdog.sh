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
TUNNEL_PID_FILE="data/cloudflared.pid"
TUNNEL_LOG="data/cloudflared.log"
# Cho phép chỉ định binary (vd bản tải tay trong ~/bin) mà không phải sửa script.
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-cloudflared}"
STOPALL_FLAG="data/stopall.flag"
mkdir -p data
termux-wake-lock 2>/dev/null

# ─── Chống PID reuse sau khi máy khởi động lại ───────────────────────────────────
# `kill -0` chỉ trả lời 'còn tiến trình mang PID này', KHÔNG xác nhận nó là của chúng ta.
# Sau một lần reboot, số trong data/*.pid rất có thể đã do tiến trình khác kế -> SIGTERM
# vào đó là giết nhầm tiến trình của người dùng khác trên máy (và watchdog còn tưởng
# dashboard/bot 'vẫn đang chạy' mà không khởi động lại chúng).
pid_is() {   # pid_is <pid> <chuoi-phai-co-trong-cmdline>
    _pid="$1"; _needle="$2"
    [ -n "$_pid" ] || return 1
    [ -r "/proc/$_pid/cmdline" ] || return 1
    _cmdline=$(tr '\0' ' ' < "/proc/$_pid/cmdline" 2>/dev/null)
    case "$_needle" in
        # Khớp basename của script, không khớp chuỗi con trong cmdline của editor.
        *watchdog.sh) printf '%s' "$_cmdline" | grep -Eq '(^|/)watchdog\.sh( |$)' ;;
        *) printf '%s' "$_cmdline" | grep -Fq -- "$_needle" ;;
    esac
}

# ─── Cloudflared: watchdog giám sát luôn cả đường ra Internet ────────────────────
# Trước đây cloudflared do người dùng bật tay. Bot vẫn sống nếu tunnel chết, nên
# không lớp nào phát hiện: web zerynbot.id.vn tắt im lặng cho tới khi có người nhìn.
TUNNEL_HEALTH_URL="https://zerynbot.id.vn/health"
TUNNEL_CHECK_EVERY=3      # cứ 3 vòng health (~4.5 phút) mới thử URL công khai 1 lần
TUNNEL_FAIL_THRESHOLD=2   # 2 lần liên tiếp (~9 phút) → coi là tunnel chết hẳn

cloudflared_token() {
    if [ -n "$CLOUDFLARED_TOKEN" ]; then printf '%s' "$CLOUDFLARED_TOKEN"; return 0; fi
    [ -f ".env" ] || return 0
    # Bỏ CR (file .env có thể được sửa trên Windows) và nháy bao quanh nếu có.
    grep -m1 '^CLOUDFLARED_TOKEN=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r' | tr -d '"'
}

stop_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        t_pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        if [ -n "$t_pid" ] && pid_is "$t_pid" "cloudflared"; then
            kill -15 "$t_pid" 2>/dev/null
            for i in 1 2 3; do
                kill -0 "$t_pid" 2>/dev/null || break
                sleep 1
            done
            kill -9 "$t_pid" 2>/dev/null
        fi
        rm -f "$TUNNEL_PID_FILE" 2>/dev/null
    fi
}

ensure_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        t_pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        # Không chỉ `kill -0`: pid_is bắt buộc cmdline phải là cloudflared, nên sau
        # reboot PID bị tái sử dụng không làm watchdog tưởng tunnel còn sống.
        pid_is "$t_pid" "cloudflared" && return 0
    fi
    if ! command -v "$CLOUDFLARED_BIN" >/dev/null 2>&1; then
        echo "[Watchdog] Không có $CLOUDFLARED_BIN trong PATH — bỏ qua tunnel."
        return 1
    fi
    _tok=$(cloudflared_token)
    if [ -z "$_tok" ]; then
        echo "[Watchdog] Thiếu CLOUDFLARED_TOKEN trong .env — không dựng được tunnel."
        return 1
    fi
    echo "[Watchdog] Khởi động cloudflared..."
    # Token truyền qua ENV chứ KHÔNG qua argv: `ps` đọc được toàn bộ command line của
    # mọi tiến trình, còn /proc/<pid>/environ thì chỉ cùng user mới đọc được.
    nohup env TUNNEL_TOKEN="$_tok" "$CLOUDFLARED_BIN" tunnel run >> "$TUNNEL_LOG" 2>&1 &
    echo "$!" > "$TUNNEL_PID_FILE"
    sleep 3
    if ! pid_is "$(cat "$TUNNEL_PID_FILE" 2>/dev/null)" "cloudflared"; then
        echo "[Watchdog] cloudflared vừa khởi động đã thoát — xem $TUNNEL_LOG"
        return 1
    fi
    return 0
}

# ─── Đảm bảo duy nhất 1 watchdog chạy (Singleton Guard) ─────────────────────────
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$old_pid" ] && [ "$old_pid" != "$$" ] && pid_is "$old_pid" "watchdog.sh"; then
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
    for f in data/bot.stdout.log data/dashboard.stdout.log "$TUNNEL_LOG"; do
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
        if [ -n "$d_pid" ] && pid_is "$d_pid" "main.py --dashboard"; then
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
    local bot_fail=0
    local dash_fail=0
    local tick=0
    local tunnel_fail=0
    while true; do
        # Watchdog bị SIGKILL/OOM -> health_loop bị reparent về init. Không để nó
        # tiếp tục restart dashboard/kill bot mà không còn supervisor.
        # KHÔNG dùng $PPID: trong subshell bash giữ nguyên PPID của shell cha, nên
        # khi watchdog được main.py khởi động rồi main.py exit, $PPID = 1 dù watchdog
        # còn sống -> health_loop tự thoát oan. Đọc ppid thật của BASHPID.
        _hp=$(ps -o ppid= -p "${BASHPID:-$$}" 2>/dev/null | tr -d ' ')
        if [ "$_hp" = "1" ]; then
            exit 0
        fi
        sleep "$HEALTH_INTERVAL"
        tick=$((tick + 1))

        # ─── Cloudflared: tiến trình còn sống, và tunnel còn thật sự thông ──────
        # Kiểm tra tiến trình mỗi vòng (bắt được OOM/kill), còn URL công khai thì thưa
        # hơn vì nó đi vòng qua Cloudflare — không nên đập vào đó mỗi 90 giây.
        ensure_tunnel
        if [ $((tick % TUNNEL_CHECK_EVERY)) -eq 0 ]; then
            pub_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$TUNNEL_HEALTH_URL" 2>/dev/null)
            if [ "$pub_code" = "200" ]; then
                tunnel_fail=0
            else
                tunnel_fail=$((tunnel_fail + 1))
                echo "[Watchdog] Tunnel công khai trả '$pub_code' (lần $tunnel_fail/$TUNNEL_FAIL_THRESHOLD)"
                if [ "$tunnel_fail" -ge "$TUNNEL_FAIL_THRESHOLD" ]; then
                    echo "[Watchdog] Tunnel chết hẳn → dựng lại cloudflared"
                    stop_tunnel
                    ensure_tunnel
                    tunnel_fail=0
                fi
            fi
        fi

        # Một lần curl duy nhất, lấy cả mã HTTP. Bản cũ gọi `curl -sf` rồi mới gọi lại
        # để lấy http_code: khi dashboard CHẾT hẳn thì http_code rỗng, nhánh "503" không
        # bao giờ chạy và zerynbot.id.vn nằm ngoài không phục vụ vô thời hạn trong khi
        # bot vẫn khỏe (dashboard chỉ được start lại ở vòng chính, sau khi bot exit).
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null)

        if [ "$http_code" = "200" ]; then
            bot_fail=0
            dash_fail=0
            continue
        fi

        if [ -z "$http_code" ] || [ "$http_code" = "000" ]; then
            dash_fail=$((dash_fail + 1))
            bot_fail=0
            echo "[Watchdog] Dashboard không trả lời HTTP (lần $dash_fail) - đang restart..."
            if [ "$dash_fail" -ge 2 ]; then
                restart_dashboard
                dash_fail=0
            fi
            continue
        fi

        # 503 = dashboard sống nhưng bot offline/heartbeat cụt.
        # Mọi mã khác (500/502/404) = dashboard hỏng -> restart dashboard, KHÔNG kill bot.
        if [ "$http_code" = "503" ]; then
            dash_fail=0
            bot_fail=$((bot_fail + 1))
            echo "[Watchdog] Bot offline lần $bot_fail (http=503)"
            if [ "$bot_fail" -ge "$HEALTH_FAIL_THRESHOLD" ]; then
                echo "[Watchdog] Bot offline liên tục $bot_fail × ${HEALTH_INTERVAL}s → Gửi SIGTERM dừng bot..."
                if [ -f "$BOT_PID_FILE" ]; then
                    b_pid=$(cat "$BOT_PID_FILE" 2>/dev/null)
                    if [ -n "$b_pid" ] && pid_is "$b_pid" "main.py --bot"; then
                        kill -15 "$b_pid" 2>/dev/null
                        # Chờ tối đa 15 giây cho aiosqlite đóng WAL và Discord ngắt kết nối an toàn
                        for i in $(seq 1 15); do
                            if ! kill -0 "$b_pid" 2>/dev/null; then
                                break
                            fi
                            sleep 1
                        done
                        # Chỉ SIGKILL nếu PID vẫn còn là bot của mình (chống PID reuse)
                        if pid_is "$b_pid" "main.py --bot"; then
                            kill -9 "$b_pid" 2>/dev/null
                        fi
                    fi
                    rm -f "$BOT_PID_FILE" 2>/dev/null
                fi
                bot_fail=0
            fi
        else
            dash_fail=$((dash_fail + 1))
            bot_fail=0
            echo "[Watchdog] Dashboard lỗi HTTP $http_code (lần $dash_fail) - restart dashboard"
            if [ "$dash_fail" -ge 2 ]; then
                restart_dashboard
                dash_fail=0
            fi
        fi
    done
}

# Khởi động health-check nền & Dọn dẹp an toàn khi nhận tín hiệu dừng
health_loop &
HEALTH_PID=$!

# Dựng tunnel ngay khi watchdog lên, không đợi vòng health đầu tiên (90 giây).
ensure_tunnel

cleanup_and_exit() {
    [ -n "$HEALTH_PID" ] && kill -15 "$HEALTH_PID" 2>/dev/null
    if [ -f "$BOT_PID_FILE" ]; then
        b_pid=$(cat "$BOT_PID_FILE" 2>/dev/null)
        [ -n "$b_pid" ] && pid_is "$b_pid" "main.py --bot" && kill -15 "$b_pid" 2>/dev/null
    fi
    # Tunnel là con của watchdog: để nó sống sót sau khi watchdog chết sẽ thành orphan,
    # và lần khởi động sau sẽ có HAI cloudflared cùng tunnel -> tunnel flap liên tục.
    stop_tunnel
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
            if pid_is "$old_b" "main.py --bot"; then
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
        if [ -n "$d_pid" ] && pid_is "$d_pid" "main.py --dashboard"; then
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


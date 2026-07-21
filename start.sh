#!/bin/bash
# start.sh — Khởi động Bot, Dashboard, và Redis trên Termux

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Các file lưu Process ID để dễ tắt
PID_REDIS="data/redis.pid"
PID_BOT="data/bot.pid"
PID_DASH="data/dashboard.pid"

# Hàm tắt
stop_all() {
    echo "🔴 Đang dừng các services..."
    # Gửi thông báo webhook TRƯỚC KHI thực sự tắt các process
    python scripts/send_status.py stop
    
    if [ -f "$PID_BOT" ]; then kill $(cat "$PID_BOT") 2>/dev/null; rm "$PID_BOT"; echo "- Đã dừng Watchdog"; fi
    if [ -f "$PID_DASH" ]; then kill $(cat "$PID_DASH") 2>/dev/null; rm "$PID_DASH"; echo "- Đã dừng Dashboard script"; fi
    if [ -f "$PID_REDIS" ]; then kill $(cat "$PID_REDIS") 2>/dev/null; rm "$PID_REDIS"; echo "- Đã dừng Redis"; fi
    # Tắt luôn watchdog và các process con
    pkill -f "watchdog.sh" 2>/dev/null
    pkill -f "run_bot.py" 2>/dev/null
    pkill -f "run_dashboard.py" 2>/dev/null
    termux-wake-unlock 2>/dev/null
    echo "✅ Tất cả services đã tắt."
}

# Hàm check status
status() {
    echo "📊 Trạng thái hệ thống:"
    if [ -f "$PID_REDIS" ] && kill -0 $(cat "$PID_REDIS") 2>/dev/null; then echo "🟢 Redis: Đang chạy"; else echo "🔴 Redis: Không chạy"; fi
    if [ -f "$PID_BOT" ] && kill -0 $(cat "$PID_BOT") 2>/dev/null; then echo "🟢 Bot: Đang chạy"; else echo "🔴 Bot: Không chạy"; fi
    if [ -f "$PID_DASH" ] && kill -0 $(cat "$PID_DASH") 2>/dev/null; then echo "🟢 Dashboard: Đang chạy"; else echo "🔴 Dashboard: Không chạy"; fi
    exit 0
}

if [ "$1" == "--stop" ]; then stop_all; exit 0; fi
if [ "$1" == "--status" ]; then status; exit 0; fi
if [ "$1" == "--restart" ]; then 
    stop_all
    sleep 2
    echo ""
    echo "🔄 Đang khởi động lại..."
fi

termux-wake-lock 2>/dev/null
echo "🚀 Bắt đầu khởi động hệ thống Bot v2..."

# 1. Khởi động Redis
echo "⏳ Đang khởi động Redis..."
redis-server --ignore-warnings ARM64-COW-BUG --daemonize yes
# Lấy PID của redis-server
pgrep redis-server > "$PID_REDIS"
echo "✅ Redis đã chạy."

# 2. Khởi động Bot thông qua Watchdog
echo "⏳ Đang khởi động Bot (kèm Watchdog)..."
nohup bash scripts/watchdog.sh > data/bot.log 2>&1 &
echo $! > "$PID_BOT"
echo "✅ Bot đã chạy ngầm (xem data/bot.log)."

# 3. Khởi động Dashboard
echo "⏳ Đang khởi động Dashboard..."
nohup python run_dashboard.py > data/dashboard.log 2>&1 &
echo $! > "$PID_DASH"
echo "✅ Dashboard đã chạy ngầm (xem data/dashboard.log)."

echo "----------------------------------------"
echo "🎉 HỆ THỐNG ĐÃ SẴN SÀNG!"
echo "- Dashboard URL: http://localhost:5000"
echo "- Dùng lệnh './start.sh --status' để kiểm tra."
echo "- Dùng lệnh './start.sh --stop' để tắt toàn bộ."
echo "----------------------------------------"

# Gửi webhook thông báo hệ thống đã chạy
python scripts/send_status.py start

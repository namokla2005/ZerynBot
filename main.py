"""
main.py — Điểm vào duy nhất quản lý toàn bộ hệ thống ZerynBot V2.
Hỗ trợ các lệnh:
  python main.py              (Khởi chạy toàn bộ: Redis, Bot, Dashboard, Watchdog)
  python main.py --start      (Khởi chạy toàn bộ hệ thống)
  python main.py --stop       (Dừng sạch tất cả services và gửi webhook)
  python main.py --restart    (Tắt sạch và khởi động lại)
  python main.py --status     (Kiểm tra trạng thái các services)
  python main.py --bot        (Chỉ chạy Bot Discord)
  python main.py --dashboard  (Chỉ chạy Web Dashboard)
  python main.py --sync       (Khởi chạy Bot & đồng bộ Slash Commands)
"""

import sys
import os
import time
import subprocess
import signal
import asyncio

# Setup sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "bot"))

import config
from database import init_db

PID_DIR = os.path.join(BASE_DIR, "data")
PID_REDIS = os.path.join(PID_DIR, "redis.pid")
PID_BOT = os.path.join(PID_DIR, "bot.pid")
PID_DASH = os.path.join(PID_DIR, "dashboard.pid")


def _read_pid(file_path: str) -> int | None:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None


def _write_pid(file_path: str, pid: int):
    os.makedirs(PID_DIR, exist_ok=True)
    with open(file_path, "w") as f:
        f.write(str(pid))


def _remove_pid(file_path: str):
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass


def _is_pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            output = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], text=True)
            return str(pid) in output
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def stop_all():
    print("🔴 Đang dừng tất cả dịch vụ hệ thống...")
    
    # Gửi webhook thông báo trước khi dừng
    script_status = os.path.join(BASE_DIR, "scripts", "send_status.py")
    if os.path.exists(script_status):
        try:
            subprocess.run([sys.executable, script_status, "stop"], timeout=5)
        except Exception:
            pass

    for pid_file, name in [(PID_BOT, "Bot"), (PID_DASH, "Dashboard"), (PID_REDIS, "Redis")]:
        pid = _read_pid(pid_file)
        if pid and _is_pid_running(pid):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
                print(f" - Đã dừng {name} (PID {pid})")
            except Exception as e:
                print(f" - Lỗi khi dừng {name}: {e}")
        _remove_pid(pid_file)

    # Tắt watchdog / process con
    if os.name != "nt":
        subprocess.run("pkill -f 'watchdog.sh' 2>/dev/null", shell=True)
        subprocess.run("pkill -f 'main.py' 2>/dev/null", shell=True)
        subprocess.run("termux-wake-unlock 2>/dev/null", shell=True)

    print("✅ Tất cả dịch vụ đã dừng thành công.")


def print_status():
    print("📊 TRẠNG THÁI HỆ THỐNG ZERYNBOT V2:")
    
    redis_pid = _read_pid(PID_REDIS)
    bot_pid = _read_pid(PID_BOT)
    dash_pid = _read_pid(PID_DASH)

    print(f"🟢 Redis:      {'Đang chạy (PID ' + str(redis_pid) + ')' if _is_pid_running(redis_pid) else '🔴 Không chạy'}")
    print(f"🟢 Bot:        {'Đang chạy (PID ' + str(bot_pid) + ')' if _is_pid_running(bot_pid) else '🔴 Không chạy'}")
    print(f"🟢 Dashboard:  {'Đang chạy (PID ' + str(dash_pid) + ')' if _is_pid_running(dash_pid) else '🔴 Không chạy'}")


def run_only_bot():
    print("[Bot] Khởi động Bot Discord v2...")
    from bot.bot import main as bot_main
    asyncio.run(bot_main())


def run_only_dashboard():
    print(f"[Dashboard] Khởi động tại http://0.0.0.0:5000...")
    init_db()
    from dashboard.app import app
    app.run(host="0.0.0.0", port=5000, debug=False)


def start_all():
    print("🚀 Bắt đầu khởi động toàn bộ hệ thống ZerynBot V2...")

    if os.name != "nt":
        subprocess.run("termux-wake-lock 2>/dev/null", shell=True)

    # 1. Khởi động Redis
    print("⏳ [1/3] Đang khởi động Redis...")
    try:
        if os.name != "nt":
            subprocess.run("redis-server --ignore-warnings ARM64-COW-BUG --daemonize yes", shell=True)
            res = subprocess.check_output("pgrep redis-server", shell=True, text=True).strip().splitlines()
            if res:
                _write_pid(PID_REDIS, int(res[0]))
        print("✅ Redis ready.")
    except Exception as e:
        print(f"⚠️ Redis warning: {e}")

    # 2. Khởi động Bot (kèm Watchdog)
    print("⏳ [2/3] Đang khởi động Bot Discord (Watchdog)...")
    bot_log = os.path.join(PID_DIR, "bot.log")
    os.makedirs(PID_DIR, exist_ok=True)
    
    if os.name == "nt":
        p_bot = subprocess.Popen([sys.executable, "main.py", "--bot"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        _write_pid(PID_BOT, p_bot.pid)
    else:
        watchdog_script = os.path.join(BASE_DIR, "scripts", "watchdog.sh")
        if os.path.exists(watchdog_script):
            p_bot = subprocess.Popen(f"nohup bash {watchdog_script} > {bot_log} 2>&1 &", shell=True)
        else:
            p_bot = subprocess.Popen(f"nohup python main.py --bot > {bot_log} 2>&1 &", shell=True)
        time.sleep(1)
        res = subprocess.check_output("pgrep -f 'main.py --bot'", shell=True, text=True).strip().splitlines()
        if res:
            _write_pid(PID_BOT, int(res[0]))

    # 3. Khởi động Dashboard
    print("⏳ [3/3] Đang khởi động Web Dashboard...")
    dash_log = os.path.join(PID_DIR, "dashboard.log")
    if os.name == "nt":
        p_dash = subprocess.Popen([sys.executable, "main.py", "--dashboard"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        _write_pid(PID_DASH, p_dash.pid)
    else:
        p_dash = subprocess.Popen(f"nohup python main.py --dashboard > {dash_log} 2>&1 &", shell=True)
        time.sleep(1)
        res = subprocess.check_output("pgrep -f 'main.py --dashboard'", shell=True, text=True).strip().splitlines()
        if res:
            _write_pid(PID_DASH, int(res[0]))

    print("--------------------------------------------------")
    print("🎉 HỆ THỐNG ĐÃ KHỞI ĐỘNG THÀNH CÔNG!")
    print(f"- Web Dashboard: http://localhost:5000")
    print(f"- Dùng 'python main.py --status' để kiểm tra.")
    print(f"- Dùng 'python main.py --stop' để tắt hệ thống.")
    print("--------------------------------------------------")

    # Send Webhook start notification
    script_status = os.path.join(BASE_DIR, "scripts", "send_status.py")
    if os.path.exists(script_status):
        try:
            subprocess.run([sys.executable, script_status, "start"], timeout=5)
        except Exception:
            pass


def main():
    args = [a.lower() for a in sys.argv[1:]]

    if "--stop" in args:
        stop_all()
        sys.exit(0)
    elif "--status" in args:
        print_status()
        sys.exit(0)
    elif "--restart" in args:
        stop_all()
        time.sleep(2)
        print("\n🔄 Đang khởi động lại...")
        start_all()
        sys.exit(0)
    elif "--bot" in args:
        run_only_bot()
    elif "--dashboard" in args:
        run_only_dashboard()
    else:
        # Default start all
        start_all()


if __name__ == "__main__":
    main()

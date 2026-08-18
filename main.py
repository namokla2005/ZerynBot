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
  python main.py --sync       (Chạy Bot & đồng bộ lại Slash Commands với Discord)
"""

import sys
import os
import time
import subprocess
import signal
import asyncio

# Force UTF-8 output on all platforms (prevents UnicodeEncodeError on Windows cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # Python <3.7 fallback

# Setup sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "bot"))

import config
from database import init_db

PID_DIR = os.path.join(BASE_DIR, "data")
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
    print("[Main] Stopping all system services...")
    
    # Gửi webhook thông báo trước khi dừng
    script_status = os.path.join(BASE_DIR, "scripts", "send_status.py")
    if os.path.exists(script_status):
        try:
            subprocess.run([sys.executable, script_status, "stop"], timeout=5)
        except Exception:
            pass

    for pid_file, name in [(PID_BOT, "Bot"), (PID_DASH, "Dashboard")]:
        pid = _read_pid(pid_file)
        if pid and _is_pid_running(pid):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
                print(f" - Stopped {name} (PID {pid})")
            except Exception as e:
                print(f" - Error stopping {name}: {e}")
        _remove_pid(pid_file)

    # Tắt watchdog / process con (loại trừ PID của chính tiến trình hiện tại)
    if os.name != "nt":
        my_pid = os.getpid()
        subprocess.run("pkill -f 'watchdog.sh' 2>/dev/null", shell=True)
        try:
            res = subprocess.check_output("pgrep -f 'main.py'", shell=True, text=True).strip().splitlines()
            for p in res:
                if p.isdigit() and int(p) != my_pid:
                    subprocess.run(f"kill -9 {p} 2>/dev/null", shell=True)
        except Exception:
            pass
        subprocess.run("termux-wake-unlock 2>/dev/null", shell=True)

    print("[Main] All services stopped successfully.")


def get_live_bot_pid() -> int | None:
    """Tìm PID chính xác của Bot đang chạy (kể cả khi Watchdog vừa restart)."""
    # 1. Kiểm tra file bot.pid
    pid = _read_pid(PID_BOT)
    if pid and _is_pid_running(pid):
        return pid

    # 2. Kiểm tra file data/health.json do Bot ghi
    health_file = os.path.join(PID_DIR, "health.json")
    if os.path.exists(health_file):
        try:
            with open(health_file, "r", encoding="utf-8") as f:
                h = json.load(f)
                h_pid = h.get("pid")
                if h_pid and _is_pid_running(h_pid):
                    _write_pid(PID_BOT, h_pid)
                    return h_pid
        except Exception:
            pass

    # 3. Quét tiến trình hệ thống (Linux / Termux fallback)
    if os.name != "nt":
        try:
            res = subprocess.check_output("pgrep -f 'main.py --bot'", shell=True, text=True).strip().splitlines()
            if not res:
                res = subprocess.check_output("pgrep -f 'bot/bot.py'", shell=True, text=True).strip().splitlines()
            for p in res:
                if p.isdigit() and _is_pid_running(int(p)):
                    live_pid = int(p)
                    _write_pid(PID_BOT, live_pid)
                    return live_pid
        except Exception:
            pass

    return None


def get_live_dash_pid() -> int | None:
    """Tìm PID chính xác của Dashboard đang chạy."""
    pid = _read_pid(PID_DASH)
    if pid and _is_pid_running(pid):
        return pid

    if os.name != "nt":
        try:
            res = subprocess.check_output("pgrep -f 'main.py --dashboard'", shell=True, text=True).strip().splitlines()
            for p in res:
                if p.isdigit() and _is_pid_running(int(p)):
                    live_pid = int(p)
                    _write_pid(PID_DASH, live_pid)
                    return live_pid
        except Exception:
            pass

    return None


def print_status():
    print("[Status] ZerynBot V2 System Status:")
    
    bot_pid = get_live_bot_pid()
    dash_pid = get_live_dash_pid()

    bot_status   = f"RUNNING (PID {bot_pid})" if bot_pid else "STOPPED"
    dash_status  = f"RUNNING (PID {dash_pid})" if dash_pid else "STOPPED"
    print(f"  RAM Cache: IN-MEMORY (Pure Python)")
    print(f"  Bot:       {bot_status}")
    print(f"  Dashboard: {dash_status}")


def run_only_bot():
    print("[Bot] Starting Bot Discord v2...")
    _write_pid(PID_BOT, os.getpid())
    try:
        from bot.bot import main as bot_main
    except ModuleNotFoundError:
        from bot import main as bot_main
    try:
        asyncio.run(bot_main())
    finally:
        _remove_pid(PID_BOT)


def run_only_dashboard():
    print("[Dashboard] Starting at http://0.0.0.0:5000...")
    _write_pid(PID_DASH, os.getpid())
    init_db()
    try:
        from dashboard.app import app
        app.run(host="0.0.0.0", port=5000, debug=False)
    finally:
        _remove_pid(PID_DASH)


def start_all():
    print("[Main] Starting full system ZerynBot V2...")

    if os.name != "nt":
        subprocess.run("termux-wake-lock 2>/dev/null", shell=True)

    # 1. Khởi động Bot (kèm Watchdog)
    print("[1/2] Starting Bot Discord (Watchdog)...")
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

    # 2. Khởi động Dashboard
    print("[2/2] Starting Dashboard...")
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
    print("[Main] System started successfully!")
    print("- Web Dashboard: http://localhost:5000")
    print("- Run 'python main.py --status' to check status.")
    print("- Run 'python main.py --stop' to stop system.")
    print("--------------------------------------------------")

    # Send Webhook start notification
    script_status = os.path.join(BASE_DIR, "scripts", "send_status.py")
    if os.path.exists(script_status):
        try:
            subprocess.run([sys.executable, script_status, "start"], timeout=5)
        except Exception:
            pass


def run_system_test():
    print("[Tester] Running Self-Diagnostic Tester...")
    try:
        from tester import SystemTester
    except ImportError:
        print("[Tester] WARNING: tester.py not found, skipping self-test.")
        return True
    success = asyncio.run(SystemTester.run_all_tests())
    return success


def main():
    args = [a.lower() for a in sys.argv[1:]]

    if "--stop" in args:
        stop_all()
        sys.exit(0)
    elif "--status" in args:
        print_status()
        sys.exit(0)
    elif "--test" in args:
        run_system_test()
        sys.exit(0)
    elif "--restart" in args:
        stop_all()
        time.sleep(2)
        print("\n[Main] Restarting system...")
        start_all()
        sys.exit(0)
    elif "--bot" in args:
        run_only_bot()
    elif "--sync" in args:
        # Chạy bot + đồng bộ slash commands (đăng ký lại lên Discord)
        sys.argv.append("--sync")  # truyền tiếp cho bot.py setup_hook()
        run_only_bot()
    elif "--dashboard" in args:
        run_only_dashboard()
    else:
        # Default start all
        start_all()


if __name__ == "__main__":
    main()

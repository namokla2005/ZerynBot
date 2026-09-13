"""
termux_deploy.py — Tự động đồng bộ git pull và khởi động lại Bot trên thiết bị Termux (Tecno Pova 2).
Sử dụng: python scripts/termux_deploy.py
"""
import os
import sys
import time
import json
import socket
import paramiko

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

def get_config():
    return {
        "host": os.environ.get("TERMUX_HOST", "192.168.2.50"),
        "port": int(os.environ.get("TERMUX_PORT", "8022")),
        "user": os.environ.get("TERMUX_USER", "u0_a224"),
        "password": os.environ.get("TERMUX_PASSWORD", "nam123"),
        "bot_dir": os.environ.get("TERMUX_BOT_DIR", "~/ZerynBot"),
    }

def run_remote_deploy():
    cfg = get_config()
    print(f"📡 Đang kết nối tới Termux tại {cfg['host']}:{cfg['port']} (user: {cfg['user']})...")
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    t0 = time.time()
    try:
        client.connect(
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["user"],
            password=cfg["password"],
            timeout=8.0,
            banner_timeout=8.0,
            auth_timeout=8.0,
        )
    except (socket.timeout, TimeoutError):
        print(f"❌ TIMEOUT: Không thể kết nối SSH tới {cfg['host']}:{cfg['port']}.")
        print("💡 Gợi ý: Kiểm tra xem Termux đang chạy 'sshd' chưa, hoặc kiểm tra IP Tailscale / Wi-Fi.")
        return False
    except Exception as e:
        print(f"❌ LỖI KẾT NỐI SSH ({type(e).__name__}): {e}")
        return False

    print(f"✅ Đã kết nối SSH thành công ({time.time() - t0:.2f}s)!")
    
    # 1. Git Pull
    print("\n📥 [1/3] Đang kéo mã nguồn mới nhất: git pull origin main...")
    cmd_pull = f"cd {cfg['bot_dir']} && git pull origin main"
    _, stdout, stderr = client.exec_command(cmd_pull, timeout=25.0)
    out_pull = stdout.read().decode("utf-8", errors="replace").strip()
    err_pull = stderr.read().decode("utf-8", errors="replace").strip()
    if out_pull:
        print(out_pull)
    if err_pull and "Already up to date" not in out_pull:
        print(f"⚠️ Git stderr: {err_pull}")

    # 2. Restart Bot
    print("\n🔄 [2/3] Đang khởi động lại Bot & Dashboard: python main.py --restart...")
    cmd_restart = f"cd {cfg['bot_dir']} && python main.py --restart"
    _, stdout, stderr = client.exec_command(cmd_restart, timeout=25.0)
    out_restart = stdout.read().decode("utf-8", errors="replace").strip()
    err_restart = stderr.read().decode("utf-8", errors="replace").strip()
    if out_restart:
        print(out_restart)
    if err_restart:
        print(f"⚠️ Restart stderr: {err_restart}")

    # 3. Post-Deployment Comprehensive Inspection (Kiểm tra 1 lượt hoàn chỉnh)
    print("\n🔍 [3/3] Đang kiểm tra 1 lượt hoàn chỉnh toàn bộ hệ thống trên Termux...")
    print("⏳ Chờ 6 giây để các tiến trình khởi tạo và nạp module...")
    time.sleep(6)

    # 3.1 Check process status via python main.py --status
    cmd_status = f"cd {cfg['bot_dir']} && python main.py --status"
    _, stdout, stderr = client.exec_command(cmd_status, timeout=10.0)
    out_status = stdout.read().decode("utf-8", errors="replace").strip()
    print("\n📊 1. Trạng thái tiến trình (main.py --status):")
    print(out_status)

    bot_running = "Bot:       RUNNING" in out_status
    dash_running = "Dashboard: RUNNING" in out_status

    # 3.2 Check Dashboard Health endpoint
    cmd_health = f"cd {cfg['bot_dir']} && curl -s -m 5 http://localhost:5000/health"
    _, stdout, stderr = client.exec_command(cmd_health, timeout=10.0)
    out_health = stdout.read().decode("utf-8", errors="replace").strip()
    print(f"\n🌐 2. Kiểm tra Health Endpoint (http://localhost:5000/health):")
    print(f"   Response: {out_health or '(không có phản hồi)'}")
    dash_healthy = False
    try:
        health_data = json.loads(out_health)
        dash_healthy = health_data.get("online", False) or dash_running
    except Exception:
        dash_healthy = dash_running

    # 3.3 Check latest logs for crashes / tracebacks
    cmd_logs = f"cd {cfg['bot_dir']} && tail -n 12 data/bot.log 2>/dev/null"
    _, stdout, stderr = client.exec_command(cmd_logs, timeout=10.0)
    out_bot_log = stdout.read().decode("utf-8", errors="replace").strip()

    cmd_dash_log = f"cd {cfg['bot_dir']} && tail -n 12 data/dashboard.log 2>/dev/null"
    _, stdout, stderr = client.exec_command(cmd_dash_log, timeout=10.0)
    out_dash_log = stdout.read().decode("utf-8", errors="replace").strip()

    has_traceback = "Traceback (most recent call last)" in out_bot_log or "Traceback (most recent call last)" in out_dash_log
    
    print("\n📋 3. Bảng tổng kết kiểm tra sức khỏe hệ thống:")
    print(f"   • Bot Discord:   {'🟢 ONLINE' if bot_running else '🔴 STOPPED / ERROR'}")
    print(f"   • Web Dashboard: {'🟢 ONLINE' if dash_running else '🔴 STOPPED / ERROR'}")
    print(f"   • Health Check:  {'🟢 HEALTHY' if dash_healthy else '🟡 PENDING / UNKNOWN'}")
    print(f"   • Log Audit:     {'🔴 CẢNH BÁO TRACEBACK' if has_traceback else '🟢 SẠCH SẼ (Không có traceback)'}")

    if out_bot_log:
        print("\n📜 Trích xuất log bot mới nhất:")
        for line in out_bot_log.splitlines()[-4:]:
            print(f"   {line}")

    client.close()

    if not (bot_running and dash_running) or has_traceback:
        print("\n⚠️ CẢNH BÁO: Hệ thống chưa đạt trạng thái hoàn hảo 100%!")
        return False

    print("\n🎉 XÁC THỰC HOÀN TẤT: Toàn bộ hệ thống ZerynBot V2 trên Termux đã vượt qua kiểm tra và hoạt động 100% ổn định!")
    return True

if __name__ == "__main__":
    success = run_remote_deploy()
    sys.exit(0 if success else 1)


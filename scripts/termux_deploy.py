"""
termux_deploy.py — Tự động đồng bộ git pull và khởi động lại Bot trên thiết bị Termux (Tecno Pova 2).
Sử dụng: python scripts/termux_deploy.py
"""
import os
import sys
import time
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
    print("📥 [1/2] Đang kéo mã nguồn mới nhất: git pull origin main...")
    cmd_pull = f"cd {cfg['bot_dir']} && git pull origin main"
    _, stdout, stderr = client.exec_command(cmd_pull, timeout=25.0)
    out_pull = stdout.read().decode("utf-8", errors="replace").strip()
    err_pull = stderr.read().decode("utf-8", errors="replace").strip()
    if out_pull:
        print(out_pull)
    if err_pull and "Already up to date" not in out_pull:
        print(f"⚠️ Git stderr: {err_pull}")

    # 2. Restart Bot
    print("\n🔄 [2/2] Đang khởi động lại Bot & Dashboard: python main.py --restart...")
    cmd_restart = f"cd {cfg['bot_dir']} && python main.py --restart"
    _, stdout, stderr = client.exec_command(cmd_restart, timeout=25.0)
    out_restart = stdout.read().decode("utf-8", errors="replace").strip()
    err_restart = stderr.read().decode("utf-8", errors="replace").strip()
    if out_restart:
        print(out_restart)
    if err_restart:
        print(f"⚠️ Restart stderr: {err_restart}")

    client.close()
    print("\n🎉 HOÀN TẤT DEPLOY: Mã nguồn trên Termux đã được đồng bộ và khởi động lại!")
    return True

if __name__ == "__main__":
    success = run_remote_deploy()
    sys.exit(0 if success else 1)

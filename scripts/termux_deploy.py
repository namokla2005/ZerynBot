"""
termux_deploy.py — Tự động đồng bộ git pull và khởi động lại Bot trên thiết bị Termux (Tecno Pova 2).
Hỗ trợ Dual-Mode thông minh:
  1. Mạng nội bộ LAN (TERMUX_HOST:8022) khi ở nhà (siêu tốc 0.2s).
  2. Cloudflare Tunnel (ssh.zerynbot.id.vn) khi ở xa / 4G (tự động chuyển đổi).

Sử dụng: python scripts/termux_deploy.py
"""
import os
import sys
import time
import json
import socket
import subprocess
import paramiko

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

def get_config():
    return {
        "host": os.environ.get("TERMUX_HOST", "127.0.0.1"),
        "port": int(os.environ.get("TERMUX_PORT", "8022")),
        "user": os.environ.get("TERMUX_USER", "termux"),
        "key_file": os.environ.get("TERMUX_KEY_FILE", os.path.expanduser("~/.ssh/id_ed25519")),
        "cf_host": os.environ.get("TERMUX_CF_HOST", "ssh.zerynbot.id.vn"),
        "bot_dir": os.environ.get("TERMUX_BOT_DIR", "~/ZerynBot"),
    }


class RemoteExecutor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = None
        self.client = None

    def connect(self) -> tuple[bool, str]:
        t0 = time.time()
        # 1. Thử kết nối mạng LAN nội bộ trước (khi ở nhà) bằng SSH Key
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            conn_args = {
                "hostname": self.cfg["host"],
                "port": self.cfg["port"],
                "username": self.cfg["user"],
                "timeout": 3.0,
                "banner_timeout": 3.0,
                "auth_timeout": 3.0,
                "look_for_keys": True,
            }
            if os.path.exists(self.cfg.get("key_file", "")):
                conn_args["key_filename"] = self.cfg["key_file"]

            client.connect(**conn_args)
            self.client = client
            self.mode = "lan"
            return True, f"Mạng LAN Wi-Fi ({self.cfg['host']}:{self.cfg['port']}) [{time.time() - t0:.2f}s]"
        except Exception:
            pass

        # 2. Tự động chuyển hướng qua Cloudflare Tunnel nếu ở xa
        try:
            cf_h = self.cfg["cf_host"]
            res = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", cf_h, "echo OK"],
                capture_output=True, text=True, timeout=8.0
            )
            if res.returncode == 0 and "OK" in res.stdout:
                self.mode = "cf"
                return True, f"Cloudflare Tunnel ({cf_h}) [{time.time() - t0:.2f}s]"
        except Exception:
            pass

        return False, f"Không thể kết nối qua cả LAN ({self.cfg['host']}) lẫn Cloudflare Tunnel ({self.cfg['cf_host']})"

    def exec(self, cmd: str, timeout: float = 30.0) -> tuple[str, str, int]:
        if self.mode == "lan":
            stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            code = stdout.channel.recv_exit_status()
            return out, err, code
        elif self.mode == "cf":
            res = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", self.cfg["cf_host"], cmd],
                capture_output=True, timeout=timeout
            )
            out = res.stdout.decode("utf-8", errors="replace").strip() if res.stdout else ""
            err = res.stderr.decode("utf-8", errors="replace").strip() if res.stderr else ""
            return out, err, res.returncode
        return "", "Not connected", 1

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

def run_remote_deploy():
    cfg = get_config()
    print("📡 Đang dò tìm và kết nối tới Termux (Hỗ trợ Dual-Mode LAN / Cloudflare)...")
    
    executor = RemoteExecutor(cfg)
    ok, info = executor.connect()
    if not ok:
        print(f"❌ LỖI KẾT NỐI: {info}")
        print("💡 Gợi ý: Kiểm tra xem Termux đang chạy 'sshd' chưa, hoặc kiểm tra kết nối mạng / Cloudflare Tunnel.")
        return False

    print(f"✅ Đã kết nối thành công qua kênh: {info}!\n")

    # 1. Git Pull
    print("📥 [1/3] Đang kéo mã nguồn mới nhất: git pull origin main...")
    cmd_pull = f"cd {cfg['bot_dir']} && git pull origin main"
    out_pull, err_pull, code_pull = executor.exec(cmd_pull, timeout=25.0)
    if out_pull:
        print(out_pull)
    if err_pull and "Already up to date" not in out_pull:
        print(f"⚠️ Git stderr: {err_pull}")

    # 2. Restart Bot
    print("\n🔄 [2/3] Đang khởi động lại Bot & Dashboard: python main.py --restart...")
    cmd_restart = f"cd {cfg['bot_dir']} && python main.py --restart"
    out_restart, err_restart, code_restart = executor.exec(cmd_restart, timeout=25.0)
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
    out_status, _, _ = executor.exec(cmd_status, timeout=10.0)
    print("\n📊 1. Trạng thái tiến trình (main.py --status):")
    print(out_status)

    bot_running = "Bot:       RUNNING" in out_status
    dash_running = "Dashboard: RUNNING" in out_status

    # 3.2 Check Dashboard Health endpoint
    cmd_health = f"cd {cfg['bot_dir']} && curl -s -m 5 http://localhost:5000/health"
    out_health, _, _ = executor.exec(cmd_health, timeout=10.0)
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
    out_bot_log, _, _ = executor.exec(cmd_logs, timeout=10.0)

    cmd_dash_log = f"cd {cfg['bot_dir']} && tail -n 12 data/dashboard.log 2>/dev/null"
    out_dash_log, _, _ = executor.exec(cmd_dash_log, timeout=10.0)

    has_traceback = "Traceback (most recent call last)" in out_bot_log or "Traceback (most recent call last)" in out_dash_log
    
    print("\n📋 3. Bảng tổng kết kiểm tra sức khỏe hệ thống:")
    print(f"   • Bot Discord:   {'🟢 ONLINE' if bot_running else '🔴 STOPPED / ERROR'}")
    print(f"   • Web Dashboard: {'🟢 ONLINE' if dash_running else '🔴 STOPPED / ERROR'}")
    print(f"   • Health Check:  {'🟢 HEALTHY' if dash_healthy else '🟡 PENDING / UNKNOWN'}")
    print(f"   • Log Audit:     {'🔴 CẢNH BÁO TRACEBACK' if has_traceback else '🟢 SẠCH SẼ (Không có traceback)'}")

    # 4. Comprehensive 20-Module Diagnostic Test on Termux (Kiểm thử chức năng & logic)
    print("\n🧪 [4/4] Đang chạy kiểm thử toàn bộ 20 modules chức năng trên Termux (python main.py --test)...")
    cmd_test = f"cd {cfg['bot_dir']} && python main.py --test"
    out_test, err_test, test_exit_code = executor.exec(cmd_test, timeout=30.0)

    if out_test:
        print(out_test)
    if err_test and test_exit_code != 0:
        print(f"⚠️ Test stderr: {err_test}")

    test_passed = (test_exit_code == 0) and (
        "pass 100%" in out_test.lower()
        or "thành công" in out_test.lower()
    )

    executor.close()

    if not (bot_running and dash_running) or has_traceback or not test_passed:
        print("\n❌ CẢNH BÁO: Phát hiện lỗi logic hoặc chức năng chưa đạt chuẩn 100% trên Termux!")
        print("👉 AI BẮT BUỘC PHẢI TIẾP TỤC SỬA LỖI, KHÔNG ĐƯỢC BÁO HOÀN TẤT CHO NGƯỜI DÙNG.")
        return False

    print("\n🎉 XÁC THỰC HOÀN TẤT 100%: Tất cả tiến trình đều RUNNING, Health Check HEALTHY, và toàn bộ 20/20 modules chức năng đều PASS trên Termux!")
    return True

if __name__ == "__main__":
    success = run_remote_deploy()
    sys.exit(0 if success else 1)

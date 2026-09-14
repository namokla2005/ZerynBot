"""
termux_mcp.py — MCP Server điều khiển & giám sát thiết bị Termux (Tecno Pova 2) từ xa.
Tương thích chuẩn Model Context Protocol (MCP 2.x) qua Stdio Transport.
"""
import os
import sys
import time
import socket
import paramiko
from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="termux-manager",
    title="ZerynBot Termux SSH Manager",
    description="Điều khiển, giám sát CPU/RAM, đọc log và quản lý tiến trình ZerynBot V2 trên thiết bị Android Termux.",
    version="1.0.0",
)

def _get_config():
    return {
        "host": os.environ.get("TERMUX_HOST", "192.168.2.50"),
        "port": int(os.environ.get("TERMUX_PORT", "8022")),
        "user": os.environ.get("TERMUX_USER", "u0_a224"),
        "password": os.environ.get("TERMUX_PASSWORD", "nam123"),
        "bot_dir": os.environ.get("TERMUX_BOT_DIR", "~/ZerynBot"),
    }

def _run_ssh(cmd: str, timeout: float = 15.0) -> str:
    cfg = _get_config()
    # 1. Thử kết nối mạng LAN nội bộ trước (khi ở nhà)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["user"],
            password=cfg["password"],
            timeout=2.5,
            banner_timeout=2.5,
            auth_timeout=2.5,
        )
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out if out else err
    except Exception:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass

    # 2. Tự động chuyển hướng qua Cloudflare Tunnel khi ở xa (ssh.zerynbot.id.vn)
    try:
        import subprocess
        cf_host = os.environ.get("TERMUX_CF_HOST", "ssh.zerynbot.id.vn")
        res = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", cf_host, cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return res.stdout if res.stdout else res.stderr
    except Exception as e:
        return f"❌ LỖI KẾT NỐI (Cả LAN {cfg['host']} và Cloudflare Tunnel {os.environ.get('TERMUX_CF_HOST', 'ssh.zerynbot.id.vn')} đều thất bại): {e}"


@server.tool(name="termux_test_connection", description="Kiểm tra kết nối SSH tới thiết bị Termux (Tecno Pova 2)")
def termux_test_connection() -> str:
    """Kiểm tra xem thiết bị Termux có thể kết nối được ngay lúc này hay không."""
    cfg = _get_config()
    t0 = time.time()
    res = _run_ssh("echo 'PONG' && uname -a", timeout=5.0)
    elapsed = time.time() - t0
    if "PONG" in res:
        return f"✅ KẾT NỐI THÀNH CÔNG tới Termux ({cfg['host']}:{cfg['port']}) trong {elapsed:.2f}s!\n{res}"
    return res


@server.tool(name="termux_get_status", description="Xem tình trạng CPU, RAM (free -h) và tiến trình bot/watchdog đang chạy trên Termux")
def termux_get_status() -> str:
    """Lấy thông tin tài nguyên hệ thống và danh sách tiến trình Python/Watchdog."""
    cfg = _get_config()
    cmd = (
        "echo '=== THÔNG TIN BỘ NHỚ (RAM/SWAP) ===' && free -h && "
        "echo '\n=== TIẾN TRÌNH PYTHON & WATCHDOG ===' && ps -ef | grep -E 'python|watchdog|cloudflared' | grep -v grep && "
        "echo '\n=== THỜI GIAN HOẠT ĐỘNG (UPTIME) ===' && uptime"
    )
    return _run_ssh(cmd, timeout=8.0)


@server.tool(name="termux_read_logs", description="Đọc N dòng cuối của file log (bot.log hoặc dashboard.log) trên Termux")
def termux_read_logs(filename: str = "bot.log", lines: int = 60) -> str:
    """Đọc log từ thư mục data/ của bot trên Termux."""
    cfg = _get_config()
    # Chống path traversal
    safe_file = "bot.log" if "dash" not in filename.lower() else "dashboard.log"
    safe_lines = min(max(10, lines), 200)
    cmd = f"tail -n {safe_lines} {cfg['bot_dir']}/data/{safe_file}"
    return _run_ssh(cmd, timeout=8.0)


@server.tool(name="termux_system_restart", description="Khởi động lại toàn bộ hệ thống ZerynBot trên Termux (python main.py --restart)")
def termux_system_restart() -> str:
    """Khởi động lại toàn bộ hệ thống (Bot + Dashboard) qua main.py --restart."""
    cfg = _get_config()
    cmd = f"cd {cfg['bot_dir']} && python main.py --restart"
    return _run_ssh(cmd, timeout=20.0)


@server.tool(name="termux_system_stop", description="Dừng sạch toàn bộ hệ thống ZerynBot trên Termux (python main.py --stop)")
def termux_system_stop() -> str:
    """Dừng sạch toàn bộ services qua main.py --stop."""
    cfg = _get_config()
    cmd = f"cd {cfg['bot_dir']} && python main.py --stop"
    return _run_ssh(cmd, timeout=15.0)


@server.tool(name="termux_system_test", description="Chạy bộ tự chẩn đoán lỗi hệ thống trên Termux (python main.py --test)")
def termux_system_test() -> str:
    """Chạy SystemTester qua main.py --test."""
    cfg = _get_config()
    cmd = f"cd {cfg['bot_dir']} && python main.py --test"
    return _run_ssh(cmd, timeout=30.0)


@server.tool(name="termux_git_pull", description="Kéo mã nguồn mới nhất từ GitHub về Termux (git pull origin main)")
def termux_git_pull() -> str:
    """Kéo code mới về Termux."""
    cfg = _get_config()
    cmd = f"cd {cfg['bot_dir']} && git pull origin main"
    return _run_ssh(cmd, timeout=20.0)


@server.tool(name="termux_run_command", description="Chạy một lệnh bash tùy ý trên thiết bị Termux")
def termux_run_command(command: str) -> str:
    """Chạy lệnh tùy chọn trên Termux."""
    cfg = _get_config()
    cmd = f"cd {cfg['bot_dir']} && {command}"
    return _run_ssh(cmd, timeout=30.0)


if __name__ == "__main__":
    server.run(transport="stdio")

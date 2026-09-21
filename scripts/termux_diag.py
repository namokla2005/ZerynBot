"""
termux_diag.py — Công cụ tự động kết nối Termux, thu thập toàn diện thông tin chẩn đoán lỗi (Log, Process, SQLite WAL, RAM).
Sử dụng: python scripts/termux_diag.py [--lines 60] [--json]
"""
import os
import sys
import time
import json
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.termux_deploy import RemoteExecutor, get_config

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def collect_termux_diagnostics(log_lines: int = 60) -> dict:
    """Truy cập Termux và thu thập toàn bộ dữ liệu thực tế."""
    cfg = get_config()
    executor = RemoteExecutor(cfg)
    ok, mode_str = executor.connect()

    diag = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "connection": {"success": ok, "mode": mode_str if ok else "FAILED"},
        "system_status": "",
        "processes": "",
        "memory": "",
        "sqlite_wal": "",
        "health_check": "",
        "bot_log_recent": "",
        "bot_log_tracebacks": "",
        "dashboard_log_recent": "",
        "error": None
    }

    if not ok:
        diag["error"] = f"Không thể kết nối tới Termux: {mode_str}"
        return diag

    bot_dir = cfg["bot_dir"]

    def _cmd(c: str, timeout: float = 10.0) -> str:
        out, err, _ = executor.exec(c, timeout=timeout)
        return out if out else err

    # 1. Trạng thái tiến trình & Uptime
    diag["system_status"] = _cmd(f"cd {bot_dir} && python main.py --status")

    # 2. Danh sách tiến trình Python & Watchdog
    diag["processes"] = _cmd("ps -ef | grep -E 'python|watchdog' | grep -v grep")

    # 3. Tài nguyên RAM & Swap
    diag["memory"] = _cmd("free -h && uptime")

    # 4. Kích thước SQLite Database & WAL file
    diag["sqlite_wal"] = _cmd(f"ls -lh {bot_dir}/data/bot.db* 2>/dev/null || true")

    # 5. Health Check Endpoint
    diag["health_check"] = _cmd("curl -s http://localhost:5000/health || echo 'HEALTH_OFFLINE'")

    # 6. Đọc log bot gần nhất
    diag["bot_log_recent"] = _cmd(f"tail -n {log_lines} {bot_dir}/data/bot.log 2>/dev/null || echo 'NO_BOT_LOG'")

    # 7. Trích xuất các lỗi Traceback nếu có trong 200 dòng cuối
    traceback_cmd = f"tail -n 200 {bot_dir}/data/bot.log 2>/dev/null | grep -E 'Traceback|Error|CRITICAL|Exception' -B 1 -A 5 | tail -n 40 || true"
    diag["bot_log_tracebacks"] = _cmd(traceback_cmd)

    # 8. Đọc log dashboard gần nhất
    diag["dashboard_log_recent"] = _cmd(f"tail -n {min(40, log_lines)} {bot_dir}/data/dashboard.log 2>/dev/null || echo 'NO_DASH_LOG'")

    executor.close()
    return diag


def format_diagnostic_report(diag: dict) -> str:
    """Format hồ sơ chẩn đoán thành báo cáo trực quan cho AI và lập trình viên."""
    conn = diag.get("connection", {})
    if not conn.get("success"):
        return f"❌ LỖI KẾT NỐI TERMUX: {diag.get('error')}"

    lines = [
        "====================================================================",
        "🔍 HỒ SƠ THU THẬP DỮ LIỆU THỰC TẾ TỪ THIẾT BỊ TERMUX (TECNO POVA 2)",
        "====================================================================",
        f"⏱️ Thời điểm: {diag.get('timestamp')} | Kênh kết nối: {conn.get('mode')}",
        "",
        "📊 1. TRẠNG THÁI TIẾN TRÌNH (python main.py --status):",
        diag.get("system_status", "N/A").strip(),
        "",
        "⚙️ 2. TIẾN TRÌNH PYTHON HOẠT ĐỘNG (ps -ef):",
        diag.get("processes", "N/A").strip(),
        "",
        "🧠 3. TÀI NGUYÊN BỘ NHỚ (RAM / SWAP & Uptime):",
        diag.get("memory", "N/A").strip(),
        "",
        "🗄️ 4. TRẠNG THÁI CSDL SQLITE (DB & WAL Files):",
        diag.get("sqlite_wal", "N/A").strip(),
        "",
        "🌐 5. PHẢN HỒI HEALTH ENDPOINT (/health):",
        diag.get("health_check", "N/A").strip(),
        "",
        "📜 6. TRACEBACKS & LỖI GẦN NHẤT (Nếu có):",
        diag.get("bot_log_tracebacks", "").strip() or "🟢 Không phát hiện Traceback hay lỗi nghiêm trọng trong log gần nhất.",
        "",
        "📜 7. ĐOẠN LOG BOT GẦN NHẤT (bot.log):",
        diag.get("bot_log_recent", "N/A").strip(),
        "===================================================================="
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Thu thập thông tin chẩn đoán Termux.")
    parser.add_argument("--lines", type=int, default=60, help="Số dòng log cần đọc (mặc định 60)")
    parser.add_argument("--json", action="store_true", help="Xuất định dạng JSON thô")
    args = parser.parse_args()

    data = collect_termux_diagnostics(log_lines=args.lines)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_diagnostic_report(data))

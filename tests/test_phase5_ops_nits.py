"""Phase 5 — ba lỗi vận hành nhỏ nhưng chặn đường (L3, L4, L5).

Mỗi ca ở đây từng làm công cụ chẩn đoán vô dụng ĐÚNG lúc cần dùng nhất: script audit
crash trên console Windows, MCP Termux chết vì thiếu một package không bắt buộc, và
watchdog bắn SIGTERM vào PID của tiến trình khác sau một lần reboot.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(not BASH, reason="can bash (chi co tren Termux/CI Linux)")


# ─── L3: console cp1252 của Windows ăn mất chữ có dấu ─────────────────────────

def test_registry_audit_runs_on_a_cp1252_console():
    """Bug thật: chạy script ở Windows mà không set PYTHONIOENCODING -> UnicodeEncodeError."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "command_registry_audit.py")],
        capture_output=True, env=env, cwd=str(ROOT), timeout=180,
    )
    assert r.returncode == 0, (
        f"script crash trên console cp1252: {r.stderr.decode('utf-8', 'replace')[-400:]}"
    )
    assert b"128" in r.stdout, r.stdout[:200]


# ─── L4: thiếu paramiko không được giết cả MCP server ─────────────────────────

def test_run_ssh_falls_back_when_paramiko_is_broken(monkeypatch):
    """Trước đây paramiko nằm NGOÀI try -> thiếu nó là chết từ lúc import, tunnel vô dụng."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import termux_mcp

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("paramiko hong")

    monkeypatch.setattr(termux_mcp, "paramiko", _Boom, raising=False)

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, b"FALLBACK-OK", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = termux_mcp._run_ssh("echo ping", timeout=5.0)

    assert out == "FALLBACK-OK", out
    assert calls and calls[0][0] == "ssh", f"phải rơi xuống nhánh Cloudflare Tunnel: {calls}"


def test_paramiko_import_is_optional():
    src = (ROOT / "scripts" / "termux_mcp.py").read_text(encoding="utf-8")
    head = src.split("def ")[0]
    assert "except ImportError" in head, (
        "paramiko phải được import trong try — nó chỉ cần cho nhánh LAN"
    )


# ─── L5: watchdog phải chắc chắn PID là của mình trước khi kill ───────────────

def _bash(body_and_expr: str) -> int:
    """Chay ham pid_is() that trong watchdog.sh, khong ban lai ban copy."""
    script = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = script.index("pid_is() {")
    end = script.index("\n}", start) + 2
    r = subprocess.run(["bash", "-c", script[start:end] + "\n" + body_and_expr],
                       capture_output=True, timeout=30)
    return r.returncode


@needs_bash
def test_pid_is_accepts_a_real_matching_process():
    assert _bash("pid_is $$ bash") == 0, "phải nhận ra shell đang chạy (cmdline chứa 'bash')"


@needs_bash
def test_pid_is_rejects_dead_foreign_and_empty_pids():
    assert _bash("pid_is 999999 bash") != 0, "PID chết thì không được nhận"
    # Chuỗi cần tìm được GHÉP lúc chạy: viết thẳng ra thì nó nằm luôn trong cmdline của
    # shell đang được test và grep sẽ tự khớp chính nó.
    assert _bash("pid_is $$ \"$(printf 'zz%s' qqq)\"") != 0, "cmdline không khớp phải bị từ chối"
    assert _bash('pid_is "" bash') != 0, "PID rỗng phải bị từ chối"


def test_watchdog_kills_only_verified_pids():
    """`kill -0` một mình không chứng minh PID đó là bot/dashboard của mình.

    Mỗi dòng kill PID đọc từ data/*.pid phải nằm trong một nhánh `if pid_is <biến> ...`
    (quét ngược lại tối đa 16 dòng). Sau reboot, PID có thể đã do tiến trình khác kế.
    """
    lines = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8").splitlines()
    bad = []
    for i, line in enumerate(lines):
        m = re.search(r'kill -(?:15|9) "\$(old_pid|old_b|d_pid|b_pid)"', line)
        if not m:
            continue
        var = "$" + m.group(1)
        window = "\n".join(lines[max(0, i - 16):i + 1])
        if f'pid_is "{var}"' not in window:
            bad.append(f"{i + 1}: {line.strip()}")
    assert not bad, (
        "những chỗ kill chưa đi qua kiểm tra danh tính PID — sau reboot là giết nhầm:\n"
        + "\n".join(bad)
    )


@needs_bash
def test_watchdog_script_still_parses():
    r = subprocess.run([BASH, "-n", str(ROOT / "scripts" / "watchdog.sh")], capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]

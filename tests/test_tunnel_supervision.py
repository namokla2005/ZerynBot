# -*- coding: utf-8 -*-
"""Watchdog giám sát cloudflared — trước đây tunnel chết thì web tắt im lặng.

Test chạy CHÍNH các hàm trong scripts/watchdog.sh (không phải bản copy), trong một
sandbox có `cloudflared` giả nằm trên PATH.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(not BASH, reason="cần bash (Termux/CI Linux)")


def _functions() -> str:
    script = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = script.index("pid_is() {")
    end = script.index("# ─── Đảm bảo duy nhất 1 watchdog chạy")
    return script[start:end]


def _tunnel_vars() -> str:
    """Lấy đúng các biến TUNNEL_* từ script thật (đừng chép tay: đổi tên là test lạc)."""
    script = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = script.index('TUNNEL_PID_FILE="data/cloudflared.pid"')
    end = script.index("STOPALL_FLAG=")
    return script[start:end]


@pytest.fixture()
def sandbox(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "bin").mkdir()
    fake = tmp_path / "bin" / "fake-cloudflared"   # tên chứa "cloudflared" để pid_is khớp
    # LF, không phải CRLF: `#!/bin/sh` + `sleep 60\r` làm /bin/sh thoát ngay với
    # "invalid number" trên Linux/Termux (và Git Bash trên Windows cũng vậy).
    fake.write_bytes(b"#!/bin/sh\nsleep 60\n")
    fake.chmod(0o755)
    (tmp_path / ".env").write_text("CLOUDFLARED_TOKEN=tok-abc-123\n")
    return tmp_path


def _run(sandbox, body: str) -> subprocess.CompletedProcess:
    script = (
        f'cd "{sandbox.as_posix()}"\n'
        f'export PATH="{sandbox.as_posix()}/bin:$PATH"\n'
        f'export CLOUDFLARED_BIN="{sandbox.as_posix()}/bin/fake-cloudflared"\n'
        + _tunnel_vars()
        + "\n"
        + _functions()
        + "\n"
        + body
    )
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


# ─── Guard nguồn ─────────────────────────────────────────────────────────────

def test_token_never_goes_through_argv():
    """`ps` đọc được command line của mọi tiến trình; token phải đi qua ENV."""
    src = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8")
    assert "--token" not in src, "token trên command line là lộ cho mọi app cùng máy"
    assert "TUNNEL_TOKEN=" in src


def test_watchdog_owns_a_tunnel_pid_file():
    src = (ROOT / "scripts" / "watchdog.sh").read_text(encoding="utf-8")
    assert "TUNNEL_PID_FILE" in src
    assert src.count("ensure_tunnel") >= 4, "phải gọi ở khởi động + mỗi vòng health + khi thất bại"


# ─── Hành vi (chạy hàm thật trong bash) ──────────────────────────────────────

@needs_bash
def test_ensure_tunnel_starts_once_and_adopts_its_own_pid(sandbox):
    r = _run(sandbox, """
ensure_tunnel
pid1=$(cat data/cloudflared.pid)
pid_is "$pid1" cloudflared || { echo "KHONG_PHAI_TUNNEL"; exit 3; }
ensure_tunnel                       # lan 2 KHONG duoc spawn them
pid2=$(cat data/cloudflared.pid)
echo "pid1=$pid1 pid2=$pid2"
""")
    assert r.returncode == 0, r.stderr
    assert "pid1=" in r.stdout and "pid1=" in r.stdout
    pid1 = r.stdout.split("pid1=")[1].split()[0]
    pid2 = r.stdout.split("pid2=")[1].strip()
    assert pid1 == pid2, f"lần gọi thứ hai đã spawn thêm cloudflared: {pid1} -> {pid2}"


@needs_bash
def test_foreign_pid_is_not_mistaken_for_the_tunnel(sandbox):
    """Sau reboot, PID trong file có thể là tiến trình khác — phải spawn tunnel mới."""
    r = _run(sandbox, """
sleep 30 & foreign=$!                # tien trinh la, cmdline KHONG chua 'cloudflared'
echo $foreign > data/cloudflared.pid
ensure_tunnel
new=$(cat data/cloudflared.pid)
kill -9 $foreign 2>/dev/null
[ "$new" != "$foreign" ] || { echo "VAN_DUNG_PID_LA"; exit 4; }
pid_is "$new" cloudflared && echo "OK_DA_TAO_TUNNEL"
""")
    assert r.returncode == 0, r.stderr
    assert "OK_DA_TAO_TUNNEL" in r.stdout


@needs_bash
def test_stop_tunnel_kills_only_the_tunnel(sandbox):
    r = _run(sandbox, """
ensure_tunnel
tpid=$(cat data/cloudflared.pid)
stop_tunnel
[ -f data/cloudflared.pid ] && { echo "PID_FILE_CON"; exit 5; }
pid_is "$tpid" cloudflared && { echo "TUNNEL_VAN_SONG"; exit 6; }
echo "DA_DUNG"
""")
    assert r.returncode == 0, r.stderr
    assert "DA_DUNG" in r.stdout


@needs_bash
def test_missing_token_fails_loudly_instead_of_looping(sandbox):
    (sandbox / ".env").write_text("")           # không có token
    r = _run(sandbox, "ensure_tunnel; echo rc=$?")
    assert "CLOUDFLARED_TOKEN" in r.stdout, r.stdout
    assert "rc=1" in r.stdout, "thiếu token phải trả 1 để caller biết không dựng được"


@needs_bash
def test_token_reader_handles_crlf_and_quotes(sandbox):
    (sandbox / ".env").write_text(
        'OTHER=1\r\nCLOUDFLARED_TOKEN="tok-crlf-999"\r\n'
    )
    r = _run(sandbox, 'v=$(cloudflared_token); echo "[$v]"')
    assert r.returncode == 0, r.stderr
    assert "[tok-crlf-999]" in r.stdout, r.stdout

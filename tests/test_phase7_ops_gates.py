"""P1-4 — Ops gates: pre-commit fail-closed, chặn đọc .env, deploy rollback,
MCP shell tắt mặc định, watchdog tách counter 500/503, SSH host key.
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_dual_model_denies_secret_files():
    import scripts.dual_model_mcp as dm

    for path in (".env", ".env.example", "data/bot.db", "server.pem"):
        with pytest.raises(PermissionError):
            dm._resolve_safe_path(path)


def test_dual_model_scrubs_unquoted_env_and_webhook():
    import scripts.dual_model_mcp as dm

    raw = (
        "FLASK_SECRET_KEY=abc123secret\n"
        "ADMIN_PASSWORD=hunter2\n"
        "https://discord.com/api/webhooks/123456/token-abc\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnopqrstuvwxyz\n"
    )
    out = dm._scrub_sensitive_data(raw)
    assert "abc123secret" not in out
    assert "hunter2" not in out
    assert "webhooks/123456" not in out
    assert "eyJhbGciOiJIUzI1NiJ9" not in out


def test_precommit_parse_failure_fails_closed(monkeypatch):
    import scripts.dual_model_mcp as dm

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""

        if isinstance(cmd, list) and "diff" in cmd:
            R.stdout = "bot/cogs/x.py\n" if "--name-only" in cmd else "diff --git a/x b/x\n+print(1)\n"
        return R()

    monkeypatch.setattr(dm.subprocess, "run", fake_run)
    monkeypatch.setattr(dm, "_invoke_ai", lambda *a, **k: "day khong phai json")
    monkeypatch.setattr(dm, "_project_baseline", lambda: "20 modules / 128 lệnh / 1861 keys")

    text = dm.execute_pre_commit_check()

    assert dm._last_pre_commit_verdict == "FIX_REQUIRED"
    assert "CẦN KHẮC PHỤC" in text


def test_deploy_health_requires_online_probe():
    import scripts.termux_deploy as td

    assert td._deploy_health_ok('{"online": true}', True) is True
    assert td._deploy_health_ok('{"online": false}', True) is False
    assert td._deploy_health_ok('not-json', True) is False
    assert td._deploy_health_ok('{"online": true}', False) is False


def test_deploy_local_head_is_a_sha():
    import scripts.termux_deploy as td

    head = td._local_git_head()
    assert len(head) == 40 and all(c in "0123456789abcdef" for c in head)


def test_termux_run_command_is_disabled_by_default(monkeypatch):
    import scripts.termux_mcp as tm

    monkeypatch.delenv("TERMUX_MCP_ALLOW_SHELL", raising=False)
    out = tm.termux_run_command("echo hello")
    assert "bị tắt" in out


def test_ssh_host_key_is_strict():
    mcp = _read("scripts/termux_mcp.py")
    deploy = _read("scripts/termux_deploy.py")
    assert "StrictHostKeyChecking=no" not in mcp
    assert "StrictHostKeyChecking=no" not in deploy
    assert "StrictHostKeyChecking=yes" in mcp
    assert "StrictHostKeyChecking=yes" in deploy
    assert "RejectPolicy" in mcp
    assert "RejectPolicy" in deploy


def test_watchdog_has_separate_bot_and_dashboard_counters():
    src = _read("scripts/watchdog.sh")
    assert "bot_fail=$((bot_fail + 1))" in src
    assert "dash_fail=$((dash_fail + 1))" in src
    assert 'if [ "$http_code" = "503" ]' in src
    assert "seq 1 15" in src, "phải chờ 15s trước SIGKILL"
    assert 'ps -o ppid= -p "${BASHPID:-$$}"' in src, "health_loop phải tự thoát khi watchdog chết"


def test_cleanup_uses_copytruncate_not_mv():
    src = _read("scripts/termux_cleanup.py")
    assert 'cp -f "$f" "$f.1"' in src
    assert 'mv -f "$f" "$f.1"' not in src

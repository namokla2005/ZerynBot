"""P3-C — Self-test không ghi DB thật, health.json test isolation, AI log tách process,
deploy backup/deps, CI matrix.
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import tester  # noqa: E402


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_self_test_aborts_when_sandbox_cannot_be_created(temp_db, monkeypatch):
    called = []

    def fail_snapshot(path):
        raise RuntimeError("snapshot failed")

    async def fake_run(**kwargs):
        called.append(kwargs)
        return True

    monkeypatch.setattr(tester, "snapshot_database", fail_snapshot)
    monkeypatch.setattr(tester.SystemTester, "_run_all_tests", staticmethod(fake_run))

    ok = asyncio.run(tester.SystemTester.run_all_tests())

    assert ok is False, "sandbox lỗi mà vẫn chạy test trên DB thật"
    assert called == []


def test_self_test_assert_is_not_tautology():
    src = _read("bot/tester.py")
    assert 'assert "autorole_ids" in s or' not in src
    assert 'assert "autoroles_user" in s and "autoroles_bot" in s' in src


def test_health_path_can_be_overridden_for_tests():
    bot_src = _read("bot/bot.py")
    pub_src = _read("dashboard/blueprints/public.py")
    assert 'os.environ.get("ZERYN_HEALTH_FILE")' in bot_src
    assert 'os.environ.get("ZERYN_HEALTH_FILE")' in pub_src


def test_health_file_fixture_points_to_tmp(health_file):
    assert "pytest-of-" in health_file or os.path.basename(os.path.dirname(health_file)).startswith("test_")
    real = os.path.join(ROOT, "data", "health.json")
    assert os.path.abspath(health_file) != os.path.abspath(real)


def test_ai_log_file_is_split_by_process():
    src = _read("ai_logger.py")
    assert 'ai_activity_{_role}.log' in src
    main_src = _read("main.py")
    assert 'ZERYN_PROCESS_ROLE' in main_src
    assert '"bot"' in main_src and '"dashboard"' in main_src


def test_deploy_backups_db_and_installs_requirements():
    src = _read("scripts/termux_deploy.py")
    assert "data/backups/pre_deploy.db" in src
    assert "pip install -r requirements.txt" in src
    assert "sqlite3.connect('data/bot.db')" in src


def test_ci_matrix_and_shell_syntax_gate():
    src = _read(".github/workflows/ci.yml")
    assert 'python-version: ["3.10", "3.12"]' in src
    assert "bash -n scripts/watchdog.sh scripts/termux_boot.sh" in src

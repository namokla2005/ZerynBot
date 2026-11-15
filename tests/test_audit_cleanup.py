"""Cleanup errors must fail closed without touching production resources."""
from scripts import termux_cleanup as cleanup


def test_cleanup_stops_and_closes_on_command_failure(monkeypatch):
    class Runner:
        bot_dir = '/tmp/test-bot'
        closed = False
        calls = []
        def __init__(self, **kwargs):
            pass
        def connect(self):
            return True, 'test'
        def exec(self, cmd, **kwargs):
            self.calls.append(cmd)
            return 'failed', 1
        def close(self):
            self.closed = True
    runner = Runner()
    monkeypatch.setattr(cleanup, '_Runner', lambda **kw: runner)
    assert cleanup.run_termux_cleanup() is False
    assert runner.closed
    assert len(runner.calls) == 1


def test_optional_failure_continues_but_reports_failure(monkeypatch):
    class Runner:
        bot_dir = '~/ZerynBot'
        closed = False
        def __init__(self):
            self.calls = []
        def connect(self):
            return True, 'test'
        def exec(self, cmd, **kwargs):
            self.calls.append(cmd)
            if cmd.startswith('printf'):
                return '/home/test user', 0
            if cmd.startswith('pip '):
                return 'permission denied', 1
            return '', 0
        def close(self):
            self.closed = True
    runner = Runner()
    monkeypatch.setattr(cleanup, '_Runner', lambda **kw: runner)
    assert cleanup.run_termux_cleanup() is False
    assert runner.closed
    assert 'sync' in runner.calls
    rotations = [cmd for cmd in runner.calls if cmd.startswith('f=')]
    assert len(rotations) == 2
    assert all("f='/home/test user/ZerynBot/data/" in cmd for cmd in rotations)
    assert all('~/' not in cmd for cmd in rotations)

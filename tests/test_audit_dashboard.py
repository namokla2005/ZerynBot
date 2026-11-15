"""Regression checks for the verified e555014 public/admin defects."""
import inspect
from types import SimpleNamespace

import pytest
from conftest import login


def test_landing_invites_have_destination(client, temp_db):
    html = client.get('/').get_data(as_text=True)
    assert 'href=""' not in html
    assert html.count('href="/invite"') >= 12


@pytest.mark.parametrize('page', ['/docs', '/support'])
def test_language_links_work(client, temp_db, page):
    login(client)
    html = client.get(page).get_data(as_text=True)
    for lang in ('vi', 'en', 'zh', 'es', 'pt', 'fr'):
        url = '/ui/language/' + lang
        assert f'href="{url}"' in html
        assert client.get(url).status_code == 302


@pytest.mark.parametrize('failed_step', [0, 1, 2, 3, None])
def test_admin_pull_stops_on_failure(flask_app, temp_db, monkeypatch, failed_step):
    from dashboard.blueprints import admin
    calls = []
    def run(argv, **kwargs):
        assert isinstance(argv, list)
        assert not kwargs.get('shell')
        calls.append(argv)
        return SimpleNamespace(stdout='', stderr='', returncode=1 if len(calls)-1 == failed_step else 0)
    monkeypatch.setattr(admin.subprocess, 'run', run)
    monkeypatch.setattr(admin, '_audit_admin_action', lambda *a: None)
    with flask_app.test_request_context('/admin/system/git-pull', method='POST'):
        response, status = inspect.unwrap(admin.admin_system_git_pull)()
    assert status == 200
    assert response.json['ok'] is (failed_step is None)
    assert len(calls) == (4 if failed_step is None else failed_step + 1)
    if len(calls) > 1:
        assert '--include-untracked' in calls[1]

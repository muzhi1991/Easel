"""Offline regressions for draft-only publishing and profile-scoped cookies."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import web_publisher as publisher
import weixin_mp_stats as mp


def arguments(tmp_path, **changes):
    media = tmp_path / 'video.mp4'
    media.write_bytes(b'fixture')
    values = dict(platform='weixin-channels', media=str(media), title='title', desc='', tags='',
                  cover='', draft=True, exec=True, headed=False, allow_unsafe=False)
    values.update(changes)
    return SimpleNamespace(**values)


def test_draft_on_other_platform_fails_before_browser(tmp_path, monkeypatch):
    browser = Mock()
    monkeypatch.setattr(publisher, '_run_browser', browser)
    with pytest.raises(SystemExit):
        publisher.cmd_publish(arguments(tmp_path, platform='kuaishou'))
    browser.assert_not_called()


def test_draft_does_not_record_publication(tmp_path, monkeypatch):
    import calendar_ops
    record = Mock()
    monkeypatch.setattr(calendar_ops, 'record_publish', record)
    monkeypatch.setattr(publisher, '_run_browser', lambda *a, **kw: 0)
    monkeypatch.setattr(publisher.content_guard, 'guard_or_die', lambda *a, **kw: None)
    assert publisher.cmd_publish(arguments(tmp_path)) == 0
    record.assert_not_called()


def test_draft_preview_never_opens_browser(tmp_path, monkeypatch, capsys):
    browser = Mock()
    monkeypatch.setattr(publisher, '_run_browser', browser)
    monkeypatch.setattr(publisher.content_guard, 'guard_or_die', lambda *a, **kw: None)
    assert publisher.cmd_publish(arguments(tmp_path, exec=False)) == 0
    assert '单次点击存草稿' in capsys.readouterr().out
    browser.assert_not_called()


@pytest.mark.parametrize('timeout', [True, False])
def test_draft_submission_is_once_and_does_not_match_button(monkeypatch, timeout):
    page = Mock()
    frame = Mock(url='https://channels.weixin.qq.com/micro/content/post/create')
    page.frames = [frame]
    button = frame.get_by_role.return_value
    button.count.return_value = 1
    button.is_visible.return_value = button.is_enabled.return_value = True
    notice = frame.get_by_text.return_value
    notice.count.return_value = 0
    if timeout:
        notice.first.wait_for.side_effect = TimeoutError('missing result')
    monkeypatch.setattr(publisher, '_settle_login', lambda *a: None)
    monkeypatch.setattr(publisher, '_is_logged_in', lambda *a: True)
    if timeout:
        with pytest.raises(RuntimeError, match='结果未知'):
            publisher._draft_weixin_channels(page, {'media': 'fixture.mp4', 'title': 'title'})
    else:
        publisher._draft_weixin_channels(page, {'media': 'fixture.mp4', 'title': 'title'})
    button.click.assert_called_once()
    page.keyboard.press.assert_not_called()
    pattern = frame.get_by_text.call_args.args[0]
    assert not pattern.fullmatch('存草稿')
    assert not pattern.fullmatch('草稿保存失败')
    assert pattern.fullmatch('草稿已保存')


def test_cookie_profiles_do_not_share_accounts(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    cookie = {'name': 'sid', 'value': 'private-fixture', 'domain': 'mp.weixin.qq.com', 'path': '/'}
    source = Mock()
    source.cookies.return_value = [cookie]
    mp._save_storage(source, first)
    target = Mock()
    mp._restore_storage(target, second)
    target.add_cookies.assert_not_called()
    mp._restore_storage(target, first)
    target.add_cookies.assert_called_once_with([cookie])
    path = first / '.easel-cookies.json'
    assert json.loads(path.read_text()) == {'cookies': [cookie]}
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(first.glob('.easel-cookies-*'))


def test_cookie_save_failure_keeps_previous_file_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / '.easel-cookies.json'
    path.write_text('{"cookies": []}')
    ctx = Mock()
    ctx.cookies.return_value = [{'name': 'sid', 'value': 'private'}]
    monkeypatch.setattr(mp.os, 'replace', Mock(side_effect=OSError('fixture')))
    mp._save_storage(ctx, tmp_path)
    assert path.read_text() == '{"cookies": []}'
    assert not list(tmp_path.glob('.easel-cookies-*'))


def test_context_close_persists_rotated_and_cleared_cookies(tmp_path):
    old = [{'name': 'sid', 'value': 'old', 'domain': 'mp.weixin.qq.com', 'path': '/'}]
    rotated = [{**old[0], 'value': 'rotated'}]
    profile = mp._profile_dir(str(tmp_path))
    profile.mkdir()
    seed = Mock()
    seed.cookies.return_value = old
    mp._save_storage(seed, profile)
    for initial, updated in [(old, rotated), (rotated, []), ([], [])]:
        context = Mock()
        original_close = context.close
        context.cookies.return_value = updated
        playwright = Mock()
        playwright.chromium.launch_persistent_context.return_value = context
        launched = mp._launch(playwright, False, str(tmp_path), None)
        if initial:
            context.add_cookies.assert_called_once_with(initial)
        else:
            context.add_cookies.assert_not_called()
        launched.close()
        original_close.assert_called_once()
        assert json.loads((profile / '.easel-cookies.json').read_text())['cookies'] == updated

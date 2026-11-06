"""Browser acceptance: persona filtering, transfer actions and scoped account requests.
All APIs are mocked; no real accounts, messages or publish endpoints are used.
"""
import json
import sys
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect


def check(browser, url):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    page.add_init_script("localStorage.setItem('easel_onboarding_seen', '1'); sessionStorage.setItem('easel_tab_session', 'shared_general')")
    messages = [{'role': 'user', 'content': '草稿'}, {'role': 'assistant', 'content': '正文'}]
    sessions = [dict(id='shared_' + name, source='server', agentSessionId=name, revision=1, created=i,
                     persona=persona, title=title, messageCount=2, historyEpoch=0)
                for i, (name, persona, title) in enumerate([
                    ('general', None, '通用对话'), ('herbal', '养生', '养生对话'), ('tech', '科技', '科技对话')])]
    calls = []
    def api(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        calls.append((path, parse_qs(parsed.query), route.request.post_data_json if route.request.method == 'POST' else None))
        if path == '/api/conversations': data = sessions
        elif path.endswith('/transfer'):
            payload = route.request.post_data_json
            source = next(s for s in sessions if s['id'] == path.split('/')[-2])
            saved = {**source, 'id': 'shared_' + ('copy' if payload['copy'] else 'moved'), 'agentSessionId': 'copy' if payload['copy'] else 'moved', 'persona': payload['persona']}
            if not payload['copy']: sessions.remove(source)
            sessions.append(saved)
            data = saved
        elif path.startswith('/api/conversations/'):
            data = {**next(s for s in sessions if s['id'] == path.split('/')[-1]), 'messages': messages, 'messageStart': 0}
        elif path == '/api/personas': data = [{'name': '养生'}, {'name': '科技'}]
        elif path == '/api/status': data = {'gateway': True, 'transport': 'api', 'personas': [{'name': '养生'}, {'name': '科技'}]}
        elif path == '/api/settings/bootstrap': data = {'modelConfigured': True}
        elif path == '/api/upload/limits': data = {'max_mb': 50}
        elif path == '/api/accounts': data = [{'platform': 'wechat-oa', 'name': '微信公众号', 'backend': 'wechat-oa', 'supported': True, 'loggedIn': not parsed.query}]
        elif path.endswith('/whoami'): data = {'loggedIn': not parsed.query, 'name': '', 'avatar': ''}
        elif path.endswith('/mp-login'): data = {'mode': 'qr', 'state': 'starting', 'message': '等待扫码', 'qr': ''}
        else:
            route.fulfill(status=404, content_type='application/json', body='{}'); return
        route.fulfill(content_type='application/json', body=json.dumps(data))
    page.route('**/api/**', api)
    page.goto(url)
    expect(page.locator('.session-item-title')).to_have_text(['通用对话'])
    page.get_by_role('button', name='显示所有画像对话', exact=True).click()
    expect(page.locator('.session-item-title')).to_have_count(3)
    page.get_by_role('button', name='选择用户画像', exact=True).click()
    page.get_by_role('option', name='养生', exact=True).click()
    expect(page.locator('.session-item-title')).to_have_text(['养生对话'])
    page.locator('.session-item').hover()
    page.get_by_title('复制或移动到画像', exact=True).click()
    page.get_by_role('combobox', name='目标画像').select_option('科技')
    page.get_by_role('button', name='复制', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(page.locator('.session-item-title')).to_have_count(2)
    assert any(path.endswith('/transfer') and payload == {'revision': 1, 'persona': '科技', 'copy': True} for path, _, payload in calls)
    page.get_by_role('button', name='账号', exact=True).click()
    expect(page.get_by_role('heading', name='账号登录 · 科技')).to_be_visible()
    assert any(path == '/api/accounts' and query.get('persona') == ['科技'] for path, query, _ in calls)
    page.screenshot(path='/tmp/easel-persona-accounts.png')
    page.get_by_role('button', name='登录', exact=True).click()
    assert any(path.endswith('/mp-login') and query.get('persona') == ['科技'] for path, query, _ in calls)
    page.get_by_role('button', name='关闭', exact=True).click()
    page.get_by_role('button', name='选择用户画像', exact=True).click()
    page.get_by_role('option', name='通用模式', exact=True).click()
    expect(page.locator('.session-item-title')).to_have_text(['通用对话'])
    expect(page.get_by_role('heading', name='账号登录 · 通用模式')).to_be_visible()
    page.get_by_role('button', name='对话', exact=True).click()
    expect(page.locator('.session-item-title')).to_have_text(['通用对话'])
    page.locator('.session-item').hover()
    page.get_by_title('复制或移动到画像', exact=True).click()
    page.get_by_role('combobox', name='目标画像').select_option('养生')
    page.get_by_role('button', name='移动', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert any(path.endswith('/transfer') and payload and payload.get('copy') is False for path, _, payload in calls)
    assert not any(s['id'] == 'shared_general' for s in sessions)
    context.close()


if __name__ == '__main__':
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        check(browser, sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:7867')
        browser.close()
    print('Persona browser acceptance passed')

"""Naming entry points with mocked APIs; never changes real conversations."""
import json
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def check(browser, url):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    page.add_init_script("localStorage.setItem('easel_onboarding_seen', '1')")
    session = {'id': 'shared_name', 'source': 'server', 'revision': 1, 'created': 1,
               'historyEpoch': 0, 'messageCount': 2, 'title': '临时标题', 'titleLocked': False}
    messages = [{'role': 'user', 'content': '写文章'},
                {'role': 'assistant', 'content': '# 正式文章标题\n\n文章正文', 'artifactTitle': '正式文章标题'}]
    patches, suggestions = [], []

    def api(route):
        path = urlparse(route.request.url).path
        if path.endswith('/suggest-title'):
            suggestions.append(route)
            return
        if path == '/api/conversations':
            data = [session]
        elif path == '/api/conversations/shared_name':
            if route.request.method == 'PATCH':
                payload = route.request.post_data_json
                patches.append(payload)
                session.update(title=payload['title'], titleLocked=True, revision=session['revision'] + 1)
                data = session
            else:
                data = {**session, 'messageStart': 0, 'messages': messages}
        elif path == '/api/status':
            data = {'gateway': True, 'transport': 'api', 'personas': []}
        elif path == '/api/settings/bootstrap':
            data = {'modelConfigured': True}
        elif path == '/api/upload/limits':
            data = {'max_mb': 50}
        else:
            route.fulfill(status=404, content_type='application/json', body='{}')
            return
        route.fulfill(content_type='application/json', body=json.dumps(data))
    page.route('**/api/**', api)
    page.goto(url)
    page.locator('.session-item-title').filter(has_text='临时标题').click()
    page.locator('.session-item').hover()
    page.get_by_title('重命名', exact=True).click()
    field = page.get_by_role('textbox', name='对话名称')
    page.get_by_role('button', name='智能命名', exact=True).click()
    page.wait_for_timeout(100)
    field.fill('用户正在编辑')
    suggestions.pop().fulfill(content_type='application/json', body='{"title":"迟来的模型标题"}')
    page.get_by_role('button', name='智能命名', exact=True).wait_for()
    assert field.input_value() == '用户正在编辑'
    page.get_by_role('button', name='取消', exact=True).click()
    assert not patches
    page.get_by_title('命名对话', exact=True).click()
    page.get_by_role('button', name='使用此产物标题', exact=True).click()
    assert field.input_value() == '正式文章标题'
    page.screenshot(path='/tmp/easel-naming-dialog.png')
    page.get_by_role('button', name='保存', exact=True).click()
    page.get_by_role('dialog').wait_for(state='hidden')
    assert patches[-1]['title'] == '正式文章标题'
    assert page.locator('.session-item-title').inner_text() == '正式文章标题'
    page.locator('.session-item').hover()
    page.get_by_title('重命名', exact=True).click()
    page.get_by_role('button', name='智能命名', exact=True).click()
    page.wait_for_timeout(100)
    suggestions.pop().fulfill(status=502, content_type='application/json', body='{"detail":"命名失败，请重试"}')
    page.get_by_role('alert').wait_for()
    assert field.input_value() == '正式文章标题'
    context.close()


if __name__ == '__main__':
    with sync_playwright() as p:
        for engine in (p.chromium, p.webkit):
            browser = engine.launch()
            check(browser, sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5179')
            print(f'PASS {engine.name}: entry points, cancel, exact title, manual edit race, suggestion failure')
            browser.close()

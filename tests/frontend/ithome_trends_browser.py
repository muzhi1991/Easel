"""Full-app IT之家 to new chat regression; all APIs and model replies are mocked."""
import argparse
import json
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def check(browser, base, mobile):
    context = browser.new_context(viewport={'width': 390 if mobile else 1440, 'height': 900},
                                  is_mobile=mobile, has_touch=mobile, service_workers='block')
    context.add_init_script("localStorage.setItem('easel_onboarding_seen', '1')")
    page = context.new_page()
    page.set_default_timeout(10000)
    errors, sent, saved, calls = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    state = {'fail': False}
    sessions = {}
    article = {'id': 'ithome-test', 'source': 'ithome', 'title': 'IT之家测试科技新闻',
               'url': 'https://www.ithome.com/0/123/456.htm', 'publisher': 'IT之家·24h热榜',
               'author': '', 'summary': '<p>芯片性能提升 &amp; 功耗下降</p><script>alert(1)</script>',
               'published_at': 1792400400, 'heat_score': 11.88, 'metrics': {}}

    def api(route):
        path = urlparse(route.request.url).path
        calls.append(path)
        if path == '/api/status':
            data = {'gateway': True, 'transport': 'api', 'personas': []}
        elif path == '/api/settings/bootstrap':
            data = {'modelConfigured': True}
        elif path == '/api/upload/limits':
            data = {'max_mb': 50}
        elif path == '/api/conversations':
            if route.request.method == 'POST':
                data = {**route.request.post_data_json, 'revision': 1}
                sessions[data['id']] = data
            else:
                data = list(sessions.values())
        elif path.startswith('/api/conversations/'):
            data = sessions[path.rsplit('/', 1)[-1]]
        elif path in [ '/api/personas', '/api/accounts', '/api/outputs']:
            data = []
        elif path == '/api/trends':
            data = {'trends': [], 'updated': 1792400400}
        elif path == '/api/ithome-trends':
            if state['fail']:
                route.fulfill(status=503, body='unavailable')
                return
            data = {'configured': True, 'error': '', 'stale': False, 'fetched_at': 1792400400,
                    'feed_updated_at': 1792400000,
                    'groups': [{'source': 'ithome', 'label': 'IT之家', 'items': [article]}]}
        elif path == '/api/ideas' and route.request.method == 'GET':
            data = []
        elif path == '/api/ideas':
            saved.append(route.request.post_data_json)
            data = {'id': 'saved', **saved[-1]}
        elif path == '/api/chat/stream':
            sent.append(route.request.post_data_json)
            session = sessions[sent[-1]['conversationId']]
            session.update(revision=3, messageCount=2, messages=[
                {'role': 'user', 'content': sent[-1]['message']},
                {'role': 'assistant', 'content': '这是模拟的科技文案初稿。'}])
            route.fulfill(content_type='text/event-stream', body='event: token\ndata: "这是模拟的科技文案初稿。"\n\nevent: done\ndata: {}\n\n')
            return
        else:
            route.fulfill(status=404, content_type='application/json', body='{}')
            return
        route.fulfill(content_type='application/json', body=json.dumps(data))

    context.route('**/api/**', api)
    page.goto(base, wait_until='domcontentloaded')
    page.get_by_role('button', name='热点雷达 →', exact=True).click()
    page.get_by_role('button', name='IT之家', exact=True).click()
    card = page.get_by_role('region', name='IT之家热点', exact=True)
    card.get_by_text(article['title'], exact=True).wait_for()
    assert '/api/overseas-trends' not in calls
    assert card.get_by_text('综合分 11.88', exact=True).is_visible()
    card.get_by_text('查看摘要', exact=True).click()
    assert card.get_by_text('芯片性能提升 & 功耗下降', exact=True).is_visible()
    card.get_by_role('button', name='收藏到选题库').click()
    card.get_by_role('button', name='已收藏').wait_for()
    assert saved[0]['source'] == article['publisher'] and article['url'] in saved[0]['note']
    state['fail'] = True
    page.get_by_role('button', name='刷新', exact=True).click()
    card.get_by_role('alert').wait_for()
    assert '当前显示上次获取的内容' in card.inner_text()
    card.get_by_role('button', name='做内容', exact=True).click()
    page.get_by_text('这是模拟的科技文案初稿。', exact=True).wait_for()
    assert len(sent) == 1
    prompt = sent[0]['message']
    for expected in [article['title'], article['publisher'], article['url'], '发布时间：',
                     '芯片性能提升 & 功耗下降', '二创角度', '文案初稿']:
        assert expected in prompt, (expected, prompt)
    assert '<script>' not in prompt and 'alert(1)' not in prompt and '<p>' not in prompt
    assert sent[0]['sessionId']
    assert len(sessions) == 1 and sent[0]['conversationId'] in sessions
    assert page.locator('.chat-messages').is_visible()
    assert page.locator('.trends-page').count() == 0
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/easel-ithome-chat-{"mobile" if mobile else "desktop"}.png', full_page=True)
    assert not errors, errors
    context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5189')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for mobile in [False, True]:
            check(browser, args.url, mobile)
        browser.close()
    print('PASS: desktop/mobile IT之家, save, stale data, new chat, full context and streamed reply')

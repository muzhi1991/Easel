"""Browser regression: run Vite, then .venv/bin/python tests/frontend/chat_scroll_browser.py.

Uses only mocked API responses; never sends a message to a real model/server.
"""
import argparse
import json
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


def check(browser, url, mobile):
    context = browser.new_context(viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 900},
                                  is_mobile=mobile, has_touch=mobile)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    session = {"id": "shared_scroll_test", "source": "server", "revision": 1, "title": "Scroll regression",
               "created": 1, "historyEpoch": 0, "messages": [{"role": "user" if i % 2 else "assistant", "content": f"History {i}\n\n" + "Reading history. " * 15} for i in range(123)]}
    polls = 0
    detail_requests = []
    sent_turns = []

    def summary():
        return {**{k: v for k, v in session.items() if k != 'messages'}, 'messageCount': len(session['messages'])}

    def api(route):
        nonlocal polls
        path = urlparse(route.request.url).path
        if path == "/api/conversations":
            polls += 1
            data = [summary()]
        elif path == '/api/conversations/shared_scroll_test':
            query = parse_qs(urlparse(route.request.url).query)
            detail_requests.append(query)
            total = len(session['messages'])
            limit = int(query.get('limit', ['50'])[0])
            end = min(int(query.get('before', [str(total)])[0]), total)
            start = max(0, end - limit)
            if 'after' in query:
                start = int(query['after'][0]) + 1
                end = min(start + limit, total)
            data = {**summary(), 'messageStart': start, 'messages': session['messages'][start:end]}
        elif path == "/api/status":
            data = {"gateway": True, "transport": "api", "personas": []}
        elif path == "/api/settings/bootstrap":
            data = {"modelConfigured": True}
        elif path == "/api/upload/limits":
            data = {"max_mb": 50}
        elif path == "/api/chat/stream":
            payload = route.request.post_data_json
            sent_turns.append(payload)
            retry = payload.get('truncateAt')
            if retry is not None:
                session['messages'] = session['messages'][:retry]
                session['historyEpoch'] += 1
            text = "Retried reply." if retry is not None else "Streaming reply. " * 300
            session["messages"].extend([
                {"role": "user", "content": payload["message"]},
                {"role": "assistant", "content": text},
            ])
            session["revision"] += 2
            route.fulfill(content_type="text/event-stream", body=f"event: token\ndata: {json.dumps(text)}\n\nevent: done\ndata: {{}}\n\n")
            return
        else:
            route.fulfill(status=404, content_type="application/json", body='{"detail":"mocked unavailable"}')
            return
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route("**/api/**", api)
    page.add_init_script("localStorage.setItem('easel_onboarding_seen', '1')")
    page.goto(url, wait_until='domcontentloaded')
    page.locator('.session-item-title').first.wait_for(state='attached')
    assert not detail_requests, 'home must not fetch conversation bodies'
    if mobile:
        page.get_by_role("button", name="打开导航").click()
    page.get_by_text("Scroll regression", exact=True).click()
    scroller = page.locator(".chat-messages")
    bottom = "el => el.scrollHeight - el.clientHeight - el.scrollTop"
    page.wait_for_function("document.querySelector('.chat-messages')?.scrollTop > 100")
    page.wait_for_timeout(1200)
    assert scroller.evaluate(bottom) < 12, f"opening conversation: distance={scroller.evaluate(bottom)}, top={scroller.evaluate('el => el.scrollTop')}"
    assert page.locator('[data-message-index]').count() == 50, 'initial load must be one page'
    assert page.locator('[data-message-index]').first.get_attribute('data-message-index') == '73'

    # Retry indexes must refer to the full history, not the 50-item viewport.
    page.get_by_title('重新生成', exact=True).click()
    page.get_by_text('Retried reply.', exact=True).wait_for()
    page.get_by_title('停止生成', exact=True).wait_for(state='hidden')
    assert sent_turns[-1]['truncateAt'] == 121
    assert len(session['messages']) == 123

    def scroll_up():
        box = scroller.bounding_box()
        if mobile:
            cdp = context.new_cdp_session(page)
            x, y = box["x"] + box["width"] / 2, box["y"] + 80
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            for step in range(1, 11):
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + step * 25}]})
                page.wait_for_timeout(25)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            cdp.detach()
        else:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 100)
            page.mouse.wheel(0, -650)
        page.wait_for_timeout(700)

    scroll_up()
    assert scroller.evaluate(bottom) > 150, "gesture must scroll into history"
    before = scroller.evaluate("el => el.scrollTop")
    old_polls = polls
    old_details = len(detail_requests)
    page.wait_for_timeout(5500)
    assert len(detail_requests) == old_details, 'idle polling must not fetch message bodies'
    assert polls > old_polls, "must exercise the actual five-second polling timer"
    assert abs(scroller.evaluate("el => el.scrollTop") - before) < 2, "idle poll stole history position"

    # Crossing the top fetches one older page and preserves the old first
    # message's screen position, including when the oldest page removes the button.
    for first_index, expected_count in ((73, 100), (23, 123)):
        offset = scroller.evaluate("""(el, index) => {
            el.scrollTop = 20;
            return document.querySelector(`[data-message-index="${index}"]`).getBoundingClientRect().top;
        }""", first_index)
        page.wait_for_function("n => document.querySelectorAll('[data-message-index]').length === n", arg=expected_count)
        page.wait_for_timeout(150)
        actual = page.locator(f'[data-message-index="{first_index}"]').evaluate('el => el.getBoundingClientRect().top')
        assert abs(actual - offset) < 2, f'prepend moved reading position: {offset} -> {actual}'
    indexes = page.locator('[data-message-index]').evaluate_all("els => els.map(el => Number(el.dataset.messageIndex))")
    assert indexes == list(range(123)), 'history pages must have no gaps or duplicates'
    before = scroller.evaluate('el => el.scrollTop')

    # A genuine remote message must not steal the reader's position either.
    session["revision"] += 1
    session["messages"].append({"role": "assistant", "content": "Remote new message. " * 100})
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.get_by_text("Remote new message. " * 100, exact=True).wait_for()
    assert abs(scroller.evaluate("el => el.scrollTop") - before) < 2, "new message stole history position"

    # Returning to the bottom enables following again.
    scroller.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    page.wait_for_timeout(100)
    session["revision"] += 1
    session["messages"].append({"role": "assistant", "content": "Follow again. " * 100})
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.get_by_text("Follow again. " * 100, exact=True).wait_for()
    page.wait_for_timeout(1200)
    assert scroller.evaluate(bottom) < 12, "following did not resume at bottom"
    original_size = page.viewport_size
    page.set_viewport_size({**original_size, "height": original_size["height"] - 200})
    page.wait_for_timeout(150)
    assert scroller.evaluate(bottom) < 12, "viewport resize lost bottom following"
    page.set_viewport_size(original_size)
    page.wait_for_timeout(150)

    # Sending from history follows the new turn, but scrolling up during typing
    # pauses following even as actual SSE tokens continue to reach the UI.
    scroll_up()
    page.locator("textarea").fill("Test streaming scroll")
    page.get_by_title("发送", exact=True).click()
    page.get_by_title("停止生成", exact=True).wait_for()
    page.wait_for_timeout(150)
    assert scroller.evaluate(bottom) < 12, "sending from history should follow the new turn"
    scroll_up()
    before = scroller.evaluate("el => el.scrollTop")
    length = len(scroller.inner_text())
    page.wait_for_timeout(500)
    assert len(scroller.inner_text()) > length, "stream must still be growing during the check"
    assert abs(scroller.evaluate("el => el.scrollTop") - before) < 2, f"streaming stole history position: before={before}, after={scroller.evaluate('el => el.scrollTop')}, bottom={scroller.evaluate(bottom)}"
    page.get_by_title("停止生成", exact=True).wait_for(state="hidden")
    assert abs(scroller.evaluate("el => el.scrollTop") - before) < 2, "stream completion stole history position"

    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal viewport overflow"
    assert not errors, errors
    print(f"PASS {'mobile touch' if mobile else 'desktop wheel'}: summary-only home, paging, retry offsets, polling, remote message, resume, send, stream, viewport")
    context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5179")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for mobile in (False, True):
                check(browser, args.url, mobile)
        finally:
            browser.close()

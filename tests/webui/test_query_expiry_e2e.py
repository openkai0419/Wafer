import struct

import pytest

SCROLL_TOP = "document.querySelector('#grid-scroll').scrollTop"
CAPTION = "document.querySelector('#viewer-caption').textContent"
STATUS = "document.querySelector('#status').textContent"


def _without_the_second_item(route):
    if "limit=1&" in route.request.url or route.request.url.endswith("limit=1"):
        route.continue_()
        return
    response = route.fetch()
    data = response.json()
    data["items"] = [item for item in data["items"] if item["i"] != 1]
    route.fulfill(response=response, json=data)


def _query_posts(page):
    posts = []
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and request.url.endswith("/api/query") else None)
    return posts


@pytest.fixture
def scrolled_viewer(page, webui_base_url):
    page.set_viewport_size({"width": 500, "height": 320})
    page.route("**/api/query/*/items*", _without_the_second_item)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    page.wait_for_function("document.querySelector('#grid-scroll').scrollHeight > document.querySelector('#grid-scroll').clientHeight")
    page.evaluate("document.querySelector('#grid-scroll').scrollTop = 40")
    page.wait_for_function(f"{SCROLL_TOP} === 40")
    page.evaluate("document.querySelector('#grid-canvas .cell[data-i=\"0\"]').click()")
    page.wait_for_selector("#viewer:not(.hidden)")
    page.wait_for_function(f"{CAPTION}.startsWith('1/')")
    return page


def test_an_expired_query_with_the_same_total_keeps_the_scroll_and_the_viewer(scrolled_viewer, webui_query_service):
    page = scrolled_viewer
    total = page.evaluate(f"{STATUS}")
    posts = _query_posts(page)

    webui_query_service._sessions.clear()

    page.click("#viewer-next")
    page.wait_for_function("document.querySelector('#viewer').classList.contains('hidden') || document.querySelector('#viewer-stage img')")
    assert page.locator("#viewer.hidden").count() == 0
    caption = page.evaluate(CAPTION)
    assert caption.startswith("2/") and "error" not in caption
    assert len(posts) == 1
    assert page.evaluate(SCROLL_TOP) == 40
    assert page.evaluate(STATUS) == total

    page.click("#viewer-close")
    page.wait_for_selector("#grid-canvas .cell img")
    assert page.evaluate(SCROLL_TOP) == 40


def test_an_expired_query_with_a_new_total_starts_over(scrolled_viewer, webui_query_service):
    page = scrolled_viewer
    posts = _query_posts(page)

    def one_file_more(route):
        response = route.fetch()
        data = response.json()
        data["total"] += 1
        route.fulfill(response=response, json=data)

    def one_aspect_more(route):
        response = route.fetch()
        route.fulfill(response=response, body=response.body() + struct.pack("<f", 1.0))

    page.route("**/api/query", one_file_more)
    page.route("**/api/query/*/aspects", one_aspect_more)
    webui_query_service._sessions.clear()

    page.click("#viewer-next")
    page.wait_for_selector("#viewer", state="hidden")
    page.wait_for_function(f"{STATUS}.endsWith(' files')")
    page.wait_for_selector("#grid-canvas .cell")
    assert len(posts) == 1
    assert page.evaluate(SCROLL_TOP) == 0

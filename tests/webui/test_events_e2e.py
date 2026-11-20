import json

import pytest

from test_support.webui_dataset import DB_NAME

FAKE_SOCKET = """
window.__sockets = [];
window.WebSocket = class {
  constructor(url) {
    this.url = url;
    window.__sockets.push(this);
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  close() {}
};
"""

SETTLE = """() => fetch('/api/dbs').then(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))"""


@pytest.fixture
def evented_page(context, webui_base_url):
    context.add_init_script(FAKE_SOCKET)
    page = context.new_page()
    page.goto(webui_base_url)
    page.wait_for_function("document.querySelector('#status').textContent.includes('files')")
    page.wait_for_selector("#grid-canvas .cell")
    page.wait_for_function("window.__sockets.length > 0")
    return page


def _emit(page, topic, db=DB_NAME):
    page.evaluate("(data) => window.__sockets.at(-1).onmessage({ data })", json.dumps({"topic": topic, "db": db, "payload": db}))


@pytest.mark.parametrize("topic", ["folderchanged", "db.created", "db.deleted"])
def test_indexer_events_leave_the_page_as_it_is(evented_page, topic):
    page = evented_page
    loads = []
    requests = []
    page.on("load", lambda _: loads.append(1))
    page.on("request", lambda request: requests.append(request.url))

    _emit(page, topic)
    page.evaluate(SETTLE)

    assert loads == []
    assert [url for url in requests if "/api/folders" in url] == []
    assert [url for url in requests if "/api/query" in url] == []


def test_an_update_refetches_the_metadata_without_searching_again(evented_page):
    page = evented_page
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer:not(.hidden)")
    page.click("#viewer-info")
    page.wait_for_function("document.querySelector('#meta-content').textContent.includes('File')")
    requests = []
    page.on("request", lambda request: requests.append(request.url))

    _emit(page, "update")
    page.click("#viewer-next")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")
    page.wait_for_function("!document.querySelector('#meta-panel').classList.contains('pending')")
    page.click("#viewer-prev")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('1/')")
    page.wait_for_function("!document.querySelector('#meta-panel').classList.contains('pending')")

    assert len([url for url in requests if "/api/meta" in url]) == 2
    assert [url for url in requests if "/api/query" in url and "/items" not in url] == []
    assert page.locator("#viewer.hidden").count() == 0

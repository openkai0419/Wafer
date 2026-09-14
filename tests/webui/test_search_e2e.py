def _total(page):
    page.wait_for_function("document.querySelector('#status').textContent.includes('files')")
    return page.inner_text("#status")


def test_search_filters_results(ready_page):
    page = ready_page
    assert "5 files" in _total(page)

    page.fill("#search-input", "cat")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('2 ')")

    cells = page.query_selector_all("#grid-canvas .cell")
    assert len(cells) == 2


def test_search_clear_restores_all(ready_page):
    page = ready_page
    page.fill("#search-input", "dog")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")

    page.fill("#search-input", "")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('5 ')")


def test_order_toggle_reverses_grid(ready_page):
    page = ready_page
    first = page.get_attribute("#grid-canvas .cell", "title")

    page.click("#order-toggle")
    page.wait_for_function("t => document.querySelector('#grid-canvas .cell').title !== t", arg=first)
    assert page.get_attribute("#grid-canvas .cell", "title") != first


def test_key_picker_filters_by_key_presence(ready_page):
    page = ready_page
    page.click("#key-picker")
    page.wait_for_selector("#key-popup:not(.hidden)")
    page.wait_for_selector(".key-row")

    page.fill("#key-search", "prom")
    page.wait_for_function("document.querySelectorAll('.key-row').length === 1")
    page.click(".key-row")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('4 ')")
    assert page.inner_text("#key-picker .key-badge") == "1"

    page.fill("#search-input", "dog")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")

    page.fill("#search-input", "")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('4 ')")

    page.click(".key-chip-name")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('5 ')")
    assert page.is_visible(".key-chip")
    assert "active" not in (page.get_attribute(".key-chip", "class") or "")

    page.click(".key-chip-x")
    page.wait_for_selector(".key-chip", state="detached")

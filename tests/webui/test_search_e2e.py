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


def _open_search_options(page):
    page.click("#key-picker")
    page.wait_for_selector("#key-popup:not(.hidden)")


def _wait_total(page, prefix):
    page.wait_for_function(f"document.querySelector('#status').textContent.startsWith('{prefix} ')")


def test_keywords_split_by_comma_with_and(ready_page):
    page = ready_page
    page.fill("#search-input", "cat,picture")
    page.press("#search-input", "Enter")
    _wait_total(page, "2")

    page.fill("#search-input", "cat,dog")
    page.press("#search-input", "Enter")
    _wait_total(page, "0")


def test_keyword_mode_or_widens_results(ready_page):
    page = ready_page
    page.fill("#search-input", "cat,dog")
    page.press("#search-input", "Enter")
    _wait_total(page, "0")

    _open_search_options(page)
    page.click("#keyword-mode button[data-mode='OR']")
    _wait_total(page, "3")

    page.click("#keyword-mode button[data-mode='AND']")
    _wait_total(page, "0")


def test_keyword_separator_is_configurable(ready_page):
    page = ready_page
    page.fill("#search-input", "cat;picture")
    page.press("#search-input", "Enter")
    _wait_total(page, "0")

    _open_search_options(page)
    page.fill("#keyword-separator", ";")
    page.press("#keyword-separator", "Enter")
    _wait_total(page, "2")


def _count_query_posts(page):
    posts = []

    def on_request(request):
        if request.method == "POST" and "/api/query" in request.url:
            posts.append(request.url)

    page.on("request", on_request)
    return posts


def test_search_runs_without_enter(ready_page):
    page = ready_page
    page.fill("#search-input", "dog")
    _wait_total(page, "1")

    page.fill("#search-input", "")
    _wait_total(page, "5")


def test_rapid_input_sends_one_query(ready_page):
    page = ready_page
    posts = _count_query_posts(page)

    for text in ("c", "ca", "cat"):
        page.fill("#search-input", text)
    _wait_total(page, "2")
    assert len(posts) == 1


def test_enter_does_not_repeat_the_same_query(ready_page):
    page = ready_page
    posts = _count_query_posts(page)

    page.fill("#search-input", "cat")
    _wait_total(page, "2")
    page.press("#search-input", "Enter")

    page.fill("#search-input", "dog")
    _wait_total(page, "1")
    assert len(posts) == 2


def test_status_is_highlighted_while_searching(ready_page):
    page = ready_page
    page.evaluate("""() => {
      window.__busySeen = false;
      const el = document.querySelector('#status');
      const observer = new MutationObserver(() => {
        if (el.classList.contains('busy')) window.__busySeen = true;
      });
      observer.observe(el, { attributes: true, attributeFilter: ['class'] });
    }""")

    page.fill("#search-input", "cat")
    _wait_total(page, "2")

    assert page.evaluate("window.__busySeen") is True
    assert "busy" not in (page.get_attribute("#status", "class") or "")


def test_key_catalog_groups_by_prefix(ready_page):
    page = ready_page
    page.click("#key-picker")
    page.wait_for_selector("#key-popup:not(.hidden)")
    page.wait_for_selector(".key-row")

    assert page.locator(".key-group").all_inner_texts() == ["exiftool", "wd14"]
    assert page.locator("#key-catalog > *").first.get_attribute("class") == "key-row"

    row = page.locator(".key-row", has_text="Model").first
    assert row.inner_text().startswith("Model")
    assert row.get_attribute("title") == "exiftool.Model"


def test_key_catalog_filter_matches_full_key(ready_page):
    page = ready_page
    page.click("#key-picker")
    page.wait_for_selector("#key-popup:not(.hidden)")
    page.wait_for_selector(".key-row")

    page.fill("#key-search", "exiftool.mo")
    page.wait_for_function("document.querySelectorAll('.key-row').length === 1")
    assert page.locator(".key-group").all_inner_texts() == ["exiftool"]

    page.click(".key-row")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('4 ')")
    assert page.inner_text(".key-chip-name") == "exiftool.Model"


def test_key_catalog_is_prefetched_before_the_popup_opens(page, webui_base_url):
    with page.expect_response(lambda r: "/api/keys" in r.url):
        page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    assert page.locator("#key-popup").is_hidden()

    later = []

    def on_request(request):
        if "/api/keys" in request.url:
            later.append(request.url)

    page.on("request", on_request)
    page.click("#key-picker")
    page.wait_for_selector(".key-row")
    assert later == []

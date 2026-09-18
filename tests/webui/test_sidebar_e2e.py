def test_sidebar_toggle_persists_across_reload(ready_page):
    page = ready_page
    assert "collapsed" not in (page.get_attribute("#sidebar", "class") or "")

    page.click("#sidebar-toggle")
    page.wait_for_function("document.querySelector('#sidebar').classList.contains('collapsed')")

    page.reload()
    page.wait_for_function("document.querySelector('#sidebar').classList.contains('collapsed')")


def test_search_persists_across_reload(ready_page):
    page = ready_page
    page.fill("#search-input", "cat")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('2 ')")

    page.reload()
    page.wait_for_function("document.querySelector('#search-input').value === 'cat'")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('2 ')")


def test_settings_thumb_size_persists_across_reload(ready_page):
    page = ready_page
    before = page.eval_on_selector("#grid-canvas .cell", "el => el.offsetHeight")
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:not(.hidden)")

    page.select_option("#thumb-size", "512")
    page.wait_for_function("h => document.querySelector('#grid-canvas .cell').offsetHeight > h", arg=before)

    page.keyboard.press("Escape")
    page.wait_for_selector("#settings-modal", state="hidden")

    page.reload()
    page.wait_for_function("h => (document.querySelector('#grid-canvas .cell')?.offsetHeight || 0) > h", arg=before)
    page.click("#settings-btn")
    assert page.input_value("#thumb-size") == "512"

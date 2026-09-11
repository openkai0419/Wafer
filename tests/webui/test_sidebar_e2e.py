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

def _open_first(page):
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer:not(.hidden)")


def test_viewer_next_and_prev(ready_page):
    page = ready_page
    _open_first(page)
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('1/')")

    page.click("#viewer-next")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")

    page.click("#viewer-prev")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('1/')")


def test_viewer_keyboard_navigation(ready_page):
    page = ready_page
    _open_first(page)
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")

    page.keyboard.press("Escape")
    page.wait_for_selector("#viewer", state="hidden")


def test_viewer_meta_panel(ready_page):
    page = ready_page
    _open_first(page)
    page.click("#viewer-info")
    page.wait_for_selector("#meta-panel:not(.hidden)")
    page.wait_for_function("document.querySelector('#meta-content').textContent.includes('File')")


def test_viewer_menu_opens(ready_page):
    page = ready_page
    _open_first(page)
    page.click("#viewer-menu")
    page.wait_for_selector("#viewer-menu-popup:not(.hidden)")
    assert "slideshow" in page.inner_text("#viewer-menu-popup")


def test_slideshow_interval_has_lower_bound(ready_page):
    page = ready_page
    _open_first(page)
    page.click("#viewer-menu")
    interval = page.locator("#viewer-menu-popup input")
    interval.fill("0.5")
    interval.press("Tab")
    interval.fill("0.1")
    interval.press("Tab")
    assert interval.input_value() == "0.5"


def test_slideshow_advances_viewer(ready_page):
    page = ready_page
    _open_first(page)
    interval = page.locator("#viewer-menu-popup input")
    page.click("#viewer-menu")
    interval.fill("0.5")
    interval.press("Tab")
    page.get_by_role("button", name="start slideshow").click()
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")


def test_viewer_select_folder(ready_page):
    page = ready_page
    page.fill("#search-input", "c_cat")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")
    page.wait_for_selector("#grid-canvas .cell[title='c_cat.png']")
    page.click("#grid-canvas .cell[title='c_cat.png']")
    page.wait_for_selector("#viewer:not(.hidden)")
    page.click("#viewer-menu")
    page.get_by_role("button", name="move to folder").click()
    page.wait_for_selector("#viewer", state="hidden")
    page.wait_for_function("document.querySelector('.folder-node.selected')?.textContent.trim() === 'sub'")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")


def test_viewer_next_survives_backend_session_loss(ready_page, webui_query_service):
    page = ready_page
    _open_first(page)
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('1/')")

    webui_query_service._sessions.clear()

    page.click("#viewer-next")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.startsWith('2/')")


def test_meta_panel_groups_keys_by_prefix(ready_page):
    page = ready_page
    _open_first(page)
    page.click("#viewer-info")
    page.wait_for_selector("#meta-panel:not(.hidden)")
    page.wait_for_function("document.querySelectorAll('#meta-content h3').length > 1")

    headings = page.locator("#meta-content h3").all_inner_texts()
    assert headings == ["File", "(no prefix) (2)", "exiftool (2)", "wd14 (1)"]

    keys = page.locator("#meta-content dt").all_inner_texts()
    assert "Model" in keys and "exiftool.Model" not in keys
    assert "prompt" in keys and "animal" in keys

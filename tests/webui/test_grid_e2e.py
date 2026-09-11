def test_grid_renders_and_viewer_opens(ready_page):
    page = ready_page
    cells = page.query_selector_all("#grid-canvas .cell")
    assert cells, "grid rendered no cells"

    cells[0].click()
    page.wait_for_selector("#viewer:not(.hidden)")

    page.click("#viewer-close")
    page.wait_for_selector("#viewer", state="hidden")


def test_no_console_errors_on_load(page, webui_base_url):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    assert not errors, f"console errors on load: {errors}"

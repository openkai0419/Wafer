def _expand_root(page):
    page.locator(".folder-node .expander").nth(1).click()
    page.wait_for_selector(".children:not(.hidden) .folder-node")


def test_folder_selection_filters(ready_page):
    page = ready_page
    _expand_root(page)

    page.click("text=sub")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")


def test_all_files_restores_full_set(ready_page):
    page = ready_page
    _expand_root(page)
    page.click("text=sub")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")

    page.click("text=(all files)")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('5 ')")


def test_expander_only_on_folders_with_children(ready_page):
    page = ready_page
    _expand_root(page)

    root = page.locator(".folder-node").nth(1)
    child = page.locator(".children:not(.hidden) .folder-node").first
    assert child.inner_text().strip() == "sub"
    assert root.locator(".expander .icon").count() == 1
    assert child.locator(".expander .icon").count() == 0

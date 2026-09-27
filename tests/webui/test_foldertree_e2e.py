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



def _wait_total(page, prefix):
    page.wait_for_function(f"document.querySelector('#status').textContent.startsWith('{prefix} ')")


def _set_direct_only(page, checked):
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:not(.hidden)")
    page.set_checked("#direct-only", checked)
    page.keyboard.press("Escape")
    page.wait_for_selector("#settings-modal.hidden", state="attached")


def test_direct_only_drops_files_in_subfolders(ready_page):
    page = ready_page
    page.locator(".folder-node").nth(1).locator("span").last.click()
    _wait_total(page, "5")

    _set_direct_only(page, True)
    _wait_total(page, "4")

    _set_direct_only(page, False)
    _wait_total(page, "5")


def test_direct_only_is_ignored_for_all_files(ready_page):
    page = ready_page
    _set_direct_only(page, True)
    page.wait_for_function("!document.getElementById('load-bar').classList.contains('busy')")
    assert page.inner_text("#status").startswith("5 ")


def test_direct_only_survives_a_reload(ready_page):
    page = ready_page
    page.locator(".folder-node").nth(1).locator("span").last.click()
    _set_direct_only(page, True)
    _wait_total(page, "4")

    page.reload()
    _wait_total(page, "4")
    assert page.is_checked("#direct-only")

def test_expander_only_on_folders_with_children(ready_page):
    page = ready_page
    _expand_root(page)

    root = page.locator(".folder-node").nth(1)
    child = page.locator(".children:not(.hidden) .folder-node").first
    assert child.inner_text().strip() == "sub"
    assert root.locator(".expander .icon").count() == 1
    assert child.locator(".expander .icon").count() == 0

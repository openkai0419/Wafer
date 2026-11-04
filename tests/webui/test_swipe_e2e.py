import pytest

from test_support.touch import Touch

START = (300, 400)
FAR = (60, 400)


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 375, "height": 812}, "is_mobile": True, "has_touch": True}


def caption(page):
    return page.inner_text("#viewer-caption")


def open_first(page):
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer:not(.hidden)")
    wait_for(page, "1/")
    page.wait_for_selector("#viewer:not(.loading)")


def wait_for(page, prefix):
    page.wait_for_function(f"document.querySelector('#viewer-caption').textContent.startsWith('{prefix}')")


def stage_children(page):
    return page.evaluate("document.querySelector('#viewer-stage').children.length")


def swipe_var(page):
    return page.evaluate("document.querySelector('#viewer-stage').style.getPropertyValue('--swipe-x')")


def requests_to(page, fragment):
    seen = []
    page.on("request", lambda request: seen.append(request.url) if fragment in request.url else None)
    return seen


def hold_drag(touch, distance=60):
    touch.start(*START)
    touch.move(START[0] - distance // 2, START[1])
    touch.move(START[0] - distance, START[1])


@pytest.fixture
def viewer_page(ready_page):
    open_first(ready_page)
    return ready_page


def test_a_swipe_left_moves_to_the_next_image(viewer_page):
    Touch(viewer_page).drag(START, FAR)
    wait_for(viewer_page, "2/")


def test_a_swipe_right_moves_back(viewer_page):
    touch = Touch(viewer_page)
    touch.drag(START, FAR)
    wait_for(viewer_page, "2/")
    viewer_page.wait_for_timeout(400)
    touch.drag(FAR, START)
    wait_for(viewer_page, "1/")


def test_a_short_slow_swipe_returns(viewer_page):
    Touch(viewer_page).drag(START, (START[0] - 40, START[1]), steps=8, pause_ms=30)
    viewer_page.wait_for_timeout(500)
    assert caption(viewer_page).startswith("1/")
    assert stage_children(viewer_page) == 1


def test_a_quick_flick_moves(viewer_page):
    Touch(viewer_page).drag(START, (START[0] - 60, START[1]), steps=3)
    wait_for(viewer_page, "2/")


def test_the_preload_is_the_original_and_starts_before_release(viewer_page):
    page = viewer_page
    files = requests_to(page, "/api/file")
    thumbs = requests_to(page, "/api/thumb")
    touch = Touch(page)
    hold_drag(touch)
    page.wait_for_function("document.querySelectorAll('.swipe-pane img').length === 1")
    page.wait_for_timeout(300)
    assert len(files) == 1
    assert thumbs == []
    touch.end()


def test_the_commit_does_not_reload_and_the_bar_clears(viewer_page):
    page = viewer_page
    files = requests_to(page, "/api/file")
    touch = Touch(page)
    hold_drag(touch, 100)
    page.wait_for_function("document.querySelector('.swipe-pane img')?.complete")
    before = len(files)
    touch.end()
    wait_for(page, "2/")
    page.wait_for_selector("#viewer:not(.loading)")
    page.wait_for_timeout(300)
    assert len(files) == before
    assert page.locator("#viewer.loading").count() == 0


def test_the_first_image_does_not_move_back(viewer_page):
    Touch(viewer_page).drag(FAR, START)
    viewer_page.wait_for_timeout(500)
    assert caption(viewer_page).startswith("1/")
    assert stage_children(viewer_page) == 1


def test_the_last_image_does_not_loop(viewer_page):
    page = viewer_page
    total = int(caption(page).split("/")[1].split()[0])
    for _ in range(total - 1):
        page.keyboard.press("ArrowRight")
    wait_for(page, f"{total}/")
    Touch(page).drag(START, FAR)
    page.wait_for_timeout(500)
    assert caption(page).startswith(f"{total}/")
    assert stage_children(page) == 1


def test_a_tap_on_the_backdrop_closes(viewer_page):
    box = viewer_page.locator("#viewer-stage").bounding_box()
    viewer_page.touchscreen.tap(box["x"] + 5, box["y"] + 5)
    viewer_page.wait_for_selector("#viewer", state="hidden")


def test_a_swipe_does_not_close(viewer_page):
    box = viewer_page.locator("#viewer-stage").bounding_box()
    y = box["y"] + 5
    Touch(viewer_page).drag((300, y), (60, y))
    viewer_page.wait_for_timeout(500)
    assert viewer_page.locator("#viewer:not(.hidden)").count() == 1


def test_a_pinch_zoomed_page_does_not_swipe(viewer_page):
    page = viewer_page
    touch = Touch(page)
    touch.pinch((187, 400), 80)
    page.wait_for_function("window.visualViewport.scale > 1.01")
    touch.drag(START, FAR)
    page.wait_for_timeout(500)
    assert caption(page).startswith("1/")


def test_a_mouse_drag_does_not_move(viewer_page):
    page = viewer_page
    page.mouse.move(*START)
    page.mouse.down()
    page.mouse.move(FAR[0], FAR[1], steps=8)
    page.mouse.up()
    page.wait_for_timeout(500)
    assert not caption(page).startswith("2/")
    assert page.locator(".swipe-pane").count() == 0


def test_a_key_during_a_drag_wins(viewer_page):
    page = viewer_page
    touch = Touch(page)
    hold_drag(touch)
    page.keyboard.press("ArrowRight")
    wait_for(page, "2/")
    page.wait_for_selector("#viewer-stage > *")
    assert stage_children(page) == 1
    assert swipe_var(page) == ""
    touch.end()


def test_escape_during_a_drag_closes(viewer_page):
    page = viewer_page
    touch = Touch(page)
    hold_drag(touch)
    page.keyboard.press("Escape")
    page.wait_for_selector("#viewer", state="hidden")
    assert stage_children(page) == 0
    touch.end()


def test_a_cancelled_touch_returns_to_the_center(viewer_page):
    page = viewer_page
    touch = Touch(page)
    hold_drag(touch)
    touch.cancel()
    page.wait_for_timeout(500)
    assert caption(page).startswith("1/")
    assert stage_children(page) == 1
    assert swipe_var(page) == ""


def test_a_swipe_during_settling_moves_again(viewer_page):
    touch = Touch(viewer_page)
    touch.drag(START, FAR)
    touch.drag(START, FAR)
    wait_for(viewer_page, "3/")


def test_the_slideshow_waits_during_a_drag(viewer_page):
    page = viewer_page
    page.click("#viewer-menu")
    page.fill("#viewer-menu-popup input", "0.5")
    page.press("#viewer-menu-popup input", "Tab")
    page.click("#viewer-menu-popup .menu-item:nth-child(2)")
    touch = Touch(page)
    hold_drag(touch, 50)
    page.wait_for_timeout(1000)
    assert caption(page).startswith("1/")
    touch.move(START[0], START[1])
    touch.end()
    wait_for(page, "2/")


def test_a_swipe_closes_the_menu(viewer_page):
    page = viewer_page
    page.click("#viewer-menu")
    page.wait_for_selector("#viewer-menu-popup:not(.hidden)")
    Touch(page).drag(START, FAR)
    page.wait_for_selector("#viewer-menu-popup", state="hidden")


def test_a_video_neighbor_waits_for_the_commit(page, webui_base_url):
    def as_video(route):
        response = route.fetch()
        data = response.json()
        data["items"][1]["kind"] = "video"
        route.fulfill(response=response, json=data)

    page.route("**/api/query/*/items*", as_video)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    open_first(page)
    touch = Touch(page)
    hold_drag(touch, 200)
    page.wait_for_timeout(300)
    assert page.locator("video").count() == 0
    touch.end()
    page.wait_for_selector("#viewer-stage video", state="attached")

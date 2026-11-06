from urllib.parse import parse_qs, urlparse

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


def wait_settled(page):
    page.wait_for_selector("#viewer-stage:not(.swipe-settling)", state="attached")


def stage_children(page):
    return page.evaluate("document.querySelector('#viewer-stage').children.length")


def swipe_var(page):
    return page.evaluate("document.querySelector('#viewer-stage').style.getPropertyValue('--swipe-x')")


def requests_to(page, fragment):
    seen = []
    page.on("request", lambda request: seen.append(request.url) if fragment in request.url else None)
    return seen


def start_slideshow(page, seconds):
    page.click("#viewer-menu")
    page.fill("#viewer-menu-popup input", str(seconds))
    page.press("#viewer-menu-popup input", "Tab")
    page.click("#viewer-menu-popup .menu-item:nth-child(2)")


def hold_drag(touch, distance=60):
    touch.start(*START)
    touch.move(START[0] - distance // 2, START[1])
    touch.move(START[0] - distance, START[1])


@pytest.fixture
def viewer_page(ready_page):
    open_first(ready_page)
    return ready_page


@pytest.fixture
def clock_viewer_page(page, webui_base_url):
    page.clock.install()
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    open_first(page)
    return page


def test_a_swipe_left_moves_to_the_next_image(viewer_page):
    Touch(viewer_page).drag(START, FAR)
    wait_for(viewer_page, "2/")


def test_a_swipe_right_moves_back(viewer_page):
    touch = Touch(viewer_page)
    touch.drag(START, FAR)
    wait_for(viewer_page, "2/")
    touch.drag(FAR, START)
    wait_for(viewer_page, "1/")


def test_a_short_slow_swipe_returns(viewer_page):
    Touch(viewer_page).drag(START, (START[0] - 40, START[1]), steps=8, pause_ms=30)
    wait_settled(viewer_page)
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
    page.wait_for_function("document.querySelector('.swipe-pane img')?.complete")
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
    assert len(files) == before
    assert page.locator("#viewer.loading").count() == 0


def test_the_first_image_does_not_move_back(viewer_page):
    Touch(viewer_page).drag(FAR, START)
    wait_settled(viewer_page)
    assert caption(viewer_page).startswith("1/")
    assert stage_children(viewer_page) == 1


def test_the_last_image_does_not_loop(viewer_page):
    page = viewer_page
    total = int(caption(page).split("/")[1].split()[0])
    for _ in range(total - 1):
        page.keyboard.press("ArrowRight")
    wait_for(page, f"{total}/")
    Touch(page).drag(START, FAR)
    wait_settled(page)
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
    wait_for(viewer_page, "2/")
    assert viewer_page.locator("#viewer:not(.hidden)").count() == 1


def test_a_pinch_zoomed_page_does_not_swipe(viewer_page):
    page = viewer_page
    touch = Touch(page)
    touch.pinch((187, 400), 80)
    page.wait_for_function("window.visualViewport.scale > 1.01")
    touch.drag(START, FAR)
    assert page.locator(".swipe-pane").count() == 0
    assert caption(page).startswith("1/")


def test_a_mouse_drag_does_not_move(viewer_page):
    page = viewer_page
    page.mouse.move(*START)
    page.mouse.down()
    page.mouse.move(FAR[0], FAR[1], steps=8)
    page.mouse.up()
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
    wait_settled(page)
    assert caption(page).startswith("1/")
    assert stage_children(page) == 1
    assert swipe_var(page) == ""


def test_a_swipe_during_settling_moves_again(viewer_page):
    touch = Touch(viewer_page)
    touch.drag(START, FAR)
    touch.drag(START, FAR)
    wait_for(viewer_page, "3/")


def test_the_slideshow_waits_during_a_drag(clock_viewer_page):
    page = clock_viewer_page
    start_slideshow(page, 5)
    touch = Touch(page)
    hold_drag(touch, 50)
    page.clock.fast_forward(6000)
    assert caption(page).startswith("1/")
    touch.move(START[0], START[1])
    touch.end()
    wait_settled(page)
    page.clock.fast_forward(6000)
    wait_for(page, "2/")


def test_the_slideshow_waits_during_a_drag_when_the_image_loads_late(page, webui_base_url):
    page.clock.install()
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    open_first(page)
    held_files = []
    page.route("**/api/file*", lambda route: held_files.append(route))
    start_slideshow(page, 0.5)
    wait_for(page, "2/")
    touch = Touch(page)
    hold_drag(touch)
    for route in held_files:
        route.continue_()
    page.unroute("**/api/file*")
    page.wait_for_function("document.querySelector('#viewer-stage > img')?.complete")
    page.clock.fast_forward(1000)
    assert caption(page).startswith("2/")
    assert page.locator(".swipe-pane").count() == 1
    touch.cancel()
    wait_for(page, "3/")


def test_a_video_ending_during_a_drag_moves_on_after_it(page, webui_base_url):
    def first_as_video(route):
        response = route.fetch()
        data = response.json()
        for item in data["items"]:
            if item["name"].startswith("a_"):
                item["kind"] = "video"
        route.fulfill(response=response, json=data)

    page.route("**/api/query/*/items*", first_as_video)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer-stage video", state="attached")
    start_slideshow(page, 0.5)
    touch = Touch(page)
    touch.start(START[0], 100)
    touch.move(START[0] - 30, 100)
    touch.move(START[0] - 60, 100)
    page.wait_for_selector(".swipe-pane", state="attached")
    page.evaluate(
        "const video = document.querySelector('#viewer-stage video');"
        "Object.defineProperty(video, 'ended', { value: true });"
        "video.dispatchEvent(new Event('ended'));"
    )
    assert page.locator(".swipe-pane").count() == 1
    touch.cancel()
    wait_for(page, "2/")


def test_a_late_item_keeps_the_neighbor_under_the_finger(viewer_page):
    page = viewer_page
    held_items = []
    page.route("**/api/query/*/items*", lambda route: held_items.append(route))
    page.keyboard.press("ArrowRight")
    wait_for(page, "2/")
    touch = Touch(page)
    hold_drag(touch, 200)
    assert page.locator(".swipe-pane img").count() == 1
    while not held_items:
        page.wait_for_timeout(10)
    for route in held_items:
        route.continue_()
    page.unroute("**/api/query/*/items*")
    page.wait_for_function("document.querySelector('#viewer-caption').textContent.includes('b_dog')")
    assert page.locator(".swipe-pane img").count() == 1
    assert page.locator("#viewer-stage > img").count() == 1
    assert swipe_var(page) != ""
    touch.end()
    wait_for(page, "3/")


def test_a_key_past_the_first_image_keeps_the_slideshow(clock_viewer_page):
    page = clock_viewer_page
    start_slideshow(page, 5)
    touch = Touch(page)
    touch.start(*FAR)
    touch.move(FAR[0] + 30, FAR[1])
    touch.move(FAR[0] + 90, FAR[1])
    page.clock.fast_forward(6000)
    page.keyboard.press("ArrowLeft")
    assert swipe_var(page) != ""
    touch.end()
    wait_settled(page)
    page.clock.fast_forward(6000)
    wait_for(page, "2/")


def test_a_cancelled_swipe_on_a_link_does_not_wait_for_the_neighbor_image(page, webui_base_url):
    def first_as_link(route):
        response = route.fetch()
        data = response.json()
        for item in data["items"]:
            if item["name"].startswith("a_"):
                item["kind"] = "other"
        route.fulfill(response=response, json=data)

    page.clock.install()
    page.route("**/api/query/*/items*", first_as_link)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer-stage a")
    held_files = []
    page.route("**/api/file*", lambda route: held_files.append(route))
    start_slideshow(page, 5)
    touch = Touch(page)
    hold_drag(touch)
    page.wait_for_selector(".swipe-pane img", state="attached")
    touch.cancel()
    wait_settled(page)
    page.clock.fast_forward(6000)
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
    page.wait_for_selector(".swipe-pane", state="attached")
    assert page.locator("video").count() == 0
    touch.end()
    page.wait_for_selector("#viewer-stage video", state="attached")


def test_a_background_tap_during_settling_does_not_close(viewer_page):
    page = viewer_page
    touch = Touch(page)
    touch.drag(START, (START[0] - 150, START[1]), steps=10, pause_ms=20)
    page.touchscreen.tap(20, 200)
    page.evaluate("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))))")
    assert page.locator("#viewer:not(.hidden)").count() == 1
    assert caption(page).startswith("2/")


def test_stopping_before_release_does_not_flick(viewer_page):
    page = viewer_page
    touch = Touch(page)
    hold_drag(touch, 60)
    page.wait_for_timeout(300)
    touch.end()
    wait_settled(page)
    assert caption(page).startswith("1/")


def test_a_zoomed_page_can_still_pan_sideways(viewer_page):
    page = viewer_page
    touch = Touch(page)
    touch.pinch((187, 400), 80)
    page.wait_for_function("window.visualViewport.scale > 1.01")
    before = page.evaluate("window.visualViewport.offsetLeft")
    touch.drag((300, 400), (100, 400), steps=10, pause_ms=20)
    page.wait_for_function(f"window.visualViewport.offsetLeft !== {before}")


class SingleItemFetches:
    def __init__(self, page):
        self.holding = False
        self.held = []
        page.route("**/api/query/*/items*", self.handle)

    def handle(self, route):
        limit = parse_qs(urlparse(route.request.url).query)["limit"][0]
        if limit != "1":
            response = route.fetch()
            data = response.json()
            data["items"] = data["items"][:1]
            route.fulfill(response=response, json=data)
        elif self.holding:
            self.held.append(route)
        else:
            route.continue_()

    def wait_until_held(self, page):
        while not self.held:
            page.wait_for_timeout(10)

    def release(self):
        for route in self.held:
            route.continue_()
        self.held.clear()


def open_with_an_unknown_neighbor(page, webui_base_url):
    fetches = SingleItemFetches(page)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    open_first(page)
    return fetches


def close_viewer(page):
    page.keyboard.press("Escape")
    page.wait_for_selector("#viewer", state="hidden")


def assert_the_next_swipe_waits_for_its_own_item(page, fetches):
    fetches.holding = True
    open_first(page)
    Touch(page).drag(START, FAR)
    wait_for(page, "2/")
    assert page.locator("#viewer-stage img").count() == 0
    fetches.release()
    page.wait_for_selector("#viewer-stage img")


def test_closing_forgets_the_neighbor_seen_before(page, webui_base_url):
    fetches = open_with_an_unknown_neighbor(page, webui_base_url)
    Touch(page).drag(START, FAR)
    wait_for(page, "2/")
    page.wait_for_selector("#viewer-stage img")
    close_viewer(page)
    assert_the_next_swipe_waits_for_its_own_item(page, fetches)


def test_a_neighbor_arriving_after_closing_is_ignored(page, webui_base_url):
    fetches = open_with_an_unknown_neighbor(page, webui_base_url)
    fetches.holding = True
    touch = Touch(page)
    hold_drag(touch, 200)
    fetches.wait_until_held(page)
    close_viewer(page)
    touch.end()
    with page.expect_response("**/api/query/*/items*"):
        fetches.release()
    assert_the_next_swipe_waits_for_its_own_item(page, fetches)

import pytest

from test_support.touch import Touch

pytestmark = pytest.mark.controls_fade

MARGIN = (187, 700)
START = (300, 400)
FAR = (60, 400)
CONTROLS = "#viewer-close"
FILL_BOX = "const img = document.querySelector('#viewer-stage img');img.style.width = '100%'; img.style.height = '100%'; img.style.objectFit = 'contain';"


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 375, "height": 812}, "is_mobile": True, "has_touch": True}


@pytest.fixture
def page(page):
    page.clock.install()
    return page


def hidden(page):
    return page.evaluate("document.querySelector('#viewer').classList.contains('controls-hidden')")


def closed(page):
    return page.evaluate("document.querySelector('#viewer').classList.contains('hidden')")


def caption(page):
    return page.inner_text("#viewer-caption")


def wait_for(page, prefix):
    page.wait_for_function(f"document.querySelector('#viewer-caption').textContent.startsWith('{prefix}')")


def open_first(page):
    page.query_selector_all("#grid-canvas .cell")[0].click()
    page.wait_for_selector("#viewer:not(.hidden)")
    wait_for(page, "1/")
    page.wait_for_selector("#viewer:not(.loading)")


@pytest.fixture
def viewer_page(ready_page):
    open_first(ready_page)
    return ready_page


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def image_center(page):
    return center(page.locator("#viewer-stage img").bounding_box())


def wait_until_hidden(page):
    page.clock.fast_forward(3100)
    assert hidden(page)


def start_slideshow(page, seconds):
    page.click("#viewer-menu")
    page.fill("#viewer-menu-popup input", str(seconds))
    page.press("#viewer-menu-popup input", "Tab")
    page.click("#viewer-menu-popup .menu-item:nth-child(2)")


def as_video(route):
    response = route.fetch()
    data = response.json()
    for item in data["items"]:
        if item["name"].startswith("b_dog"):
            item["kind"] = "video"
    route.fulfill(response=response, json=data)


def test_they_stay_for_three_seconds_then_hide(viewer_page):
    page = viewer_page
    page.clock.fast_forward(2000)
    assert not hidden(page)
    page.clock.fast_forward(1100)
    assert hidden(page)


def test_the_fade_takes_half_a_second_and_returning_is_quick(viewer_page):
    page = viewer_page
    duration = f"getComputedStyle(document.querySelector('{CONTROLS}')).transitionDuration"
    assert page.evaluate(duration) == "0.15s"
    wait_until_hidden(page)
    assert page.evaluate(duration) == "0.5s"


def test_reduced_motion_switches_at_once(viewer_page):
    page = viewer_page
    page.emulate_media(reduced_motion="reduce")
    duration = f"getComputedStyle(document.querySelector('{CONTROLS}')).transitionDuration"
    assert page.evaluate(duration) == "0s"
    wait_until_hidden(page)
    assert page.evaluate(duration) == "0s"


def test_a_pointer_move_restarts_the_wait(viewer_page):
    page = viewer_page
    page.clock.fast_forward(2000)
    page.mouse.move(*MARGIN)
    page.clock.fast_forward(2000)
    assert not hidden(page)
    page.clock.fast_forward(1100)
    assert hidden(page)


def test_a_pointer_move_does_not_reveal(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    page.mouse.move(*MARGIN)
    page.mouse.move(100, 100)
    assert hidden(page)


def test_clicking_the_image_toggles(viewer_page):
    page = viewer_page
    x, y = image_center(page)
    page.mouse.click(x, y)
    assert hidden(page)
    page.mouse.click(x, y)
    assert not hidden(page)


def test_tapping_the_image_toggles(viewer_page):
    page = viewer_page
    x, y = image_center(page)
    page.touchscreen.tap(x, y)
    assert hidden(page)
    page.touchscreen.tap(x, y)
    assert not hidden(page)


@pytest.mark.parametrize("hide_first", [False, True])
def test_the_margin_closes_when_visible_and_hidden(viewer_page, hide_first):
    page = viewer_page
    if hide_first:
        wait_until_hidden(page)
    page.mouse.click(*MARGIN)
    assert closed(page)


def drag(page, start, end):
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=8)
    page.mouse.up()


@pytest.mark.parametrize("hide_first", [False, True])
def test_dragging_the_image_changes_nothing(viewer_page, hide_first):
    page = viewer_page
    page.evaluate("window.events = [];for (const type of ['dragstart', 'click']) document.addEventListener(type, () => window.events.push(type), true);")
    x, y = image_center(page)
    if hide_first:
        wait_until_hidden(page)
    for end in [(x + 20, y + 5), MARGIN]:
        drag(page, (x, y), end)
        assert hidden(page) == hide_first
        assert not closed(page)
    events = page.evaluate("window.events")
    assert "dragstart" in events
    assert "click" not in events


def test_moving_while_hidden_stays_hidden(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    Touch(page).drag(START, FAR)
    wait_for(page, "2/")
    assert hidden(page)
    page.keyboard.press("ArrowRight")
    wait_for(page, "3/")
    assert hidden(page)


def test_a_swipe_does_not_toggle(viewer_page):
    page = viewer_page
    touch = Touch(page)
    touch.drag(START, FAR)
    wait_for(page, "2/")
    page.wait_for_timeout(300)
    assert not hidden(page)
    wait_until_hidden(page)
    touch.drag(FAR, START)
    wait_for(page, "1/")
    page.wait_for_timeout(300)
    assert hidden(page)


def test_they_stay_while_the_menu_is_open(viewer_page):
    page = viewer_page
    page.click("#viewer-menu")
    page.clock.fast_forward(3100)
    assert not hidden(page)
    page.click("#viewer-menu")
    page.clock.fast_forward(3100)
    assert hidden(page)


def test_a_tap_with_the_menu_open_only_closes_the_menu(viewer_page):
    page = viewer_page
    page.click("#viewer-menu")
    page.wait_for_selector("#viewer-menu-popup:not(.hidden)")
    page.touchscreen.tap(*image_center(page))
    page.wait_for_selector("#viewer-menu-popup", state="hidden")
    assert not hidden(page)


def test_a_tap_during_the_fade_brings_them_back(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    page.touchscreen.tap(*image_center(page))
    assert not hidden(page)
    page.clock.fast_forward(3100)
    assert hidden(page)


def test_hidden_prev_does_not_move(viewer_page):
    page = viewer_page
    x, y = center(page.locator("#viewer-prev").bounding_box())
    wait_until_hidden(page)
    page.touchscreen.tap(x, y)
    assert closed(page)


def test_tab_focus_reveals(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    page.evaluate("document.activeElement.blur()")
    for _ in range(30):
        page.keyboard.press("Tab")
        if not hidden(page):
            break
    assert not hidden(page)


def test_arrow_keys_do_not_reveal(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    page.keyboard.press("ArrowRight")
    wait_for(page, "2/")
    assert hidden(page)


@pytest.mark.parametrize("hide_first", [False, True])
def test_reopening_starts_visible(viewer_page, hide_first):
    page = viewer_page
    if hide_first:
        wait_until_hidden(page)
    page.keyboard.press("Escape")
    page.wait_for_selector("#viewer", state="hidden")
    page.clock.fast_forward(3100)
    open_first(page)
    assert not hidden(page)


def test_the_load_bar_is_not_hidden(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    assert page.evaluate("getComputedStyle(document.querySelector('#viewer-load')).opacity") == "1"


def test_a_slideshow_step_neither_reveals_nor_restarts(viewer_page):
    page = viewer_page
    start_slideshow(page, 2)
    page.clock.fast_forward(2100)
    wait_for(page, "2/")
    assert not hidden(page)
    page.clock.fast_forward(1000)
    assert hidden(page)
    page.clock.fast_forward(2000)
    wait_for(page, "3/")
    assert hidden(page)


def test_a_tap_while_pinch_zoomed_toggles(viewer_page):
    page = viewer_page
    x, y = image_center(page)
    Touch(page).pinch((x, y), 80)
    page.wait_for_function("window.visualViewport.scale > 1.01")
    assert not hidden(page)
    left, top = page.evaluate("[visualViewport.offsetLeft, visualViewport.offsetTop]")
    page.touchscreen.tap(x - left, y - top)
    assert hidden(page)


def test_the_info_panel_stays_and_does_not_toggle(viewer_page):
    page = viewer_page
    page.click("#viewer-info")
    page.wait_for_selector("#meta-panel:not(.hidden)")
    wait_until_hidden(page)
    panel = page.locator("#meta-panel")
    assert panel.is_visible()
    assert page.evaluate("getComputedStyle(document.querySelector('#meta-panel')).opacity") == "1"
    page.touchscreen.tap(*center(panel.bounding_box()))
    assert hidden(page)
    assert panel.is_visible()


def test_a_video_is_never_hidden(page, webui_base_url):
    page.route("**/api/query/*/items*", as_video)
    page.goto(webui_base_url)
    page.wait_for_selector("#grid-canvas .cell")
    open_first(page)
    wait_until_hidden(page)
    page.route("**/api/file*", lambda route: None)
    page.keyboard.press("ArrowRight")
    page.wait_for_selector("#viewer-stage video", state="attached")
    assert not hidden(page)
    page.clock.fast_forward(3100)
    assert not hidden(page)
    x, y = center(page.locator("#viewer-stage video").bounding_box())
    page.mouse.click(x, y)
    assert not hidden(page)


def test_a_failed_image_reveals_and_stays(viewer_page):
    page = viewer_page
    wait_until_hidden(page)
    page.route("**/api/file*", lambda route: route.fulfill(status=404))
    page.keyboard.press("ArrowRight")
    wait_for(page, "error")
    assert not hidden(page)
    page.clock.fast_forward(3100)
    assert not hidden(page)
    page.evaluate(FILL_BOX)
    page.mouse.click(*image_center(page))
    assert not hidden(page)
    assert not closed(page)


def test_after_a_failure_the_next_image_hides_again(viewer_page):
    page = viewer_page
    start_slideshow(page, 4)
    wait_until_hidden(page)
    page.route("**/api/file*", lambda route: route.fulfill(status=404))
    page.clock.fast_forward(1000)
    wait_for(page, "error")
    assert not hidden(page)
    page.unroute("**/api/file*")
    page.clock.fast_forward(4100)
    wait_for(page, "3/")
    page.wait_for_selector("#viewer:not(.loading)")
    page.clock.fast_forward(3100)
    assert hidden(page)


def test_a_click_outside_the_drawn_image_is_the_margin(viewer_page):
    page = viewer_page
    page.evaluate(FILL_BOX)
    page.mouse.click(187, 406)
    assert hidden(page)
    page.mouse.click(187, 100)
    assert closed(page)

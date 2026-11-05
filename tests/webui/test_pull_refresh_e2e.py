import pytest

from test_support.touch import Touch

PULL_DISTANCE = 300


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 375, "height": 812}, "is_mobile": True, "has_touch": True}


def aspects_requests(page):
    seen = []
    page.on("request", lambda request: seen.append(request.url) if request.url.split("?")[0].endswith("/aspects") else None)
    return seen


def grid_origin(page):
    box = page.locator("#grid-scroll").bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + 10


def assert_no_requery(page, seen):
    assert page.locator("#pull-indicator.hidden").count() == 1
    assert len(seen) == 0


def wait_for_the_requery(page):
    page.wait_for_selector("#pull-indicator.hidden", state="attached")


def test_a_long_pull_requeries_once(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    Touch(page).drag((x, y), (x, y + PULL_DISTANCE))
    wait_for_the_requery(page)
    assert len(seen) == 1


def test_a_short_pull_does_nothing(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    Touch(page).drag((x, y), (x, y + 40))
    assert_no_requery(page, seen)


def test_pulling_back_below_the_threshold_cancels(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    touch = Touch(page)
    touch.start(x, y)
    touch.move(x, y + PULL_DISTANCE)
    assert page.locator("#pull-indicator.armed").count() == 1
    touch.move(x, y + 20)
    assert page.locator("#pull-indicator.armed").count() == 0
    touch.end()
    assert_no_requery(page, seen)


def test_a_pull_from_a_scrolled_grid_does_nothing(ready_page):
    page = ready_page
    page.evaluate("document.querySelector('#grid-canvas').style.height = '3000px'")
    page.evaluate("document.querySelector('#grid-scroll').scrollTop = 100")
    page.wait_for_function("document.querySelector('#grid-scroll').scrollTop === 100")
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    Touch(page).drag((x, y), (x, y + PULL_DISTANCE))
    assert_no_requery(page, seen)


def test_a_short_list_can_still_be_pulled(ready_page):
    page = ready_page
    page.fill("#search-input", "dog")
    page.press("#search-input", "Enter")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('1 ')")
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    Touch(page).drag((x, y), (x, y + PULL_DISTANCE))
    wait_for_the_requery(page)
    assert len(seen) == 1


def test_a_pull_during_a_requery_is_ignored(ready_page):
    page = ready_page
    held = []
    page.route("**/aspects", lambda route: held.append(route))
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    touch = Touch(page)
    touch.drag((x, y), (x, y + PULL_DISTANCE))
    page.wait_for_function("document.querySelector('#pull-indicator').classList.contains('refreshing')")
    touch.start(x, y)
    touch.move(x, y + PULL_DISTANCE)
    assert page.locator("#pull-indicator.refreshing").count() == 1
    touch.end()
    while not held:
        page.wait_for_timeout(10)
    assert len(seen) == 1
    for route in held:
        route.continue_()
    page.wait_for_function("document.querySelector('#pull-indicator').classList.contains('hidden')")


def test_a_cancelled_touch_keeps_the_spinner_during_a_requery(ready_page):
    page = ready_page
    held = []
    page.route("**/aspects", lambda route: held.append(route))
    x, y = grid_origin(page)
    touch = Touch(page)
    touch.drag((x, y), (x, y + PULL_DISTANCE))
    page.wait_for_selector("#pull-indicator.refreshing")
    touch.start(x, y)
    touch.cancel()
    assert page.locator("#pull-indicator.refreshing").count() == 1
    while not held:
        page.wait_for_timeout(10)
    for route in held:
        route.continue_()
    page.wait_for_selector("#pull-indicator.hidden", state="attached")


def test_a_mouse_drag_does_nothing(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + PULL_DISTANCE, steps=12)
    page.mouse.up()
    assert_no_requery(page, seen)


def test_a_second_finger_hides_the_indicator(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    x, y = grid_origin(page)
    touch = Touch(page)
    touch.start(x, y)
    touch.move(x, y + PULL_DISTANCE)
    assert page.locator("#pull-indicator.armed").count() == 1
    touch.dispatch("touchStart", [{"x": x, "y": y + PULL_DISTANCE, "id": 0}, {"x": x + 50, "y": y + PULL_DISTANCE, "id": 1}])
    touch.end()
    assert page.locator("#pull-indicator.hidden").count() == 1
    assert_no_requery(page, seen)


def test_a_tap_after_a_lost_touch_end_does_not_requery(ready_page):
    page = ready_page
    seen = aspects_requests(page)
    box = page.locator("#grid-canvas .cell").first.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    touch = Touch(page)
    touch.start(x, y)
    touch.move(x, y + PULL_DISTANCE)
    assert page.locator("#pull-indicator.armed").count() == 1
    page.evaluate("document.querySelector('#grid-canvas .cell').remove()")
    touch.end()
    assert page.locator("#pull-indicator.armed").count() == 1
    touch.start(*grid_origin(page))
    touch.end()
    assert page.locator("#pull-indicator.hidden").count() == 1
    assert_no_requery(page, seen)

from itertools import pairwise


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


SCROLL_TOP = "document.querySelector('#grid-scroll').scrollTop"
THUMB_SIZE_MAX = 1024


def _start_auto_scroll(page, speed):
    page.set_viewport_size({"width": 500, "height": 320})
    page.wait_for_function("document.querySelector('#grid-scroll').scrollHeight > document.querySelector('#grid-scroll').clientHeight")
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:not(.hidden)")
    _set_speed(page, speed)
    page.click("#auto-scroll-toggle")
    assert page.inner_text("#auto-scroll-toggle") == "on"
    page.wait_for_function(f"{SCROLL_TOP} > 0")


def _set_speed(page, speed):
    page.fill("#auto-scroll-speed-value", str(speed))
    page.press("#auto-scroll-speed-value", "Enter")


def _close_settings(page):
    page.keyboard.press("Escape")
    page.wait_for_selector("#settings-modal", state="hidden")


def test_auto_scroll_loops_back_to_top(ready_page):
    page = ready_page
    page.evaluate("""() => {
      window.__wrapped = false;
      const el = document.querySelector('#grid-scroll');
      let prev = el.scrollTop;
      const tick = () => {
        if (el.scrollTop < prev - 1) window.__wrapped = true;
        prev = el.scrollTop;
        requestAnimationFrame(tick);
      };
      tick();
    }""")

    _start_auto_scroll(page, 500)
    page.wait_for_function("window.__wrapped", timeout=10000)
    assert page.inner_text("#auto-scroll-toggle") == "on"


def test_auto_scroll_stops_on_wheel(ready_page):
    page = ready_page
    _start_auto_scroll(page, 500)
    _close_settings(page)

    page.mouse.move(250, 200)
    page.mouse.wheel(0, 50)
    page.wait_for_function("document.querySelector('#auto-scroll-toggle').textContent === 'off'")

    stopped = page.evaluate(SCROLL_TOP)
    page.wait_for_function(f"{SCROLL_TOP} === {stopped}")


def test_auto_scroll_speed_persists(ready_page):
    page = ready_page
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:not(.hidden)")
    _set_speed(page, 7)
    assert page.input_value("#auto-scroll-speed-value") == "7"
    assert page.evaluate("JSON.parse(localStorage.getItem('wafer.ui')).autoScrollSpeed") == 7


def test_auto_scroll_speed_slider_steps_finer_when_slow(ready_page):
    page = ready_page
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:not(.hidden)")

    def speed_at(index):
        page.fill("#auto-scroll-speed", str(index))
        return int(page.input_value("#auto-scroll-speed-value"))

    slowest = speed_at(0)
    assert slowest == 5
    assert speed_at(1) - slowest == 1

    last = int(page.get_attribute("#auto-scroll-speed", "max"))
    assert speed_at(last) == 500
    assert speed_at(last) - speed_at(last - 1) == 25

    speed_at(last)
    assert page.evaluate("() => { const el = document.querySelector('#auto-scroll-speed-value'); return el.scrollWidth <= el.clientWidth; }"), "speed field clips its value"


def test_auto_scroll_moves_sub_pixel_per_frame(ready_page):
    page = ready_page
    _start_auto_scroll(page, 50)
    page.evaluate("""() => {
      window.__offsets = [];
      const el = document.querySelector('#grid-scroll');
      const canvas = document.querySelector('#grid-canvas');
      const tick = () => {
        const matrix = new DOMMatrixReadOnly(getComputedStyle(canvas).transform);
        window.__offsets.push(el.scrollTop - matrix.m42);
        if (window.__offsets.length < 40) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }""")
    page.wait_for_function("window.__offsets.length >= 40", timeout=10000)

    offsets = page.evaluate("window.__offsets")
    deltas = [b - a for a, b in pairwise(offsets) if b >= a]
    assert deltas, "auto scroll never advanced"
    assert all(0 < d < 3 for d in deltas), f"frames stalled or jumped: {deltas}"
    assert any(abs(d - round(d)) > 0.05 for d in deltas), f"movement is pixel-quantized: {deltas}"


def test_thumbnail_request_covers_displayed_rect(ready_page):
    page = ready_page
    page.wait_for_selector("#grid-canvas .cell img")
    page.wait_for_function("[...document.querySelectorAll('#grid-canvas .cell img')].every((img) => img.complete)")
    measured = page.evaluate("""() => ({
      dpr: devicePixelRatio,
      cells: [...document.querySelectorAll('#grid-canvas .cell')]
        .map((cell) => {
          const img = cell.querySelector('img');
          return img && { longest: Math.max(cell.clientWidth, cell.clientHeight), requested: Number(new URL(img.src).searchParams.get('size')) };
        })
        .filter(Boolean),
    })""")

    assert measured["cells"], "no thumbnails rendered"
    for cell in measured["cells"]:
        needed = min(cell["longest"] * measured["dpr"], THUMB_SIZE_MAX)
        assert cell["requested"] >= needed, f"thumbnail is upscaled: {cell} dpr={measured['dpr']}"

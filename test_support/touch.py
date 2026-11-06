from __future__ import annotations


class Touch:
    def __init__(self, page):
        self.page = page
        self.session = page.context.new_cdp_session(page)

    def dispatch(self, kind: str, points: list[dict]) -> None:
        self.session.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    def start(self, x: float, y: float) -> None:
        self.dispatch("touchStart", [{"x": x, "y": y, "id": 0}])

    def move(self, x: float, y: float) -> None:
        self.dispatch("touchMove", [{"x": x, "y": y, "id": 0}])

    def end(self) -> None:
        self.dispatch("touchEnd", [])

    def cancel(self) -> None:
        self.dispatch("touchCancel", [])

    def drag(self, start: tuple[float, float], end: tuple[float, float], steps: int = 12, pause_ms: int = 0) -> None:
        self.start(*start)
        for i in range(1, steps + 1):
            self.move(start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps)
            if pause_ms:
                self.page.wait_for_timeout(pause_ms)
        self.end()

    def pinch(self, center: tuple[float, float], spread: float) -> None:
        cx, cy = center
        self.dispatch("touchStart", [{"x": cx, "y": cy, "id": 0}, {"x": cx, "y": cy, "id": 1}])
        steps = 8
        for i in range(1, steps + 1):
            d = spread * i / steps
            self.dispatch("touchMove", [{"x": cx - d, "y": cy, "id": 0}, {"x": cx + d, "y": cy, "id": 1}])
        self.end()

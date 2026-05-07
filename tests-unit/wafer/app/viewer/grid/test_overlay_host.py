from wafer.app.viewer.grid import overlay_host as overlay_host_module


class _Helper:
    def __init__(self):
        self.calls = []

    def refresh(self, paths=None, *, force=False):
        self.calls.append((paths, force))


def _make_host(monkeypatch):
    monkeypatch.setattr(overlay_host_module.grid_overlay_registry, "list_all", lambda: [])
    host = overlay_host_module.GridOverlayHost(lambda: None, lambda: "test_db")
    helper = _Helper()
    host._helpers = {"test": helper}
    return host, helper


def test_set_visible_paths_does_not_refresh_overlay_helpers(monkeypatch):
    host, helper = _make_host(monkeypatch)

    host.set_visible_paths(["a.jpg", "b.jpg", "a.jpg"])
    host.set_visible_paths(["a.jpg", "b.jpg"])

    assert host._visible_paths == ("a.jpg", "b.jpg")
    assert helper.calls == []


def test_reload_refreshes_overlay_helpers_without_visible_path_filter(monkeypatch):
    host, helper = _make_host(monkeypatch)

    host.set_visible_paths(["visible.jpg"])
    host.reload()

    assert helper.calls == [(None, True)]
from source.image_viewer.commands.file_viewer import next_file, prev_file
from source.image_viewer.viewer.items import ViewerItems


class DummyRoot:
    def __init__(self):
        self.items = ViewerItems()


class DummyViewerWidget:
    def __init__(self, root):
        self.root = root
        self.path = None

    def set_path(self, path):
        self.path = path


class DummyCtx:
    def __init__(self, viewer_widget, items):
        self._viewer = viewer_widget
        self._items = items

    def get(self, key, default=None):
        return self._viewer if key == "widget" else default

    def get_instance(self, name, default=None):
        if name == "ViewerWidget":
            return self._viewer
        if name == "ViewerItems":
            return self._items
        return default


def test_file_viewer_next_prev_switches_viewer_path():
    root = DummyRoot()
    root.items.set_items(["a", "b", "c"], None, None)
    viewer = DummyViewerWidget(root)
    ctx = DummyCtx(viewer, root.items)

    next_file(ctx)
    assert viewer.path == "a"
    assert root.items.current_index() == 0

    next_file(ctx)
    assert viewer.path == "b"
    assert root.items.current_index() == 1

    prev_file(ctx)
    assert viewer.path == "a"
    assert root.items.current_index() == 0


def test_file_viewer_wrap_option():
    root = DummyRoot()
    root.items.set_items(["a", "b", "c"], None, None)
    viewer = DummyViewerWidget(root)
    ctx = DummyCtx(viewer, root.items)

    next_file(ctx)
    next_file(ctx)
    next_file(ctx)
    assert viewer.path == "c"

    next_file(ctx, loop=True)
    assert viewer.path == "a"

    prev_file(ctx, loop=True)
    assert viewer.path == "c"

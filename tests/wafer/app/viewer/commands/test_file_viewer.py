from wafer.app.viewer.commands.file_viewer import next_file, prev_file
from wafer.app.viewer.preview.file_model import FileViewModel


class DummyCtx:
    def __init__(self, model):
        self._model = model

    def get(self, key, default=None):
        return default

    def get_instance(self, name, default=None):
        if name == "FileViewModel":
            return self._model
        return default


def _make_ctx(paths):
    model = FileViewModel()
    model.set_items(paths, None)
    return DummyCtx(model), model


def test_file_viewer_next_prev_switches_path():
    ctx, model = _make_ctx(["a", "b", "c"])

    next_file(ctx)
    assert model.path() == "b"
    assert model.current_index() == 1

    next_file(ctx)
    assert model.path() == "c"
    assert model.current_index() == 2

    prev_file(ctx)
    assert model.path() == "b"
    assert model.current_index() == 1


def test_file_viewer_wrap_option():
    ctx, model = _make_ctx(["a", "b", "c"])

    next_file(ctx)
    next_file(ctx)
    next_file(ctx)
    assert model.path() == "c"

    next_file(ctx, loop=True)
    assert model.path() == "a"

    prev_file(ctx, loop=True)
    assert model.path() == "c"


def test_file_viewer_empty_model_does_nothing():
    ctx, model = _make_ctx([])
    next_file(ctx)
    assert model.path() is None
    prev_file(ctx)
    assert model.path() is None


def test_file_viewer_step():
    ctx, model = _make_ctx(["a", "b", "c", "d", "e"])

    next_file(ctx)
    assert model.current_index() == 1

    next_file(ctx, step=2)
    assert model.current_index() == 3

    next_file(ctx, step=2)
    assert model.current_index() == 4

    prev_file(ctx, step=3)
    assert model.current_index() == 1

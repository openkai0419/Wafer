import pytest
from source.app.viewer.preview.file_model import FileViewModel


@pytest.fixture
def model():
    return FileViewModel()


def test_initial_state(model):
    assert model.count() == 0
    assert model.path() is None
    assert model.current_index() is None


def test_set_items(model):
    model.set_items(["a", "b", "c"], ["s1", "s2", "s3"])
    assert model.count() == 3
    assert model.path_at(0) == "a"
    assert model.path_at(1) == "b"
    assert model.path_at(2) == "c"
    assert model.sources[0] == "s1"


def test_set_items_normalizes_sources(model):
    model.set_items(["a", "b", "c"], ["s1"])
    assert model.sources[0] == "s1"
    assert model.sources[1] == ""
    assert model.sources[2] == ""


def test_set_items_none(model):
    model.set_items(None, None)
    assert model.count() == 0


def test_set_current_index(model):
    model.set_items(["a", "b", "c"], None)
    model.set_current_index(1)
    assert model.current_index() == 1
    assert model.path() == "b"


def test_set_current_index_clamps(model):
    model.set_items(["a", "b"], None)
    model.set_current_index(100)
    assert model.current_index() == 1
    model.set_current_index(-5)
    assert model.current_index() == 0


def test_set_current_index_none_on_empty(model):
    model.set_current_index(0)
    assert model.current_index() is None


def test_set_path_existing(model):
    model.set_items(["a", "b", "c"], None)
    model.set_path("b")
    assert model.current_index() == 1
    assert model.path() == "b"


def test_set_path_not_in_list(model):
    model.set_items(["a", "b"], None)
    model.set_path("z")
    assert model.path() == "z"
    assert model.count() == 3
    assert model.index_of_path("z") == 2


def test_set_path_none_does_nothing(model):
    model.set_items(["a"], None)
    model.set_path(None)
    assert model.current_index() is None


def test_path_changed_signal(model, qtbot):
    signals = []
    model.pathChanged.connect(lambda p: signals.append(p))
    model.set_items(["a", "b", "c"], None)
    model.set_path("b")
    assert "b" in signals
    model.set_path("c")
    assert "c" in signals


def test_items_changed_signal(model, qtbot):
    signals = []
    model.itemsChanged.connect(lambda: signals.append(True))
    model.set_items(["a"], None)
    assert len(signals) == 1
    model.set_items(["x", "y"], None)
    assert len(signals) == 2


def test_move_current_next(model):
    model.set_items(["a", "b", "c"], None)
    model.set_current_index(0)

    result = model.move_current_next()
    assert result == "b"
    assert model.current_index() == 1

    result = model.move_current_next()
    assert result == "c"
    assert model.current_index() == 2

    result = model.move_current_next()
    assert result == "c"
    assert model.current_index() == 2


def test_move_current_prev(model):
    model.set_items(["a", "b", "c"], None)
    model.set_current_index(2)

    result = model.move_current_prev()
    assert result == "b"
    assert model.current_index() == 1

    result = model.move_current_prev()
    assert result == "a"
    assert model.current_index() == 0

    result = model.move_current_prev()
    assert result == "a"
    assert model.current_index() == 0


def test_move_current_loop(model):
    model.set_items(["a", "b", "c"], None)
    model.set_current_index(2)

    result = model.move_current_next(loop=True)
    assert result == "a"
    assert model.current_index() == 0

    result = model.move_current_prev(loop=True)
    assert result == "c"
    assert model.current_index() == 2


def test_move_current_step(model):
    model.set_items(["a", "b", "c", "d", "e"], None)
    model.set_current_index(0)

    result = model.move_current_next(step=2)
    assert result == "c"
    assert model.current_index() == 2

    result = model.move_current_prev(step=2)
    assert result == "a"
    assert model.current_index() == 0


def test_move_on_empty(model):
    assert model.move_current_next() is None
    assert model.move_current_prev() is None


def test_dbpath_getter():
    model = FileViewModel(dbpath_getter=lambda: "/some/db.sqlite")
    assert model.dbpath == "/some/db.sqlite"


def test_dbpath_getter_none():
    model = FileViewModel()
    assert model.dbpath is None


def test_index_of_path(model):
    model.set_items(["x", "y", "z"], None)
    assert model.index_of_path("y") == 1
    assert model.index_of_path("w") is None


def test_preferred_anchor_prefers_current(model):
    model.set_items(["a", "b", "c"], None)
    model.set_current_index(1)
    assert model.next_index() == 2


def test_next_index_no_current(model):
    model.set_items(["a", "b", "c"], None)
    assert model.next_index() == 0


def test_set_items_preserves_display_path(model):
    model.set_items(["a", "b", "c"], None)
    model.set_path("b")
    assert model.path() == "b"
    model.set_items(["x", "b", "y"], None)
    assert model.path() == "b"
    assert model.current_index() == 1


def test_set_items_keeps_display_path_even_if_absent(model):
    model.set_items(["a", "b", "c"], None)
    model.set_path("b")
    model.set_items(["x", "y", "z"], None)
    assert model.path() == "b"
    assert model.current_index() is None


def test_set_items_no_spurious_path_changed(model):
    model.set_items(["a", "b", "c"], None)
    model.set_path("b")
    signals = []
    model.pathChanged.connect(lambda p: signals.append(p))
    model.set_items(["x", "b", "y"], None)
    assert len(signals) == 0


def test_set_path_same_value_no_signal(model):
    model.set_items(["a", "b"], None)
    model.set_path("a")
    signals = []
    model.pathChanged.connect(lambda p: signals.append(p))
    model.set_path("a")
    assert len(signals) == 0

from wafer.qt.widgets import database_box
from wafer.qt.widgets.database_box import DatabaseBox


def items(box):
    return [(box.itemText(i), box.model().item(i).isEnabled()) for i in range(box.count())]


def test_reload_lists_databases_and_keeps_the_current_one(qtbot, monkeypatch):
    monkeypatch.setattr(database_box, "list_data_db_names", lambda: ["b", "a"])
    box = DatabaseBox()
    qtbot.addWidget(box)
    box.show_quietly("gone")
    box.reload()
    assert [name for name, _ in items(box)] == ["a", "b", "gone"]
    assert box.currentText() == "gone"


def test_can_open_disables_items(qtbot, monkeypatch):
    monkeypatch.setattr(database_box, "list_data_db_names", lambda: ["a", "b"])
    box = DatabaseBox(can_open=lambda name: name == "a")
    qtbot.addWidget(box)
    box.reload()
    assert items(box) == [("a", True), ("b", False)]


def test_without_can_open_every_item_is_enabled(qtbot, monkeypatch):
    monkeypatch.setattr(database_box, "list_data_db_names", lambda: ["a", "b"])
    box = DatabaseBox()
    qtbot.addWidget(box)
    box.reload()
    assert items(box) == [("a", True), ("b", True)]

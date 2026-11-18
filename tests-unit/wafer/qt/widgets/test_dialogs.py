def _click(dialog, text):
    from PySide6 import QtWidgets

    buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
    buttons[text].click()


def test_file_conflict_dialog_returns_role_id_of_translated_button(qtbot, monkeypatch, tmp_path):
    from wafer.qt.widgets import dialogs

    monkeypatch.setattr(dialogs, "t", lambda s: f"<{s}>")
    monkeypatch.setattr(dialogs, "_image_for_source", lambda *a: None)
    dialog = dialogs.FileConflictDialog("msg", src_path=str(tmp_path / "a.txt"), dst_path=str(tmp_path / "b.txt"), choices=("rename", "skip", "cancel"))
    qtbot.addWidget(dialog)
    dialog.apply_all_checkbox.setChecked(True)
    _click(dialog, "<Skip>")
    assert (dialog.choice(), dialog.apply_all()) == ("skip", True)


def test_folder_conflict_dialog_labels_go_through_t(qtbot, monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    from wafer.qt.widgets import dialogs

    monkeypatch.setattr(dialogs, "t", lambda s: f"<{s}>")
    dialog = dialogs.FolderConflictDialog("msg", src_path=str(tmp_path / "a"), dst_path=str(tmp_path / "b"), op="move", show_apply_all=False)
    qtbot.addWidget(dialog)
    texts = {w.text() for w in dialog.findChildren(QtWidgets.QLabel)} | {b.text() for b in dialog.findChildren(QtWidgets.QPushButton)}
    assert {"<Move Source>", "<Move Target>", "<Merge>", "<Rename>", "<Skip>", "<Cancel>"} <= texts
    assert dialog.apply_all_checkbox is None
    _click(dialog, "<Merge>")
    assert dialog.choice() == "merge"
    assert not dialog.apply_all()


def test_conflict_dialog_closed_without_button_has_no_choice(qtbot, tmp_path, monkeypatch):
    from wafer.qt.widgets import dialogs

    monkeypatch.setattr(dialogs, "_image_for_source", lambda *a: None)
    dialog = dialogs.SingleFileConflictDialog("msg", path=str(tmp_path / "a.txt"))
    qtbot.addWidget(dialog)
    dialog.reject()
    assert dialog.choice() is None


def test_file_conflict_dialog_loads_thumbnails_off_the_main_thread(qtbot, monkeypatch, tmp_path):
    import threading

    from PySide6 import QtWidgets
    from PySide6.QtGui import QImage
    from wafer.qt.widgets import dialogs

    threads = []

    def fake_image(path, data, size):
        threads.append(threading.current_thread())
        img = QImage(8, 6, QImage.Format_RGB32)
        img.fill(0)
        return img

    def loaded():
        return [lbl for lbl in dialog.findChildren(QtWidgets.QLabel) if lbl.width() == 8 and lbl.height() == 6]

    monkeypatch.setattr(dialogs, "_image_for_source", fake_image)
    dialog = dialogs.FileConflictDialog("msg", src_path=str(tmp_path / "a.png"), dst_path=str(tmp_path / "b.png"))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: len(loaded()) == 2, timeout=5000)
    assert len(threads) == 2
    assert threading.main_thread() not in threads


def test_drop_operation_dialog_normalizes_operation():
    from wafer.qt.widgets.dialogs import DropOperationDialog

    assert DropOperationDialog.normalize_operation("copy") == "copy"
    assert DropOperationDialog.normalize_operation("move") == "move"
    assert DropOperationDialog.normalize_operation("invalid") == "copy"
    assert DropOperationDialog.normalize_operation(None, default="move") == "move"


def test_drop_target_dialog_normalizes_candidates():
    from wafer.qt.widgets.dialogs import DropTargetDialog

    assert DropTargetDialog.normalize_candidates(["a", "", None, "a", "b"]) == ["a", "b"]


def test_drop_target_dialog_uses_default(qtbot):
    from wafer.qt.widgets.dialogs import DropTargetDialog

    from PySide6 import QtWidgets

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    dialog = DropTargetDialog(["a", "b"], default="b", parent=parent)
    qtbot.addWidget(dialog)
    assert dialog.combo.currentData() == "b"


def test_drop_target_dialog_ok_sets_selected_path(qtbot):
    from wafer.qt.widgets.dialogs import DropTargetDialog

    from PySide6 import QtWidgets

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    dialog = DropTargetDialog(["a", "b"], default="b", parent=parent)
    qtbot.addWidget(dialog)
    dialog._on_button(dialog.ok_text)
    assert dialog.selected_path == "b"


def test_confirm_dialog_disables_named_buttons(qtbot):
    from wafer.qt.widgets.dialogs import ConfirmDialog

    from PySide6 import QtWidgets

    dialog = ConfirmDialog("msg", "title", ("A", "B", "C"), disabled=("B",))
    qtbot.addWidget(dialog)
    buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
    assert buttons["A"].isEnabled()
    assert not buttons["B"].isEnabled()
    assert buttons["C"].isEnabled()

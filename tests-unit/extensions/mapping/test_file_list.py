import numpy as np
from PySide6 import QtCore, QtGui

from extensions.mapping.file_list import FileList


class Owner:
    def thumbnail(self, path):
        return None

    def context_for_selection(self):
        return {"paths": ["y"]}


def test_rows_follow_order_and_selection_roundtrip(qtbot):
    widget = FileList(Owner())
    qtbot.addWidget(widget)
    paths = ["c:/a.png", "c:/b.png", "c:/c.png"]
    widget.set_rows(paths, np.array([2, 0, 1]), [QtGui.QColor("red")] * 3)
    model = widget.model()
    assert [model.index(r, 0).data() for r in range(3)] == ["c.png", "a.png", "b.png"]
    emitted = []
    widget.selection_changed.connect(lambda: emitted.append(1))
    widget.select_rows([0, 1])
    assert widget.selected_rows() == [0, 1] and emitted == []
    widget.selectionModel().select(model.index(0, 0), QtCore.QItemSelectionModel.ClearAndSelect)
    assert widget.selected_rows() == [2] and emitted
    assert widget.extend_context(None, None) == {"paths": ["y"]}

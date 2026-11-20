from PySide6 import QtWidgets

from wafer.qt.commands.binding.mouse.editors import MouseBindingEditor, MouseSection


def test_switching_actions_while_events_are_pending_builds_one_set_of_sections(qtbot, monkeypatch):
    editor = MouseBindingEditor([])
    qtbot.addWidget(editor)
    pending = [2]

    def process_events(*args, **kwargs):
        if pending:
            editor.list_actions.setCurrentRow(pending.pop())

    monkeypatch.setattr(QtWidgets.QApplication, "processEvents", staticmethod(process_events))
    editor.list_actions.setCurrentRow(1)

    in_layout = [editor.sections_layout.itemAt(i).widget() for i in range(editor.sections_layout.count())]
    shown = [w for w in in_layout if isinstance(w, MouseSection)]
    assert len(shown) == len(editor.sections)

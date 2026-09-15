from PySide6 import QtCore, QtWidgets

from wafer.qt.common.visibility import WidgetVisibilityWatcher


class TestWidgetVisibilityWatcher:
    def test_emits_false_on_collapse_and_true_on_restore(self, qtbot):
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        child = QtWidgets.QWidget()
        splitter.addWidget(child)
        splitter.addWidget(QtWidgets.QWidget())
        qtbot.addWidget(splitter)

        watcher = WidgetVisibilityWatcher(child)
        events = []
        watcher.changed.connect(events.append)

        splitter.resize(1000, 400)
        splitter.show()
        qtbot.waitUntil(lambda: watcher.is_visible() is True)

        splitter.setSizes([0, 1000])
        qtbot.waitUntil(lambda: watcher.is_visible() is False)
        assert events[-1] is False

        splitter.setSizes([500, 500])
        qtbot.waitUntil(lambda: watcher.is_visible() is True)
        assert events[-1] is True

    def test_emits_false_on_hide(self, qtbot):
        widget = QtWidgets.QWidget()
        qtbot.addWidget(widget)
        widget.resize(200, 200)
        widget.show()
        qtbot.waitExposed(widget)

        watcher = WidgetVisibilityWatcher(widget)
        events = []
        watcher.changed.connect(events.append)
        assert watcher.is_visible() is True

        widget.hide()
        qtbot.waitUntil(lambda: watcher.is_visible() is False)
        assert events[-1] is False

    def test_no_emit_on_noop_resize_while_visible(self, qtbot):
        widget = QtWidgets.QWidget()
        qtbot.addWidget(widget)
        widget.resize(200, 200)
        widget.show()
        qtbot.waitExposed(widget)

        watcher = WidgetVisibilityWatcher(widget)
        events = []
        watcher.changed.connect(events.append)
        widget.resize(220, 220)
        qtbot.wait(50)
        assert events == []
        assert watcher.is_visible() is True

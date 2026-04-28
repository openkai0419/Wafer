import py_compile

from PySide6 import QtWidgets


def test_compile():
    py_compile.compile("wafer/ui/widgets/eliding.py")


class TestElidingLabel:
    def test_keeps_full_text_in_tooltip_and_small_minimum_hint(self, qtbot):
        from wafer.ui.widgets.eliding import ElidingLabel

        label = ElidingLabel("A" * 200, minimum_hint_width=40)
        qtbot.addWidget(label)
        assert label.toolTip() == "A" * 200
        assert label.full_text() == "A" * 200
        assert label.minimumSizeHint().width() == 40

    def test_uses_ignored_policy_by_default(self, qtbot):
        from wafer.ui.widgets.eliding import ElidingLabel

        label = ElidingLabel("long")
        qtbot.addWidget(label)
        assert label.minimumWidth() == 0
        assert label.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored


class TestElidingToolButton:
    def test_keeps_full_text_in_tooltip_and_small_minimum_hint(self, qtbot):
        from wafer.ui.widgets.eliding import ElidingToolButton

        button = ElidingToolButton("B" * 200, minimum_hint_width=24, width_margin=8)
        qtbot.addWidget(button)
        assert button.toolTip() == "B" * 200
        assert button.full_text() == "B" * 200
        assert button.minimumSizeHint().width() == 24

    def test_uses_ignored_policy_by_default(self, qtbot):
        from wafer.ui.widgets.eliding import ElidingToolButton

        button = ElidingToolButton("long")
        qtbot.addWidget(button)
        assert button.minimumWidth() == 0
        assert button.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored

import py_compile
from PySide6 import QtCore, QtWidgets


def test_compile():
    py_compile.compile("wafer/app/viewer/widgets/callout_overlay.py")


def test_create_and_show(qtbot):
    target = QtWidgets.QPushButton("Test")
    target.show()
    qtbot.addWidget(target)

    from wafer.app.viewer.widgets.callout_overlay import CalloutOverlay

    overlay = CalloutOverlay(target, "Test callout")
    overlay.show()
    assert overlay.isVisible()
    assert overlay._track_timer.isActive()
    overlay.close()


def test_dismiss_emits_signal(qtbot):
    target = QtWidgets.QPushButton("Test")
    target.show()
    qtbot.addWidget(target)

    from wafer.app.viewer.widgets.callout_overlay import CalloutOverlay

    overlay = CalloutOverlay(target, "Test callout")
    overlay.show()
    assert overlay.isVisible()
    qtbot.waitUntil(lambda: overlay._fade_anim is None or overlay._fade_anim.state() != QtCore.QAbstractAnimation.Running, timeout=2000)
    with qtbot.waitSignal(overlay.dismissed, timeout=2000):
        overlay.dismiss()
    assert not overlay._track_timer.isActive()


def test_reposition_follows_target(qtbot):
    parent = QtWidgets.QWidget()
    parent.resize(400, 300)
    parent.show()
    qtbot.addWidget(parent)

    target = QtWidgets.QPushButton("Btn", parent)
    target.move(100, 50)
    target.show()

    from wafer.app.viewer.widgets.callout_overlay import CalloutOverlay

    overlay = CalloutOverlay(target, "Follow me")
    overlay.show()
    pos1 = overlay.pos()

    parent.move(parent.x() + 50, parent.y() + 50)
    overlay._last_anchor = QtCore.QPoint()
    overlay._reposition()
    pos2 = overlay.pos()

    assert pos1 != pos2
    overlay.close()


def test_hide_stops_timer(qtbot):
    target = QtWidgets.QPushButton("Test")
    target.show()
    qtbot.addWidget(target)

    from wafer.app.viewer.widgets.callout_overlay import CalloutOverlay

    overlay = CalloutOverlay(target, "Test")
    overlay.show()
    assert overlay._track_timer.isActive()
    overlay.hide()
    assert not overlay._track_timer.isActive()


def test_reposition_skips_when_anchor_unchanged(qtbot):
    target = QtWidgets.QPushButton("Test")
    target.show()
    qtbot.addWidget(target)

    from wafer.app.viewer.widgets.callout_overlay import CalloutOverlay

    overlay = CalloutOverlay(target, "Test")
    overlay.show()
    overlay._reposition()
    pos1 = overlay.pos()
    overlay._reposition()
    pos2 = overlay.pos()
    assert pos1 == pos2
    overlay.close()

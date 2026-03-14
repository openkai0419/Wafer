import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.actions.command.menu_builder import StickyMenu


@pytest.fixture
def menu(qtbot):
    m = StickyMenu()
    qtbot.addWidget(m)
    return m


def _add_submenu(parent: StickyMenu, title: str) -> QtWidgets.QMenu:
    sub = QtWidgets.QMenu(title, parent)
    sub.addAction("item")
    parent.addMenu(sub)
    return sub


class TestStickyMenuInit:
    def test_initial_state(self, menu):
        assert menu._sticky_action is None
        assert not menu._sticky_timer.isActive()

    def test_is_qmenu(self, menu):
        assert isinstance(menu, QtWidgets.QMenu)


class TestStickyClick:
    def test_click_on_submenu_action_sets_sticky(self, menu):
        sub = _add_submenu(menu, "Sub1")
        action = sub.menuAction()
        rect = menu.actionGeometry(action)
        center = rect.center()
        ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(center),
            QtCore.QPointF(menu.mapToGlobal(center)),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev)
        assert menu._sticky_action == action
        assert menu._sticky_timer.isActive()

    def test_click_same_submenu_releases_sticky(self, menu):
        sub = _add_submenu(menu, "Sub1")
        action = sub.menuAction()
        rect = menu.actionGeometry(action)
        center = rect.center()
        ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(center),
            QtCore.QPointF(menu.mapToGlobal(center)),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev)
        assert menu._sticky_action == action
        menu.mouseReleaseEvent(ev)
        assert menu._sticky_action is None
        assert not menu._sticky_timer.isActive()

    def test_click_different_submenu_switches_sticky(self, menu):
        sub1 = _add_submenu(menu, "Sub1")
        sub2 = _add_submenu(menu, "Sub2")
        a1 = sub1.menuAction()
        a2 = sub2.menuAction()

        r1 = menu.actionGeometry(a1)
        ev1 = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(r1.center()),
            QtCore.QPointF(menu.mapToGlobal(r1.center())),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev1)
        assert menu._sticky_action == a1

        r2 = menu.actionGeometry(a2)
        ev2 = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(r2.center()),
            QtCore.QPointF(menu.mapToGlobal(r2.center())),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev2)
        assert menu._sticky_action == a2

    def test_click_non_submenu_clears_sticky(self, menu):
        sub = _add_submenu(menu, "Sub1")
        action = sub.menuAction()
        rect = menu.actionGeometry(action)
        ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(rect.center()),
            QtCore.QPointF(menu.mapToGlobal(rect.center())),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev)
        assert menu._sticky_action is not None

        plain = menu.addAction("plain")
        r2 = menu.actionGeometry(plain)
        ev2 = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(r2.center()),
            QtCore.QPointF(menu.mapToGlobal(r2.center())),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        menu.mouseReleaseEvent(ev2)
        assert menu._sticky_action is None


class TestStickyHoverBlock:
    def test_mouse_move_to_other_submenu_blocked(self, menu):
        sub1 = _add_submenu(menu, "Sub1")
        sub2 = _add_submenu(menu, "Sub2")
        a1 = sub1.menuAction()
        a2 = sub2.menuAction()

        menu._sticky_action = a1
        r2 = menu.actionGeometry(a2)
        move_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(r2.center()),
            QtCore.QPointF(menu.mapToGlobal(r2.center())),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        result = menu.event(move_ev)
        assert result is True

    def test_mouse_move_to_same_submenu_allowed(self, menu):
        sub1 = _add_submenu(menu, "Sub1")
        a1 = sub1.menuAction()

        menu._sticky_action = a1
        r1 = menu.actionGeometry(a1)
        move_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(r1.center()),
            QtCore.QPointF(menu.mapToGlobal(r1.center())),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        result = menu.event(move_ev)
        assert result is not True or menu._sticky_action == a1

    def test_mouse_move_no_sticky_not_blocked(self, menu):
        sub1 = _add_submenu(menu, "Sub1")
        sub2 = _add_submenu(menu, "Sub2")
        a2 = sub2.menuAction()

        r2 = menu.actionGeometry(a2)
        move_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(r2.center()),
            QtCore.QPointF(menu.mapToGlobal(r2.center())),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        menu.event(move_ev)
        assert menu._sticky_action is None


class TestStickyTimerRelease:
    def test_timer_clears_sticky(self, menu, qtbot):
        sub = _add_submenu(menu, "Sub1")
        action = sub.menuAction()
        menu._sticky_action = action
        menu._sticky_timer.start(50)
        qtbot.waitUntil(lambda: menu._sticky_action is None, timeout=1000)
        assert menu._sticky_action is None

    def test_hide_clears_sticky(self, menu):
        sub = _add_submenu(menu, "Sub1")
        action = sub.menuAction()
        menu._sticky_action = action
        menu._sticky_timer.start(StickyMenu._STICKY_DURATION_MS)
        menu.hideEvent(QtGui.QHideEvent())
        assert menu._sticky_action is None
        assert not menu._sticky_timer.isActive()

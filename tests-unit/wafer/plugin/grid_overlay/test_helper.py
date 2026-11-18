import shiboken6
from PySide6 import QtCore

from wafer.plugin.grid_overlay.helper import OverlayHelper


class _Host(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.updates = 0

    @QtCore.Slot()
    def request_update(self):
        self.updates += 1


def test_rebinding_moves_updates_to_the_new_host(qapp):
    helper = OverlayHelper("*", "tag")
    old, new = _Host(), _Host()
    helper.bind_host(old)
    helper.bind_host(new)
    helper.changed.emit()
    assert (old.updates, new.updates) == (0, 1)


def test_rebinding_after_the_old_host_is_deleted(qapp):
    helper = OverlayHelper("*", "tag")
    old, new = _Host(), _Host()
    helper.bind_host(old)
    shiboken6.delete(old)
    helper.bind_host(new)
    helper.changed.emit()
    assert new.updates == 1


def test_binding_the_same_host_twice_connects_once(qapp):
    helper = OverlayHelper("*", "tag")
    host = _Host()
    helper.bind_host(host)
    helper.bind_host(host)
    helper.changed.emit()
    assert host.updates == 1

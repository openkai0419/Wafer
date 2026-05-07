from PySide6 import QtCore

from wafer.builtins.mark.overlay import MarkBadgeOverlayPlugin
from wafer.builtins.mark.registry import MarkRegistry


class _Host(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.update_count = 0

    def request_update(self):
        self.update_count += 1


def test_mark_overlay_requests_update_when_mark_shape_changes():
    host = _Host()
    plugin = MarkBadgeOverlayPlugin()
    plugin.bind_host(host)

    reg = MarkRegistry.instance()
    mark_id = reg.add("Overlay Shape Mark", "#123456", mark_key="circle")
    try:
        before = host.update_count
        reg.set_mark_key(mark_id, "heart")
        assert host.update_count == before + 1
    finally:
        reg.remove(mark_id)
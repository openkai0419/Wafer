import pytest
from PySide6 import QtWidgets

from wafer.core.commands.binding.instance_registry import InstanceRegistry
from wafer.core.state import StateStore


@pytest.fixture(autouse=True)
def _reset_registries():
    prev_registry = InstanceRegistry._instance
    prev_state = StateStore._instance
    InstanceRegistry._instance = None
    StateStore._instance = None
    yield
    InstanceRegistry._instance = prev_registry
    StateStore._instance = prev_state


def test_mark_filter_widget_syncs_overlay_controls(qtbot):
    from wafer.builtins.mark.widget import MarkFilterWidget

    class _Host:
        def __init__(self):
            self._badge_visible = True
            self._badge_radius = 8
            from PySide6 import QtCore

            class _Sig(QtCore.QObject):
                changed = QtCore.Signal()

            self._sig = _Sig()
            self.changed = self._sig.changed

        def plugin(self, name):
            return None

        def request_update(self):
            self.changed.emit()

        def database_path(self):
            return None

        def badge_visible(self):
            return self._badge_visible

        def set_badge_visible(self, v):
            self._badge_visible = bool(v)
            self.request_update()

        def badge_radius(self):
            return self._badge_radius

        def set_badge_radius(self, v):
            self._badge_radius = int(v)
            self.request_update()

    host = _Host()
    InstanceRegistry.instance().register("GridOverlayHost", host)

    widget = MarkFilterWidget()
    qtbot.addWidget(widget)

    labels = [label.text() for label in widget._popup.findChildren(QtWidgets.QLabel)]
    assert "Mark Filter Options" in labels

    host.set_badge_visible(False)
    host.set_badge_radius(22)

    assert widget._popup.overlay_check.isChecked() is False
    assert widget._popup.radius_spin.value() == 22

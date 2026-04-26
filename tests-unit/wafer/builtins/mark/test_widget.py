import pytest

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
    from wafer.app.viewer.grid.mark_overlay_service import MarkOverlayService
    from wafer.builtins.mark.widget import MarkFilterWidget

    svc = MarkOverlayService(lambda: None)
    InstanceRegistry.instance().register("MarkOverlayService", svc)

    widget = MarkFilterWidget()
    qtbot.addWidget(widget)

    svc.set_visible(False)
    svc.set_radius(22)

    assert widget._popup.overlay_check.isChecked() is False
    assert widget._popup.radius_spin.value() == 22

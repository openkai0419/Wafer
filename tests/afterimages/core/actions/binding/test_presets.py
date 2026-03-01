from afterimages.core.actions.binding.key.sequence import KeySequence
from afterimages.core.actions.binding.key.store import KeyBindingStore
from afterimages.core.actions.binding.mouse.mouseeventmanager import MouseActionKey, MouseButton, ClickType
from afterimages.core.actions.binding.mouse.store import MouseBindingStore
from afterimages.core.actions.binding.presets import set_presets
from afterimages.core.actions.bridge import ActionKit


def test_preset_mouse_bindings_load():
    set_presets(mouse="standard")
    data = MouseBindingStore()._seed_data()
    assert data
    assert all(isinstance(k, MouseActionKey) for k in data.keys())


def test_preset_key_bindings_load():
    set_presets(key="standard")
    data = KeyBindingStore()._seed_data()
    assert data
    assert all(isinstance(k, KeySequence) for k in data.keys())


def test_preset_mouse_bindings_content():
    set_presets(mouse="standard")
    data = MouseBindingStore()._seed_data()
    right_single = ActionKit.Mouse("RIGHT", "SINGLE")
    assert right_single in data
    assert data[right_single]["*"].id == "allmenu"

    wheel_up = ActionKit.Mouse("NONE", "WHEEL_UP")
    assert data[wheel_up]["ImageView"].id == "imgv.zoom_in"
    assert data[wheel_up]["GridView"].id == "grid.scroll_up"

    wheel_down = ActionKit.Mouse("NONE", "WHEEL_DOWN")
    assert data[wheel_down]["ImageView"].id == "imgv.zoom_out"

    dbl = ActionKit.Mouse("LEFT", "DOUBLE")
    assert data[dbl]["ImageView"].id == "imgv.toggle_fit_mode"

    drag = ActionKit.Mouse("LEFT", "DRAG_START")
    assert data[drag]["ImageView"].id == "imgv.pan"


def test_kit_key_factory():
    k = ActionKit.Key("H")
    assert isinstance(k, KeySequence)
    assert k == KeySequence(["H"])


def test_kit_mouse_factory():
    m = ActionKit.Mouse("RIGHT", "SINGLE")
    assert isinstance(m, MouseActionKey)
    assert m.button == MouseButton.RIGHT
    assert m.click_type == ClickType.SINGLE

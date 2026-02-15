from source.actions.binding.key.sequence import KeySequence
from source.actions.binding.key.store import KeyBindingStore
from source.actions.binding.mouse.mouseeventmanager import MouseActionKey, MouseButton, ClickType
from source.actions.binding.mouse.store import MouseBindingStore
from source.actions.binding.seed import set_presets
from source.actions.bridge import Kit


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
    right_single = Kit.Mouse("RIGHT", "SINGLE")
    assert right_single in data
    assert data[right_single]["*"].id == "allmenu"

    wheel_up = Kit.Mouse("NONE", "WHEEL_UP")
    assert data[wheel_up]["ImageView"].id == "imgv.zoom_in"
    assert data[wheel_up]["GridView"].id == "grid.scroll_up"

    wheel_down = Kit.Mouse("NONE", "WHEEL_DOWN")
    assert data[wheel_down]["ImageView"].id == "imgv.zoom_out"

    dbl = Kit.Mouse("LEFT", "DOUBLE")
    assert data[dbl]["ImageView"].id == "imgv.toggle_fit_mode"

    drag = Kit.Mouse("LEFT", "DRAG_START")
    assert data[drag]["ImageView"].id == "imgv.pan"


def test_kit_key_factory():
    k = Kit.Key("H")
    assert isinstance(k, KeySequence)
    assert k == KeySequence(["H"])


def test_kit_mouse_factory():
    m = Kit.Mouse("RIGHT", "SINGLE")
    assert isinstance(m, MouseActionKey)
    assert m.button == MouseButton.RIGHT
    assert m.click_type == ClickType.SINGLE

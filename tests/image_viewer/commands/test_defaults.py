from source.actions.binding.key.sequence import KeySequence
from source.actions.binding.mouse.mouseeventmanager import MouseActionKey, MouseButton, ClickType
from source.actions.bridge import Kit
from source.image_viewer.commands.defaults import default_key_bindings, default_mouse_bindings


def test_default_key_bindings_use_keysequence():
    d = default_key_bindings()
    assert d
    assert all(isinstance(k, KeySequence) for k in d.keys())


def test_default_mouse_bindings_use_mouseactionkey():
    d = default_mouse_bindings()
    assert d
    assert all(isinstance(k, MouseActionKey) for k in d.keys())


def test_kit_key_factory():
    k = Kit.Key("H")
    assert isinstance(k, KeySequence)
    assert k == KeySequence(["H"])


def test_kit_mouse_factory():
    m = Kit.Mouse("RIGHT", "SINGLE")
    assert isinstance(m, MouseActionKey)
    assert m.button == MouseButton.RIGHT
    assert m.click_type == ClickType.SINGLE

from __future__ import annotations

def set_seed_bindings(*, mouse_bindings=None, key_bindings=None) -> None:
    global _mouse_bindings, _key_bindings
    if mouse_bindings is not None:
        _mouse_bindings = mouse_bindings
    if key_bindings is not None:
        _key_bindings = key_bindings

def get_seed_mouse_bindings():
    return _mouse_bindings

def get_seed_key_bindings():
    return _key_bindings

_mouse_bindings = None
_key_bindings = None

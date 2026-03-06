import json
import py_compile

from wayfer.utils.helpers import invoke, invoke_int, get_callable, to_int, try_invoke, try_cast, try_json_loads, widget_prop_bool


class _Obj:
    def __init__(self, v=None):
        self._v = v

    def f(self):
        return self._v


class _Widget:
    def __init__(self, v=None, raise_on_property: bool = False):
        self._v = v
        self._raise = raise_on_property

    def property(self, _name: str):
        if self._raise:
            raise RuntimeError("boom")
        return self._v


def test_compile():
    py_compile.compile('wayfer/utils/helpers.py')


def test_get_callable_and_invoke():
    o = _Obj(123)
    assert get_callable(o, "f") is not None
    assert invoke(o, "f") == 123
    assert get_callable(o, "missing") is None
    assert invoke(o, "missing") is None


def test_invoke_int():
    assert invoke_int(_Obj(None), "f", 7) == 7
    assert invoke_int(_Obj(5), "f", 7) == 5
    assert invoke_int(_Obj(True), "f", 7) == 1
    assert invoke_int(_Obj(" 42 "), "f", 7) == 42
    assert invoke_int(_Obj("4.2"), "f", 7) == 7
    assert invoke_int(_Obj(object()), "f", 7) == 7


def test_widget_prop_bool():
    assert widget_prop_bool(None, "x") is False
    assert widget_prop_bool(_Widget(True), "x") is True
    assert widget_prop_bool(_Widget(1), "x") is True
    assert widget_prop_bool(_Widget(0), "x") is False
    assert widget_prop_bool(_Widget(""), "x") is False
    assert widget_prop_bool(_Widget("nonempty"), "x") is True
    assert widget_prop_bool(_Widget(raise_on_property=True), "x") is False


def test_to_int():
    assert to_int(None, 7) == 7
    assert to_int(5, 7) == 5
    assert to_int(True, 7) == 1
    assert to_int(" 42 ", 7) == 42
    assert to_int("4.2", 7) == 7
    assert to_int(object(), 7) == 7


def test_try_cast_and_try_json_loads_and_try_invoke():
    assert try_cast(int, "123", None) == 123
    assert try_cast(int, "x", 9) == 9
    assert try_json_loads('{"a": 1}', None) == {"a": 1}
    assert try_json_loads('bad', None) is None
    seen = []
    assert try_json_loads('bad', 123, on_error=lambda e: seen.append(type(e))) == 123
    assert seen == [json.JSONDecodeError]

    class _Bad:
        def f(self):
            raise RuntimeError("boom")

    assert try_invoke(_Bad(), "f", 7) == 7

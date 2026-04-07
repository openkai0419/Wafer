from wafer.utils.helpers import (
    get_callable,
    invoke,
    invoke_int,
    to_int,
    try_cast,
    try_json_loads,
    try_invoke,
)


class _Dummy:
    def greet(self):
        return "hello"

    def get_value(self):
        return 42

    not_callable = "string"


class TestGetCallable:
    def test_existing_method(self):
        d = _Dummy()
        assert get_callable(d, "greet") is not None

    def test_non_callable_attribute(self):
        d = _Dummy()
        assert get_callable(d, "not_callable") is None

    def test_missing_attribute(self):
        d = _Dummy()
        assert get_callable(d, "nope") is None


class TestInvoke:
    def test_invoke_existing(self):
        assert invoke(_Dummy(), "greet") == "hello"

    def test_invoke_missing(self):
        assert invoke(_Dummy(), "missing") is None


class TestInvokeInt:
    def test_invoke_int_method(self):
        assert invoke_int(_Dummy(), "get_value") == 42

    def test_invoke_int_missing_returns_default(self):
        assert invoke_int(_Dummy(), "nope", default=99) == 99


class TestToInt:
    def test_int_value(self):
        assert to_int(10) == 10

    def test_string_digit(self):
        assert to_int("42") == 42

    def test_string_non_digit(self):
        assert to_int("abc", 0) == 0

    def test_none_returns_default(self):
        assert to_int(None, 5) == 5

    def test_float_truncated(self):
        assert to_int(3.9) == 3

    def test_bool_not_treated_as_int(self):
        assert to_int(True, 0) == 1

    def test_empty_string(self):
        assert to_int("", 7) == 7

    def test_string_with_spaces(self):
        assert to_int("  123  ") == 123


class TestTryCast:
    def test_successful_cast(self):
        assert try_cast(int, "42") == 42

    def test_failed_cast(self):
        assert try_cast(int, "abc", default=-1) == -1

    def test_none_default(self):
        assert try_cast(float, "xyz") is None


class TestTryJsonLoads:
    def test_valid_json(self):
        assert try_json_loads('{"a": 1}') == {"a": 1}

    def test_invalid_json(self):
        assert try_json_loads("{bad}") is None

    def test_non_string_returns_default(self):
        assert try_json_loads(42, default="fallback") == "fallback"

    def test_on_error_called(self):
        errors = []
        try_json_loads("{bad}", on_error=lambda e: errors.append(e))
        assert len(errors) == 1

    def test_valid_list(self):
        assert try_json_loads("[1,2,3]") == [1, 2, 3]


class TestTryInvoke:
    def test_success(self):
        assert try_invoke(_Dummy(), "greet") == "hello"

    def test_missing_returns_default(self):
        assert try_invoke(_Dummy(), "nope", default="fallback") == "fallback"

    def test_exception_returns_default(self):
        class Broken:
            def fail(self):
                raise ValueError("boom")

        assert try_invoke(Broken(), "fail", default="safe") == "safe"

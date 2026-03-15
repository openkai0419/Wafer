from wafer.core.commands.command.core import (
    CommandRegistry, CommandMeta, CommandParam, create_command_from_meta,
)


def test_get_commands_by_category_includes_dot_ids():
    registry = CommandRegistry.instance()
    prev = registry.get_all_commands()
    try:
        registry._commands = {}

        base_meta = CommandMeta(id="filerunner.start", display="Base", category="drop", target_widgets=["GridView"])

        registry.register(create_command_from_meta(base_meta))

        out = registry.get_commands_by_category("drop", widget_scope="GridView")
        assert "filerunner.start" in out
    finally:
        registry._commands = prev


class TestCommandParamChoicesFn:

    def test_callable_value_sets_choices_fn(self):
        fn = lambda: ["a", "b", "c"]
        p = CommandParam(name="x", value=fn)
        assert p.choices_fn is fn
        assert p.choices is None
        assert p.default == ""

    def test_resolve_choices_calls_fn(self):
        p = CommandParam(name="x", value=lambda: ["a", "b"])
        assert p.resolve_choices() == ["a", "b"]

    def test_resolve_choices_returns_static(self):
        p = CommandParam(name="x", value=["a", "b"])
        assert p.resolve_choices() == ["a", "b"]

    def test_resolve_choices_returns_none_for_scalar(self):
        p = CommandParam(name="x", value=10)
        assert p.resolve_choices() is None

    def test_callable_with_explicit_default(self):
        p = CommandParam(name="x", value=lambda: ["a", "b"], default="a")
        assert p.default == "a"
        assert p.type is str

    def test_required_defaults_false(self):
        p = CommandParam(name="x", value=10)
        assert p.required is False

    def test_required_explicit_true(self):
        p = CommandParam(name="x", value="", required=True)
        assert p.required is True

    def test_type_class_not_treated_as_callable(self):
        p = CommandParam(name="x", value=int)
        assert p.choices_fn is None
        assert p.choices is None

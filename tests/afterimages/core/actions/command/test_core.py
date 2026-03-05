from afterimages.core.actions.command.core import CommandRegistry, CommandMeta, create_command_from_meta


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

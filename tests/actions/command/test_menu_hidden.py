from source.actions.command.core import CommandMeta, CommandRegistry
from source.actions.command.maker import MenuMaker
from source.actions.command.menu import RegistryBackedMenu, MenuHub


def test_hidden_command_is_registered_but_not_listed_in_picker_menu():
    class _HiddenMenu(RegistryBackedMenu):
        prefix = "__TestHiddenMenu__"
        commands = [
            CommandMeta(path="__test_hidden_visible_cmd__", display="Visible", func=lambda ctx: None),
            CommandMeta(path="__test_hidden_internal_cmd__", display="Internal", func=lambda ctx: None, hidden=True),
        ]

    _HiddenMenu.register()

    reg = CommandRegistry()
    assert reg.has_command("__test_hidden_visible_cmd__")
    assert reg.has_command("__test_hidden_internal_cmd__")

    hub = MenuHub()
    assert hub.get_path_by_command_id("__test_hidden_visible_cmd__") == "__TestHiddenMenu__/__test_hidden_visible_cmd__"
    assert hub.get_path_by_command_id("__test_hidden_internal_cmd__") == "__TestHiddenMenu__/__test_hidden_internal_cmd__"

    maker = MenuMaker()
    tokens = maker.use("__TestHiddenMenu__").resolve_tokens()
    assert "__test_hidden_visible_cmd__" in tokens
    assert "__test_hidden_internal_cmd__" not in tokens

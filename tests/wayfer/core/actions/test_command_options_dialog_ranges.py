from __future__ import annotations


def test_int_default_99_allows_100(qtbot, tmp_path):
    from wayfer.core.actions.command.core import CommandMeta, CommandParam
    from wayfer.core.actions.command.state import CommandOptionStore
    from wayfer.core.actions.command.option_dialog import CommandOptionsDialog

    prev_instance = getattr(CommandOptionStore, "_instance", None)
    prev_initialized = getattr(CommandOptionStore, "_initialized", False)
    prev_default_path = getattr(CommandOptionStore, "_default_path", None)

    try:
        CommandOptionStore._instance = None
        CommandOptionStore._initialized = False
        CommandOptionStore._default_path = None
        CommandOptionStore.configure(tmp_path / "command_options.json")

        class _Cmd:
            meta = CommandMeta(id="__test__cmd", display="test", params=[CommandParam(name="n", value=99)])

        d = CommandOptionsDialog(_Cmd)
        qtbot.addWidget(d)
        w = d.widgets["n"]
        assert w.maximum() == 99999
    finally:
        CommandOptionStore._instance = prev_instance
        CommandOptionStore._initialized = prev_initialized
        CommandOptionStore._default_path = prev_default_path


def test_float_default_99_allows_100(qtbot, tmp_path):
    from wayfer.core.actions.command.core import CommandMeta, CommandParam
    from wayfer.core.actions.command.state import CommandOptionStore
    from wayfer.core.actions.command.option_dialog import CommandOptionsDialog

    prev_instance = getattr(CommandOptionStore, "_instance", None)
    prev_initialized = getattr(CommandOptionStore, "_initialized", False)
    prev_default_path = getattr(CommandOptionStore, "_default_path", None)

    try:
        CommandOptionStore._instance = None
        CommandOptionStore._initialized = False
        CommandOptionStore._default_path = None
        CommandOptionStore.configure(tmp_path / "command_options.json")

        class _Cmd:
            meta = CommandMeta(id="__test__cmd2", display="test", params=[CommandParam(name="x", value=99.0)])

        d = CommandOptionsDialog(_Cmd)
        qtbot.addWidget(d)
        w = d.widgets["x"]
        assert w.maximum() == 99999.0
    finally:
        CommandOptionStore._instance = prev_instance
        CommandOptionStore._initialized = prev_initialized
        CommandOptionStore._default_path = prev_default_path

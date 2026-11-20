import pytest
from PySide6 import QtWidgets

from wafer.qt.commands.binding.manager import BindingManager
from wafer.qt.commands.binding.mixins import CommandBindingMixin
from wafer.qt.commands.command.core import CommandMeta, CommandParam, CommandRegistry, register_command_defs
from wafer.qt.commands.command.payload import CommandPayload
from wafer.qt.commands.command.state import CommandOptionStore


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    reg = CommandRegistry.instance()
    prev_commands = dict(reg._commands)
    prev_inst = CommandOptionStore._instance
    prev_path = CommandOptionStore._default_path
    prev_manager = BindingManager._instance
    CommandOptionStore._instance = None
    CommandOptionStore.configure(tmp_path / "opts.json")
    BindingManager._instance = None
    yield
    reg._commands = prev_commands
    CommandOptionStore._instance = prev_inst
    CommandOptionStore._default_path = prev_path
    BindingManager._instance = prev_manager


def _register_two_arg_command(calls):
    def run(a=0, b=0):
        calls.append((a, b))

    register_command_defs([CommandMeta(id="test.mixin_two_args", display="Two", func=run, params=[CommandParam(name="a", value=0), CommandParam(name="b", value=0)])])


def test_binding_args_fill_in_over_saved_options_per_param(qtbot):
    calls = []
    _register_two_arg_command(calls)
    CommandOptionStore.instance().set("test.mixin_two_args", {"a": 1, "b": 2})
    w = _W()
    qtbot.addWidget(w)
    w.init_command_binding("viewer")

    w.exec_command(CommandPayload("test.mixin_two_args", {"a": 9}), source="key")

    assert calls == [(9, 2)]


def test_binding_without_args_uses_saved_options(qtbot):
    calls = []
    _register_two_arg_command(calls)
    CommandOptionStore.instance().set("test.mixin_two_args", {"a": 1, "b": 2})
    w = _W()
    qtbot.addWidget(w)
    w.init_command_binding("viewer")

    w.exec_command(CommandPayload("test.mixin_two_args", {}), source="key")

    assert calls == [(1, 2)]

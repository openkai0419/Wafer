from PySide6 import QtWidgets

from wafer.core.actions.command.core import CommandMeta, CommandParam
from wafer.core.actions.command.state import CommandOptionStore
from wafer.core.actions.command.option_dialog import CommandOptionsDialog


class _Cmd:
    meta = None


def test_int_step_infers_trailing_zeros(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.int_step", display="int", params=[CommandParam(name="x", value=110)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QSpinBox)
    assert sb.singleStep() == 5


def test_int_step_defaults_to_one(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.int_step2", display="int2", params=[CommandParam(name="x", value=105)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QSpinBox)
    assert sb.singleStep() == 1


def test_float_step_infers_decimal_places(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.float_step", display="float", params=[CommandParam(name="x", value=1.01)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QDoubleSpinBox)
    assert sb.decimals() >= 2
    assert abs(sb.singleStep() - 0.005) < 1e-12


def test_float_step_one_decimal(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.float_step2", display="float2", params=[CommandParam(name="x", value=1.1)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QDoubleSpinBox)
    assert sb.decimals() >= 2
    assert abs(sb.singleStep() - 0.05) < 1e-12


def test_float_display_min_two_decimals_keeps_step(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.float_disp2", display="float_disp2", params=[CommandParam(name="x", value=1.0)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QDoubleSpinBox)
    assert sb.decimals() >= 2
    assert abs(sb.singleStep() - 0.5) < 1e-12


def test_float_display_preserves_more_decimals(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.float_disp3", display="float_disp3", params=[CommandParam(name="x", value=0.001)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QDoubleSpinBox)
    assert sb.decimals() >= 3
    assert abs(sb.singleStep() - 0.0005) < 1e-12


def test_float_step_ignores_binary_noise(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.float_noise", display="float_noise", params=[CommandParam(name="x", value=0.1 * 12)])
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w)
    sb = d.widgets["x"]
    assert isinstance(sb, QtWidgets.QDoubleSpinBox)
    assert sb.decimals() == 2
    assert abs(sb.singleStep() - 0.05) < 1e-12


def test_execute_does_not_close_dialog(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.exec_noclose", display="exec", params=[CommandParam(name="x", value=10)])
    called = []
    def callback(values):
        called.append(values)
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w, execute_callback=callback)
    qtbot.addWidget(d)
    d.show()
    d._on_execute()
    assert len(called) == 1
    assert d.isVisible()
    assert not d.did_save()
    d.close()


def test_save_closes_dialog_without_execute(qtbot, tmp_path):
    CommandOptionStore.configure(tmp_path / "opts.json")
    _Cmd.meta = CommandMeta(id="__test__.save_noexec", display="save", params=[CommandParam(name="x", value=10)])
    called = []
    def callback(values):
        called.append(values)
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    d = CommandOptionsDialog(_Cmd, w, execute_callback=callback)
    qtbot.addWidget(d)
    d.show()
    d._on_save()
    assert len(called) == 0
    assert d.did_save()

from extensions.mapping.params import MapParams, param_specs
from extensions.mapping.projection import BlockStats
from extensions.mapping.session import MapDiagnostics
from extensions.mapping.tuning import TuningPanel


def test_form_has_a_control_and_description_per_param(qtbot):
    panel = TuningPanel()
    qtbot.addWidget(panel)
    assert set(panel.controls) == {name for name, _spec, _default in param_specs()}
    for name, spec, _default in param_specs():
        assert panel.controls[name].toolTip() == spec.description


def test_editing_emits_new_params_and_reset(qtbot):
    panel = TuningPanel()
    qtbot.addWidget(panel)
    received = []
    panel.params_changed.connect(received.append)
    panel.controls["min_dist"].setValue(0.5)
    assert received[-1] == MapParams(min_dist=0.5)
    panel.reset_button.click()
    assert received[-1] == MapParams()


def test_set_params_is_silent(qtbot):
    panel = TuningPanel()
    qtbot.addWidget(panel)
    received = []
    panel.params_changed.connect(received.append)
    panel.set_params(MapParams(seed=7))
    assert panel.params().seed == 7 and received == []


def test_diagnostics_text(qtbot):
    panel = TuningPanel()
    qtbot.addWidget(panel)
    diagnostics = MapDiagnostics(timings={"layout": 1.5}, blocks=[BlockStats("tags", 50, 0.8, 2, 0.6)], groups=3)
    panel.set_diagnostics(diagnostics)
    text = panel.diagnostics_label.text()
    assert "layout" in text and "tags" in text and "60%" in text
    panel.set_diagnostics(None)
    assert panel.diagnostics_label.text() == ""


def test_stages_limit_the_form_but_not_the_params(qtbot):
    panel = TuningPanel(stages=("layout",))
    qtbot.addWidget(panel)
    layout_names = {name for name, spec, _default in param_specs() if spec.stage == "layout"}
    assert set(panel.controls) == layout_names
    assert panel.params() == MapParams()
    panel.controls["seed"].setValue(7)
    assert panel.params() == MapParams(seed=7)
    panel.set_params(MapParams(seed=3, label_terms=7))
    assert panel.controls["seed"].value() == 3 and panel.params().label_terms == 7

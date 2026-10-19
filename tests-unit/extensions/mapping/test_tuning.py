from extensions.mapping.params import TrainParams, ViewParams, param_specs
from extensions.mapping.tuning import TuningPanel


def test_form_has_a_control_and_description_per_param(qtbot):
    panel = TuningPanel(TrainParams)
    qtbot.addWidget(panel)
    assert set(panel.controls) == {name for name, _spec, _default in param_specs(TrainParams)}
    for name, spec, _default in param_specs(TrainParams):
        assert panel.controls[name].toolTip() == spec.description


def test_editing_emits_new_params_and_reset(qtbot):
    panel = TuningPanel(TrainParams)
    qtbot.addWidget(panel)
    received = []
    panel.params_changed.connect(received.append)
    panel.controls["min_dist"].setValue(0.5)
    assert received[-1] == TrainParams(min_dist=0.5)
    panel.reset_button.click()
    assert received[-1] == TrainParams()


def test_set_params_is_silent(qtbot):
    panel = TuningPanel(TrainParams)
    qtbot.addWidget(panel)
    received = []
    panel.params_changed.connect(received.append)
    panel.set_params(TrainParams(seed=7))
    assert panel.params().seed == 7 and received == []


def test_view_tuning_has_a_control_for_every_shared_value(qtbot):
    panel = TuningPanel(ViewParams)
    qtbot.addWidget(panel)
    assert set(panel.controls) == {name for name, _spec, _default in param_specs(ViewParams)}
    panel.controls["max_images"].setValue(700)
    assert panel.params() == ViewParams(max_images=700)
    panel.reset_button.click()
    assert panel.params() == ViewParams()

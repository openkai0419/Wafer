from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from extensions.color.commands import apply_color_filter, apply_selected_color
from extensions.color.widget import ColorFilterWidget


def test_apply_color_filter_appends_ratio_tolerance():
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[]), apply_bars=MagicMock())
    apply_color_filter(search, hex_color="#ff0000", tolerance=1.0, mode="append_and", join="AND")
    bars = search.apply_bars.call_args.args[0]
    assert search.apply_bars.call_args.kwargs["mode"] == "append"
    assert "op" not in bars[0]
    assert bars[0]["params"]["mode"] == "OR"
    assert bars[0]["params"]["colors"][0]["tolerance"] == pytest.approx(1.0)


def test_apply_selected_color_noops_without_selection():
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[]))
    apply_selected_color(search, hex_color="#ff0000")


def test_apply_selected_color_updates_selected_widget():
    widget = SimpleNamespace(has_selection=MagicMock(return_value=True), replace_selected_color=MagicMock(return_value=True))
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[widget]))
    apply_selected_color(search, hex_color="#ff0000")
    widget.replace_selected_color.assert_called_once_with("#FF0000")


def test_apply_color_filter_appends_to_last_color_widget(qapp):
    first = ColorFilterWidget()
    last = ColorFilterWidget()
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[first, last]), apply_bars=MagicMock())

    apply_color_filter(search, hex_color="#112233", tolerance=0.25)

    colors = last.read_params()["colors"]
    assert colors[-1]["hex"] == "#112233".upper()
    assert colors[-1]["tolerance"] == pytest.approx(0.25)
    search.apply_bars.assert_not_called()


def test_apply_color_filter_ignores_existing_duplicate_color(qapp):
    color_widget = ColorFilterWidget()
    color_widget.add_color("#112233", 0.25)
    before = color_widget.read_params()["colors"]
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[color_widget]), apply_bars=MagicMock())

    apply_color_filter(search, hex_color="#112233", tolerance=0.5)

    after = color_widget.read_params()["colors"]
    assert after == before
    search.apply_bars.assert_not_called()

import pytest

from extensions.wd14._downloader import DEFAULT_MODEL


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(tmp_path / "viewer_plugins.ini"))
    monkeypatch.setattr("extensions.wd14.panel.list_models", lambda: [DEFAULT_MODEL, "pixai-tagger-v1.0"])


def make_widget(qtbot):
    from extensions.wd14.panel import WD14SettingsWidget

    w = WD14SettingsWidget()
    qtbot.addWidget(w)
    return w


RAW = {
    "rating": {"general": 0.9, "sensitive": 0.1},
    "general": {"1girl": 0.95, "smile": 0.3},
    "character": {"hatsune_miku": 0.9},
    "copyright": {"vocaloid": 0.85},
    "artist": {"someone": 0.5},
    "meta": {"highres": 0.99},
    "model": "pixai-tagger-v1.0",
    "elapsed_ms": 123,
}


class TestModelSelection:
    def test_lists_models_and_selects_saved(self, qtbot):
        w = make_widget(qtbot)
        assert [w._model_combo.itemText(i) for i in range(w._model_combo.count())] == [DEFAULT_MODEL, "pixai-tagger-v1.0"]
        assert w._model_combo.currentText() == DEFAULT_MODEL
        assert w._current_settings()["model"] == DEFAULT_MODEL

    def test_missing_saved_model_stays_selectable(self, qtbot, monkeypatch):
        from extensions.wd14.settings import wd14_config

        wd14_config.save(model="removed-tagger")
        w = make_widget(qtbot)
        assert w._model_combo.currentText() == "removed-tagger"

    def test_changing_model_requests_preview(self, qtbot, monkeypatch):
        w = make_widget(qtbot)
        requests = []
        monkeypatch.setattr(w, "_do_preview_request", lambda path, settings: requests.append(settings["model"]))
        w._dispatcher.post = lambda fn: fn()
        w._current_path = "/a.png"
        w._model_combo.setCurrentText("pixai-tagger-v1.0")
        assert requests == ["pixai-tagger-v1.0"]

    def test_change_during_request_is_sent_after_result(self, qtbot, monkeypatch):
        w = make_widget(qtbot)
        requests = []
        monkeypatch.setattr(w, "_do_preview_request", lambda path, settings: requests.append(settings["model"]))
        w._dispatcher.post = lambda fn: fn()
        w._current_path = "/a.png"
        w._requesting = True
        w._model_combo.setCurrentText("pixai-tagger-v1.0")
        assert requests == []
        w._on_preview_result(RAW)
        assert requests == ["pixai-tagger-v1.0"]


class TestPreviewDisplay:
    def test_shows_all_categories_and_timing(self, qtbot):
        w = make_widget(qtbot)
        w._general_spin.setValue(0.35)
        w._character_spin.setValue(0.8)
        w._on_preview_result(RAW)
        raw = w._raw_label.text()
        for tag in ("hatsune_miku", "vocaloid", "someone", "highres", "1girl"):
            assert tag in raw
        output = w._filtered_label.text()
        assert "vocaloid" in output
        assert "someone" not in output
        assert "smile" not in output
        assert "highres" in output
        assert "pixai-tagger-v1.0" in w._output_group.title()
        assert "123" in w._output_group.title()

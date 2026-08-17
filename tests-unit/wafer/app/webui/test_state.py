from wafer.app.webui import state


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.app.webui.state.resolve_temp_path", lambda name: tmp_path / name)
    state.write_state("http://127.0.0.1:8787")
    assert state.read_url() == "http://127.0.0.1:8787"


def test_read_url_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.app.webui.state.resolve_temp_path", lambda name: tmp_path / name)
    assert state.read_url() == ""


def test_read_url_returns_empty_on_broken_json(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.app.webui.state.resolve_temp_path", lambda name: tmp_path / name)
    (tmp_path / "webui.json").write_text("{broken", encoding="utf-8")
    assert state.read_url() == ""

import pytest

from wafer.app.webui.settings import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOST_ALL,
    HOST_LOCAL,
    WebUISettings,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = str(tmp_path / "webui_settings.ini")
    monkeypatch.setattr("wafer.app.webui.settings._path", lambda: path)
    return WebUISettings()


def test_defaults_without_file(settings):
    assert settings.host() == DEFAULT_HOST
    assert settings.port() == DEFAULT_PORT


def test_set_and_read_bind(settings):
    settings.set_bind(HOST_ALL, 9000)
    assert settings.host() == HOST_ALL
    assert settings.port() == 9000


def test_resolve_bind_prefers_cli(settings):
    settings.set_bind(HOST_ALL, 9000)
    assert settings.resolve_bind(HOST_LOCAL, 8000) == (HOST_LOCAL, 8000)


def test_resolve_bind_falls_back_to_settings(settings):
    settings.set_bind(HOST_ALL, 9000)
    assert settings.resolve_bind(None, None) == (HOST_ALL, 9000)


def test_resolve_bind_falls_back_to_defaults(settings):
    assert settings.resolve_bind(None, None) == (DEFAULT_HOST, DEFAULT_PORT)


def test_invalid_port_falls_back(settings):
    from wafer.app.webui import settings as mod

    with open(mod._path(), "w", encoding="utf-8") as f:
        f.write("[webui]\nport = notanumber\n")
    assert settings.port() == DEFAULT_PORT

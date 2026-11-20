import socket
import sys

import pytest

from wafer.core.common.profile import current_profile

from wafer.app.webui.settings import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOST_ALL,
    HOST_LOCAL,
    WebUISettings,
    classify_allowed_hosts,
    parse_allowed_hosts,
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
    settings.save(HOST_ALL, 9000)
    assert settings.host() == HOST_ALL
    assert settings.port() == 9000


def test_resolve_bind_prefers_cli(settings):
    settings.save(HOST_ALL, 9000)
    assert settings.resolve_bind(HOST_LOCAL, 8000) == (HOST_LOCAL, 8000)


def test_resolve_bind_falls_back_to_settings(settings):
    settings.save(HOST_ALL, 9000)
    assert settings.resolve_bind(None, None) == (HOST_ALL, 9000)


def test_resolve_bind_falls_back_to_defaults(settings):
    assert settings.resolve_bind(None, None) == (DEFAULT_HOST, DEFAULT_PORT)


def test_invalid_port_falls_back(settings):
    from wafer.app.webui import settings as mod

    with open(mod._path(), "w", encoding="utf-8") as f:
        f.write("[webui]\nport = notanumber\n")
    assert settings.port() == DEFAULT_PORT


def test_allowed_hosts_round_trip(settings):
    assert settings.allowed_hosts() == ()
    settings.save(HOST_ALL, 9000, ("nas.example.com", "*.home.example.net"))
    assert settings.allowed_hosts() == ("nas.example.com", "*.home.example.net")
    assert settings.resolve_bind(None, None) == (HOST_ALL, 9000)


def test_parse_allowed_hosts_normalizes_entries():
    text = "NAS.Example.com, *.home.example.net\nhttps://wafer.example.org:8443/path  example.com. nas.example.com"
    assert parse_allowed_hosts(text) == ("nas.example.com", "*.home.example.net", "wafer.example.org", "example.com")


@pytest.mark.parametrize("entry", ["*", "*.com", "bad_host!", "a..b", "-x.example.com"])
def test_parse_allowed_hosts_drops_invalid_or_too_broad_entries(entry):
    assert parse_allowed_hosts(entry) == ()


def test_classify_allowed_hosts_returns_rejected_entries_without_logging(monkeypatch):
    logged = []
    monkeypatch.setattr("wafer.app.webui.settings.AppLogger.warning", lambda message, **kwargs: logged.append(message))
    assert classify_allowed_hosts("nas.example.com bad_host! *.com") == (("nas.example.com",), ("bad_host!", "*.com"))
    assert logged == []


def test_parse_allowed_hosts_logs_each_rejected_entry(monkeypatch):
    logged = []
    monkeypatch.setattr("wafer.app.webui.settings.AppLogger.warning", lambda message, **kwargs: logged.append(message))
    assert parse_allowed_hosts("nas.example.com bad_host!") == ("nas.example.com",)
    assert len(logged) == 1 and "bad_host!" in logged[0]


def test_thumb_cache_defaults_to_512_mib(settings):
    assert settings.thumb_cache_mb() == 512


def test_thumb_cache_is_saved_next_to_the_bind(settings):
    settings.save(HOST_ALL, 9000, thumb_cache_mb=1024)
    settings.save(HOST_ALL, 9001)
    assert settings.thumb_cache_mb() == 1024 and settings.port() == 9001


def test_broken_thumb_cache_falls_back_to_the_default(settings, tmp_path):
    (tmp_path / "webui_settings.ini").write_text("[webui]\nthumb_cache_mb = lots\n", encoding="utf-8")
    assert settings.thumb_cache_mb() == 512


@pytest.fixture
def debug_profile(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--profile", "debug-port"])
    current_profile.cache_clear()
    yield
    current_profile.cache_clear()


def test_resolve_bind_uses_free_port_in_profile(settings, debug_profile):
    settings.save(HOST_ALL, 9000)
    host, port = settings.resolve_bind(None, None)
    assert host == HOST_ALL
    assert port not in (DEFAULT_PORT, 9000)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_resolve_bind_keeps_cli_port_in_profile(settings, debug_profile):
    assert settings.resolve_bind(None, 8123) == (DEFAULT_HOST, 8123)


def test_resolve_bind_keeps_configured_port_without_profile(settings, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    current_profile.cache_clear()
    try:
        settings.save(HOST_ALL, 9000)
        assert settings.resolve_bind(None, None) == (HOST_ALL, 9000)
    finally:
        current_profile.cache_clear()

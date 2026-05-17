import pytest

from wafer.builtins.update_notifier import service


def _release(tag="v0.6.19", *, html_url="https://github.com/openkai0419/Wafer/releases/tag/v0.6.19", assets=None):
    return {
        "tag_name": tag,
        "name": tag,
        "html_url": html_url,
        "published_at": "2026-05-01T00:00:00Z",
        "body": "release body",
        "assets": assets if assets is not None else [
            {"name": "Wafer-v0.6.19.zip", "browser_download_url": "https://github.com/openkai0419/Wafer/releases/download/v0.6.19/Wafer.zip"}
        ],
    }


class _Response:
    def __init__(self, *, json_data=None, text="", error=None):
        self._json = json_data
        self.text = text
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "resolve_cache_path", lambda rel: str(tmp_path / rel))
    return tmp_path


def test_check_for_updates_fetches_release_and_remote_release_notes(cache_dir, monkeypatch):
    responses = [_Response(json_data=_release()), _Response(text="# Release Notes\n\n- new")]
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: responses.pop(0))

    result = service.check_for_updates(current_version="0.6.18")

    assert result.error == ""
    assert result.info.latest_version == "0.6.19"
    assert result.info.is_newer is True
    assert result.info.release_notes.startswith("# Release Notes")
    assert service.latest_release_cache_path().is_file()
    assert service.release_notes_cache_path("v0.6.19").is_file()


def test_check_for_updates_uses_cache_when_release_fetch_fails(cache_dir, monkeypatch):
    service.write_cached_latest_release(_release())
    service.write_cached_release_notes("v0.6.19", "cached release notes")
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    result = service.check_for_updates(current_version="0.6.18")

    assert result.from_cache is True
    assert result.info.from_cache is True
    assert result.info.latest_version == "0.6.19"
    assert result.info.release_notes == "cached release notes"


def test_check_for_updates_reports_error_when_network_and_cache_unavailable(cache_dir, monkeypatch):
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    result = service.check_for_updates(current_version="0.6.18")

    assert result.info is None
    assert "offline" in result.error


def test_build_update_info_blocks_untrusted_urls():
    release = _release(
        html_url="http://example.com/release",
        assets=[{"name": "evil.zip", "browser_download_url": "https://example.com/evil.zip"}],
    )

    info = service.build_update_info(release, "", current_version="0.6.18")

    assert info.release_url == ""
    assert info.download_url == ""


def test_build_update_info_rejects_invalid_version():
    with pytest.raises(ValueError):
        service.build_update_info(_release(tag="not-a-version"), "", current_version="0.6.18")


def test_build_update_info_strips_release_body():
    release = _release()
    release["body"] = " \n release body \n "

    info = service.build_update_info(release, "", current_version="0.6.18")

    assert info.release_notes == "release body"


def test_remote_release_notes_failure_falls_back_to_release_body(cache_dir, tmp_path, monkeypatch):
    responses = [_Response(json_data=_release()), _Response(error=RuntimeError("not found"))]
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(service, "get_app_root_dir", lambda: tmp_path)

    result = service.check_for_updates(current_version="0.6.18")

    assert result.info.release_notes == "release body"


def test_remote_release_notes_failure_falls_back_to_local_release_notes(cache_dir, tmp_path, monkeypatch):
    release = _release()
    release["body"] = " \n "
    (tmp_path / service.RELEASE_NOTES_FILENAME).write_text("# Local Release Notes\n\n- local", encoding="utf-8")
    responses = [_Response(json_data=release), _Response(error=RuntimeError("not found"))]
    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(service, "get_app_root_dir", lambda: tmp_path)

    result = service.check_for_updates(current_version="0.6.18")

    assert result.info.release_notes == "# Local Release Notes\n\n- local"


def test_up_to_date_check_does_not_fetch_remote_release_notes(cache_dir, monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(args[0])
        return _Response(json_data=_release(tag="v0.6.18"))

    monkeypatch.setattr(service.requests, "get", get)

    result = service.check_for_updates(current_version="0.6.18")

    assert result.info.is_newer is False
    assert result.info.release_notes == "release body"
    assert len(calls) == 1


def test_should_notify_update_requires_newer_version():
    info = service.build_update_info(_release(), "", current_version="0.6.18")

    assert service.should_notify_update(info, "") is True


def test_should_notify_update_rejects_up_to_date_version():
    info = service.build_update_info(_release(tag="v0.6.18"), "", current_version="0.6.18")

    assert service.should_notify_update(info, "") is False


def test_should_notify_update_rejects_skipped_version():
    info = service.build_update_info(_release(), "", current_version="0.6.18")

    assert service.should_notify_update(info, "0.6.19") is False


def test_should_notify_update_rejects_missing_info():
    assert service.should_notify_update(None, "") is False

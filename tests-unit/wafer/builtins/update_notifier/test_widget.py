from PySide6 import QtGui, QtWidgets

from wafer.builtins.update_notifier import widget as update_widget
from wafer.builtins.update_notifier.service import UpdateCheckResult, UpdateInfo


class _MarkdownBrowser(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.markdown = ""

    def set_markdown(self, text):
        self.markdown = text


class _Dispatcher:
    def __init__(self, *args, **kwargs):
        pass

    def post(self, fn, priority=5):
        fn()

    def invoke(self, fn):
        fn()


def _translate(text, **kwargs):
    return text.format(**kwargs) if kwargs else text


def _make_widget(monkeypatch, qtbot):
    monkeypatch.setattr(update_widget, "MarkdownBrowser", _MarkdownBrowser)
    monkeypatch.setattr(update_widget, "Dispatcher", _Dispatcher)
    monkeypatch.setattr(update_widget, "t", _translate)
    monkeypatch.setattr(update_widget.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(update_widget.state, "record_latest_result", lambda version: None)
    w = update_widget.UpdateNotifierWidget()
    qtbot.addWidget(w)
    return w


def _info(*, latest="0.6.19", is_newer=True):
    return UpdateInfo(
        current_version="0.6.18",
        latest_version=latest,
        tag_name=f"v{latest}",
        release_url="https://github.com/openkai0419/Wafer/releases/latest",
        download_url="https://github.com/openkai0419/Wafer/releases/latest",
        published_at="2026-05-01T00:00:00Z",
        release_notes="release body",
        is_newer=is_newer,
    )


def test_update_available_state_uses_primary_download_and_header(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)

    w.set_update_info(_info(is_newer=True))

    assert w._title.text() == "New Update Available: v0.6.19"
    assert w._title.isHidden() is False
    assert w._title.property("updateAvailable") == "true"
    assert w._title.font().weight() == int(QtGui.QFont.Weight.ExtraBold)
    assert w._status.property("updateAvailable") == "true"
    assert w._status.text() == ""
    assert w._status.isHidden() is True
    assert w._open_btn.text() == "Go to Download"
    assert w._open_btn.objectName() == "primary_update_btn"
    assert w._open_btn.isEnabled() is True
    assert w._skip_btn.text() == "Skip until next version"
    assert w._skip_btn.isEnabled() is True
    assert w._check_btn.text() == ""
    assert w._browser.markdown == "release body"


def test_update_notes_are_empty_when_release_notes_are_empty(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)
    info = _info(is_newer=True)
    info = UpdateInfo(**{**info.__dict__, "release_notes": ""})

    w.set_update_info(info)

    assert w._browser.markdown == ""


def test_up_to_date_state_keeps_download_secondary_and_clickable(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)

    w.set_update_info(_info(latest="0.6.18", is_newer=False))

    assert w._title.text() == "Up to Date"
    assert w._title.isHidden() is False
    assert w._title.property("updateAvailable") == "false"
    assert w._title.font().weight() == int(QtGui.QFont.Weight.Normal)
    assert w._status.property("updateAvailable") == "false"
    assert w._status.text() == ""
    assert w._status.isHidden() is True
    assert w._open_btn.objectName() == "secondary_update_btn"
    assert w._open_btn.isEnabled() is True
    assert w._skip_btn.isEnabled() is False


def test_cached_result_uses_status_as_supplemental_hint(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)
    info = _info(latest="0.6.18", is_newer=False)
    info = UpdateInfo(**{**info.__dict__, "from_cache": True})

    w.set_update_info(info)

    assert w._title.text() == "Up to Date"
    assert w._status.text() == "cached result"
    assert w._status.isHidden() is False


def test_check_now_hides_title_until_result_is_applied(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)
    w.set_update_info(_info(is_newer=True))
    monkeypatch.setattr(w._dispatcher, "post", lambda fn, priority=5: None)

    w.check_now(explicit=True)

    assert w._title.isHidden() is True
    assert w._status.text() == "Checking for updates..."
    assert w._status.isHidden() is False

    w.apply_check_result(UpdateCheckResult(info=_info(is_newer=True)))

    assert w._title.text() == "New Update Available: v0.6.19"
    assert w._title.isHidden() is False


def test_error_result_keeps_title_hidden_after_reload(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)
    w.set_update_info(_info(is_newer=True))
    monkeypatch.setattr(w._dispatcher, "post", lambda fn, priority=5: None)

    w.check_now(explicit=True)
    w.apply_check_result(UpdateCheckResult(error="network"))

    assert w._title.isHidden() is True
    assert w._status.text() == "Update check failed: network"
    assert w._status.isHidden() is False


def test_show_event_starts_initial_refresh_once(monkeypatch, qtbot):
    calls = []
    w = _make_widget(monkeypatch, qtbot)
    monkeypatch.setattr(w, "check_now", lambda explicit=True: calls.append(explicit))

    w.show()
    qtbot.waitUntil(lambda: calls == [False], timeout=1000)

    w.refresh_if_needed()

    assert calls == [False]

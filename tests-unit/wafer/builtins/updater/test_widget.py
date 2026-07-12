from PySide6 import QtGui, QtWidgets

from wafer.builtins.updater import widget as update_widget
from wafer.builtins.updater.service import UpdateCheckResult, UpdateInfo


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


def _make_widget(monkeypatch, qtbot, *, mode="git", staged_version=""):
    monkeypatch.setattr(update_widget, "MarkdownBrowser", _MarkdownBrowser)
    monkeypatch.setattr(update_widget, "Dispatcher", _Dispatcher)
    monkeypatch.setattr(update_widget, "t", _translate)
    monkeypatch.setattr(update_widget.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(update_widget.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(update_widget.stage, "update_mode", lambda: mode)
    monkeypatch.setattr(update_widget.stage, "staged_version", lambda: staged_version)
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


def test_stylesheet_defines_disabled_colors_with_theme_roles():
    css = update_widget._build_stylesheet()
    assert "QPushButton#primary_update_btn:disabled" in css
    assert 'QPushButton#primary_update_btn[actionState="cancel"]' in css
    assert "QPushButton#secondary_update_btn:disabled" in css


def test_update_available_state_git_mode_disables_download_with_guidance(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)

    w.set_update_info(_info(is_newer=True))

    assert w._title.text() == "New Update Available: v0.6.19"
    assert w._title.isHidden() is False
    assert w._title.property("updateAvailable") == "true"
    assert w._title.font().weight() == int(QtGui.QFont.Weight.ExtraBold)
    assert w._status.property("updateAvailable") == "true"
    assert w._status.text() == ""
    assert w._status.isHidden() is True
    assert w._open_btn.isHidden() is True
    assert w._open_btn.isEnabled() is False
    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Use git pull instead"
    assert w._primary_btn.property("actionState") == "guidance"
    assert w._skip_btn.text() == "Skip until next version"
    assert w._skip_btn.isEnabled() is True
    assert w._check_btn.text() == ""
    assert w._browser.markdown == "release body"


def test_initial_state_git_shows_disabled_pull_button(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)

    assert w._open_btn.isHidden() is True
    assert w._open_btn.isEnabled() is False
    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Use git pull instead"
    assert w._primary_btn.property("actionState") == "guidance"


def test_initial_state_portable_shows_disabled_actions(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")

    assert w._open_btn.isHidden() is True
    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Download Update"
    assert w._primary_btn.property("actionState") == "disabled"


def test_update_available_state_portable_enables_download(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")

    w.set_update_info(_info(is_newer=True))

    assert w._open_btn.isHidden() is True
    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is True
    assert w._primary_btn.text() == "Download Update"
    assert w._primary_btn.property("actionState") == "download"


def test_update_available_without_in_app_support_shows_download_page(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")

    info = UpdateInfo(**{**_info(is_newer=True).__dict__, "supports_in_app_update": False})
    w.set_update_info(info)

    assert w._primary_btn.isHidden() is True
    assert w._open_btn.isHidden() is False
    assert w._open_btn.isEnabled() is True


def test_update_ready_state_portable_enables_restart(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable", staged_version="0.6.19")

    w.set_update_info(_info(is_newer=True))

    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is True
    assert w._primary_btn.text() == "Restart to Update"
    assert w._primary_btn.property("actionState") == "restart"


def test_portable_download_enters_cancel_state_until_background_task_finishes(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")
    w.set_update_info(_info(is_newer=True))
    monkeypatch.setattr(w._dispatcher, "post", lambda fn, priority=5: None)

    w._on_primary_action_clicked()

    assert w._stage_in_progress is True
    assert w._check_btn.isEnabled() is False
    assert w._progress.isHidden() is False
    assert w._status.text() == "Downloading update..."
    assert w._primary_btn.isEnabled() is True
    assert w._primary_btn.text() == "Cancel Download"
    assert w._primary_btn.property("actionState") == "cancel"


def test_portable_cancel_request_enters_cancelling_state(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")
    w.set_update_info(_info(is_newer=True))
    monkeypatch.setattr(w._dispatcher, "post", lambda fn, priority=5: None)

    w._on_primary_action_clicked()
    w._on_primary_action_clicked()

    assert w._cancel_requested is True
    assert w._status.text() == "Cancelling download..."
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Cancelling..."
    assert w._primary_btn.property("actionState") == "cancelling"


def test_portable_restart_state_click_dispatches_restart(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable", staged_version="0.6.19")
    w.set_update_info(_info(is_newer=True))
    calls = []
    monkeypatch.setattr(w, "_restart_to_apply", lambda: calls.append(True))

    w._on_primary_action_clicked()

    assert calls == [True]


def test_update_notes_are_empty_when_release_notes_are_empty(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)
    info = _info(is_newer=True)
    info = UpdateInfo(**{**info.__dict__, "release_notes": ""})

    w.set_update_info(info)

    assert w._browser.markdown == ""


def test_up_to_date_state_git_keeps_pull_button_disabled(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot)

    w.set_update_info(_info(latest="0.6.18", is_newer=False))

    assert w._title.text() == "Up to Date"
    assert w._title.isHidden() is False
    assert w._title.property("updateAvailable") == "false"
    assert w._title.font().weight() == int(QtGui.QFont.Weight.Normal)
    assert w._status.property("updateAvailable") == "false"
    assert w._status.text() == ""
    assert w._status.isHidden() is True
    assert w._open_btn.isHidden() is True
    assert w._open_btn.isEnabled() is False
    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Use git pull instead"
    assert w._primary_btn.property("actionState") == "guidance"
    assert w._skip_btn.isEnabled() is False


def test_up_to_date_state_portable_keeps_actions_disabled(monkeypatch, qtbot):
    w = _make_widget(monkeypatch, qtbot, mode="portable")

    w.set_update_info(_info(latest="0.6.18", is_newer=False))

    assert w._primary_btn.isHidden() is False
    assert w._primary_btn.isEnabled() is False
    assert w._primary_btn.text() == "Download Update"
    assert w._primary_btn.property("actionState") == "disabled"


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

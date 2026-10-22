from unittest.mock import Mock, patch


def test_wait_for_install_complete_pumps_qt_events_while_waiting():
    from wafer.qt.install import waiter

    app = Mock()

    def fake_wait_for_install(*, restart_idle_tray, wait_for_tray, on_idle):
        on_idle()

    with patch.object(waiter, "wait_for_install", side_effect=fake_wait_for_install):
        waiter.wait_for_install_complete(app=app)

    app.processEvents.assert_called_once()


def test_wait_for_install_complete_asks_before_restarting_an_idle_tray():
    from wafer.qt.install import waiter

    captured = {}

    def fake_wait_for_install(*, restart_idle_tray, wait_for_tray, on_idle):
        captured["answer"] = restart_idle_tray()

    with (
        patch.object(waiter, "wait_for_install", side_effect=fake_wait_for_install),
        patch.object(waiter, "_ask_restart_tray", return_value=False) as ask,
    ):
        waiter.wait_for_install_complete(app=Mock())

    ask.assert_called_once()
    assert captured["answer"] is False

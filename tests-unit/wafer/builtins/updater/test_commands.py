from unittest.mock import patch

from wafer.builtins.updater import commands as update_commands


def _check_command():
    return next(c for c in update_commands.UpdateCommands.commands() if getattr(c, "path", None) == "update.check")


def test_check_for_updates_is_shown_without_a_profile():
    with patch.object(update_commands, "current_profile", return_value=None):
        assert _check_command().hidden is False


def test_check_for_updates_is_hidden_in_a_profile():
    with patch.object(update_commands, "current_profile", return_value="debug-x"):
        assert _check_command().hidden is True


def test_check_for_updates_does_nothing_in_a_profile():
    with patch.object(update_commands, "current_profile", return_value="debug-x"), patch("wafer.builtins.updater.startup.present_updater") as present:
        update_commands.check_for_updates(None)
    present.assert_not_called()


def test_check_for_updates_checks_without_a_profile():
    with patch.object(update_commands, "current_profile", return_value=None), patch("wafer.builtins.updater.startup.present_updater") as present:
        update_commands.check_for_updates(None)
    present.return_value.check_now.assert_called_once_with(explicit=True)

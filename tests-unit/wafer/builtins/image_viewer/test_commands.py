from unittest.mock import MagicMock, patch

from wafer.builtins.image_viewer.commands import ImageViewCommands, set_image_spread
from wafer.builtins.image_viewer.viewer import ImageViewer


def test_set_image_spread_calls_image_viewer():
    image_viewer = MagicMock()

    with patch("wafer.builtins.image_viewer.commands.viewer_resolver") as mock_resolver:
        mock_resolver.registry.instance.return_value = image_viewer
        set_image_spread(MagicMock(), pages=4, direction="top-to-bottom")

    mock_resolver.registry.instance.assert_called_once_with(ImageViewer.NAME)
    image_viewer.set_image_spread.assert_called_once_with(pages=4, direction="top-to-bottom", match_size=True)


def test_set_image_spread_forwards_match_size():
    image_viewer = MagicMock()

    with patch("wafer.builtins.image_viewer.commands.viewer_resolver") as mock_resolver:
        mock_resolver.registry.instance.return_value = image_viewer
        set_image_spread(MagicMock(), pages=2, direction="left-to-right", match_size=False)

    image_viewer.set_image_spread.assert_called_once_with(pages=2, direction="left-to-right", match_size=False)


def test_image_spread_command_is_not_checkable():
    command = next(c for c in ImageViewCommands.commands() if getattr(c, "path", "") == "imgv.image_spread")

    assert command.checkable is False
    assert command.checked_resolver is None

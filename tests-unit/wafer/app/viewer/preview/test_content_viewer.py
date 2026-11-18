from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
from wafer.qt.common.dpi import dpix


def test_the_content_viewer_can_be_made_small(qtbot):
    widget = ContentViewerWidget()
    qtbot.addWidget(widget)

    hint = widget.minimumSizeHint()

    assert hint.width() < dpix(200)
    assert hint.height() < dpix(200)

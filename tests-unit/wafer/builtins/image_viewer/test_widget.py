import py_compile

from PySide6 import QtGui

from wafer.builtins.image_viewer.widget import ImageDisplayWidget
from wafer.plugin import ViewerContext


def test_compile():
    py_compile.compile("wafer/builtins/image_viewer/widget.py")


def test_set_images_uses_multiple_scene_items(qtbot):
    widget = ImageDisplayWidget()
    qtbot.addWidget(widget)
    first = QtGui.QImage(10, 20, QtGui.QImage.Format_ARGB32)
    second = QtGui.QImage(30, 40, QtGui.QImage.Format_ARGB32)
    first.fill(QtGui.QColor("red"))
    second.fill(QtGui.QColor("blue"))

    widget.set_images([first, second], direction="left-to-right")

    assert len(widget.view._pix_items) == 2
    assert widget.view._image_rect().width() == 40
    assert widget.view._image_rect().height() == 40


def test_extend_context_uses_active_batch_paths(qtbot):
    from wafer.utils.virtual_paths import register_owner_extension

    register_owner_extension(".zip")
    widget = ImageDisplayWidget()
    qtbot.addWidget(widget)
    view = widget.view
    viewer = type(
        "ViewerStub",
        (),
        {
            "current_viewer_contexts": lambda self: (
                ViewerContext(path="archive.zip::a.png", source="archive.zip", render_path="cache/a.png"),
                ViewerContext(path="archive.zip::b.png", source="archive.zip", render_path="cache/b.png"),
            ),
        },
    )()
    ctx = type("Ctx", (), {"get_instance": lambda self, name: viewer if name == "FileViewerController" else None})()

    result = view.extend_context(ctx, None)

    assert result["path"] == "archive.zip::a.png"
    assert result["paths"] == ["archive.zip::a.png", "archive.zip::b.png"]
    assert result["source"] == "archive.zip"
    assert result["sources"] == ["archive.zip"]
    assert result["render_path"] == "cache/a.png"
    assert result["render_paths"] == ["cache/a.png", "cache/b.png"]

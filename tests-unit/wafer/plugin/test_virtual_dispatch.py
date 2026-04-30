from wafer.plugin.registry import DISPATCH_LEAF, DISPATCH_OWNER, FilePluginRegistry
from wafer.plugin.grid.base import BaseGridPlugin
from wafer.utils.virtual_paths import build_virtual_path


class _ZipOwner(BaseGridPlugin):
    NAME = "zip_owner_test"
    EXTENSIONS = (".zip",)
    PRIORITY = 10


class _PngLeaf(BaseGridPlugin):
    NAME = "png_leaf_test"
    EXTENSIONS = (".png",)
    PRIORITY = 10


def test_file_registry_owner_and_leaf_dispatch():
    reg = FilePluginRegistry()
    reg.register(_ZipOwner)
    reg.register(_PngLeaf)
    path = build_virtual_path("C:/data/archive.zip", "folder/image.png")
    assert reg.resolve(path, DISPATCH_OWNER) is _ZipOwner
    assert reg.resolve(path, DISPATCH_LEAF) is _PngLeaf

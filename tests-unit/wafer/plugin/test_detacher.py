import py_compile

from wafer.plugin.detacher.base import (
    BaseDetacher,
    BaseDetacherPlugin,
    BaseSingletonDetacher,
    DetacherResult,
)


def test_compile_base():
    py_compile.compile("wafer/plugin/detacher/base.py")


def test_base_detacher_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseDetacher()


def test_base_detacher_plugin_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseDetacherPlugin()


def test_base_singleton_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseSingletonDetacher()


def test_hierarchy():
    assert issubclass(BaseDetacherPlugin, BaseDetacher)
    assert issubclass(BaseSingletonDetacher, BaseDetacher)
    assert not issubclass(BaseDetacherPlugin, BaseSingletonDetacher)


def test_batch_size_defaults():
    assert BaseDetacherPlugin.BATCH_SIZE == 1200
    assert BaseSingletonDetacher.BATCH_SIZE == 300


def test_trigger_keys_default():
    assert BaseDetacher.TRIGGER_KEYS == ()


def test_detacher_result_to_dict():
    r = DetacherResult(source="img.png", status=True, meta_info={"k": "v"})
    d = r.to_dict()
    assert d == {"source": "img.png", "status": True, "meta_info": {"k": "v"}}
    assert "tags" not in d
    assert "delete_keys" not in d


def test_on_notify_default_is_noop():
    class MyDetacher(BaseDetacherPlugin):
        NAME = "test_noop"
        TRIGGER_KEYS = ("some.key",)

        def process(self, path, file_info, metadata):
            return DetacherResult(source=path, status=True)

    inst = MyDetacher()
    inst.on_notify()


def test_on_notify_override():
    class MyDetacher(BaseDetacherPlugin):
        NAME = "test_override"
        TRIGGER_KEYS = ("some.key",)
        reloaded = False

        def process(self, path, file_info, metadata):
            return DetacherResult(source=path, status=True)

        def on_notify(self):
            self.reloaded = True

    inst = MyDetacher()
    assert not inst.reloaded
    inst.on_notify()
    assert inst.reloaded


def test_notify_to_sends_ipc():
    from unittest.mock import MagicMock, patch

    mock_node = MagicMock()
    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = mock_node

    with patch("wafer.core.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseDetacherPlugin.notify_to("novelai")

    mock_node.send.assert_called_once_with("plugin.notify", dst="detacher-novelai")


def test_notify_to_no_node():
    from unittest.mock import MagicMock, patch

    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = None

    with patch("wafer.core.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseDetacherPlugin.notify_to("novelai")

import py_compile

from wafer.plugin.parser.base import (
    BaseParser,
    BaseParserPlugin,
    BaseSingletonParser,
    ParserResult,
)


def test_compile_base():
    py_compile.compile("wafer/plugin/parser/base.py")


def test_base_parser_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseParser()


def test_base_parser_plugin_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseParserPlugin()


def test_base_singleton_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseSingletonParser()


def test_hierarchy():
    assert issubclass(BaseParserPlugin, BaseParser)
    assert issubclass(BaseSingletonParser, BaseParser)
    assert not issubclass(BaseParserPlugin, BaseSingletonParser)


def test_batch_size_defaults():
    assert BaseParserPlugin.BATCH_SIZE == 1200
    assert BaseSingletonParser.BATCH_SIZE == 300


def test_trigger_keys_default():
    assert BaseParser.TRIGGER_KEYS == ()


def test_parser_result_to_dict():
    r = ParserResult(source="img.png", status=True, meta_info={"k": "v"})
    d = r.to_dict()
    assert d == {"source": "img.png", "status": True, "meta_info": {"k": "v"}}
    assert "tags" not in d
    assert "delete_keys" not in d


def test_on_notify_default_is_noop():
    class MyParser(BaseParserPlugin):
        NAME = "test_noop"
        TRIGGER_KEYS = ("some.key",)

        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=True)

    inst = MyParser()
    inst.on_notify()


def test_on_notify_override():
    class MyParser(BaseParserPlugin):
        NAME = "test_override"
        TRIGGER_KEYS = ("some.key",)
        reloaded = False

        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=True)

        def on_notify(self, payload=None):
            self.reloaded = True

    inst = MyParser()
    assert not inst.reloaded
    inst.on_notify()
    assert inst.reloaded


def test_notify_to_sends_ipc():
    from unittest.mock import MagicMock, patch

    mock_node = MagicMock()
    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = mock_node

    with patch("wafer.core.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseParserPlugin.notify_to("novelai")

    mock_node.send.assert_called_once_with("plugin.notify", None, dst="parser-novelai")


def test_notify_to_no_node():
    from unittest.mock import MagicMock, patch

    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = None

    with patch("wafer.core.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseParserPlugin.notify_to("novelai")

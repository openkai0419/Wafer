import pytest
from wafer.plugin.parser.base import BaseParserPlugin, BaseSingletonParser, ParserResult
from wafer.plugin.parser.handler import ParserResolver


class FakeParserA(BaseParserPlugin):
    NAME = "fake_a"
    TRIGGER_KEYS = ("exif.parameters", "exif.Comment")
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


class FakeParserB(BaseSingletonParser):
    NAME = "fake_b"
    TRIGGER_KEYS = ("sd.prompt",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


class FakeParserC(BaseParserPlugin):
    NAME = "fake_c"
    TRIGGER_KEYS = ("other.key",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


@pytest.fixture
def resolver():
    r = ParserResolver()
    r.registry.register(FakeParserA)
    r.registry.register(FakeParserB)
    r.registry.register(FakeParserC)
    return r


def test_names(resolver):
    names = resolver.names()
    assert "fake_a" in names
    assert "fake_b" in names
    assert "fake_c" in names


def test_singleton_names(resolver):
    assert resolver.singleton_names() == ["fake_b"]


def test_per_indexer_names(resolver):
    pi = resolver.per_indexer_names()
    assert "fake_a" in pi
    assert "fake_c" in pi
    assert "fake_b" not in pi


def test_batch_size(resolver):
    assert resolver.batch_size("fake_a") == 1200
    assert resolver.batch_size("fake_b") == 300
    assert resolver.batch_size("nonexistent") == 1200


def test_trigger_keys(resolver):
    assert resolver.trigger_keys("fake_a") == ("exif.parameters", "exif.Comment")
    assert resolver.trigger_keys("fake_b") == ("sd.prompt",)


def test_parsers_for_keys_single(resolver):
    matched = resolver.parsers_for_keys({"exif.parameters"})
    assert "fake_a" in matched
    assert "fake_b" not in matched


def test_parsers_for_keys_multiple(resolver):
    matched = resolver.parsers_for_keys({"exif.parameters", "sd.prompt"})
    assert "fake_a" in matched
    assert "fake_b" in matched
    assert "fake_c" not in matched


def test_parsers_for_keys_no_match(resolver):
    matched = resolver.parsers_for_keys({"unknown.key"})
    assert matched == []


def test_parsers_for_keys_empty(resolver):
    matched = resolver.parsers_for_keys(set())
    assert matched == []


def test_status_name(resolver):
    assert resolver.status_name("fake_a") == "fake_a"
    assert resolver.status_name("fake_b") == "fake_b"

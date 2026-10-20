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


def test_resolver_required_collectors_unknown_is_empty():
    from wafer.plugin.parser.handler import parser_resolver

    assert parser_resolver.required_collectors("does_not_exist") == {}


class StaticParser(BaseParserPlugin):
    NAME = "static_keys"
    TRIGGER_KEYS = ("a.x",)

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


class PerDbParser(BaseParserPlugin):
    NAME = "per_db_keys"
    TRIGGER_KEYS = ("file_hash",)
    calls: list[str] = []

    @classmethod
    def trigger_keys(cls, db_name):
        cls.calls.append(db_name)
        return ("file_hash", f"{db_name}.k")

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


class BrokenParser(BaseParserPlugin):
    NAME = "broken_keys"
    TRIGGER_KEYS = ("b.y",)

    @classmethod
    def trigger_keys(cls, db_name):
        raise RuntimeError("boom")

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


def make_resolver(*classes):
    resolver = ParserResolver()
    for cls in classes:
        resolver.registry.register(cls)
    return resolver


def test_default_trigger_keys_come_from_class_attribute():
    resolver = make_resolver(StaticParser)
    resolver.bind_db("db1")
    assert resolver.trigger_keys("static_keys") == ("a.x",)


def test_per_db_trigger_keys_are_bound_and_cached():
    PerDbParser.calls.clear()
    resolver = make_resolver(PerDbParser)
    resolver.bind_db("db1")
    assert resolver.trigger_keys("per_db_keys") == ("file_hash", "db1.k")
    assert resolver.trigger_keys("per_db_keys") == ("file_hash", "db1.k")
    assert PerDbParser.calls == ["db1"]
    resolver.refresh_trigger_keys()
    resolver.trigger_keys("per_db_keys")
    assert PerDbParser.calls == ["db1", "db1"]
    assert resolver.parsers_for_keys({"db1.k"}) == ["per_db_keys"]


def test_failing_trigger_keys_fall_back_to_class_attribute():
    resolver = make_resolver(BrokenParser)
    resolver.bind_db("db1")
    assert resolver.trigger_keys("broken_keys") == ("b.y",)


def test_unknown_parser_has_no_trigger_keys():
    assert make_resolver().trigger_keys("missing") == ()

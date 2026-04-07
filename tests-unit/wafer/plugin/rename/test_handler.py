import pytest

from wafer.plugin.rename.base import BaseRenameSourcePlugin
from wafer.plugin.rename.handler import RenameSourceRegistry


class _SrcA(BaseRenameSourcePlugin):
    NAME = "src_a"
    DISPLAY = "Source A"
    PRIORITY = 50

    def evaluate(self, segment):
        return "a"


class _SrcB(BaseRenameSourcePlugin):
    NAME = "src_b"
    DISPLAY = "Source B"
    PRIORITY = 100

    def evaluate(self, segment):
        return "b"


@pytest.fixture
def registry():
    r = RenameSourceRegistry()
    r.register(_SrcA)
    r.register(_SrcB)
    return r


class TestRenameSourceRegistry:
    def test_register_and_get(self, registry):
        assert registry.get("src_a") is _SrcA
        assert registry.get("src_b") is _SrcB

    def test_get_unknown(self, registry):
        assert registry.get("unknown") is None

    def test_list_all_sorted_by_priority_desc(self, registry):
        all_ = registry.list_all()
        assert all_[0] is _SrcB
        assert all_[1] is _SrcA

    def test_deserialise(self, registry):
        inst = registry.deserialise({"type": "src_a"})
        assert isinstance(inst, _SrcA)

    def test_deserialise_unknown_falls_back(self, registry):
        registry.register(type("Fallback", (_SrcA,), {"NAME": "name"}))
        inst = registry.deserialise({"type": "nonexistent"})
        assert inst.NAME == "name"

    def test_deserialise_no_plugins_raises(self):
        r = RenameSourceRegistry()
        with pytest.raises(ValueError):
            r.deserialise({})

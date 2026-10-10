import pytest

from wafer.plugin.rename.base import BaseRenameSourcePlugin


class TestBaseRenameSourcePlugin:
    def test_abstract(self):
        with pytest.raises(TypeError):
            BaseRenameSourcePlugin()

    def test_serialise_default(self):
        class Src(BaseRenameSourcePlugin):
            NAME = "src"

            def evaluate(self, segment):
                return ""

        assert Src().serialise() == {"type": "src"}

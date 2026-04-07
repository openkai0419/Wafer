import pytest
from wafer.plugin.registry import PluginBase, CommandGroupRegistry


class _FakeGroup(PluginBase):
    NAME = "FakeA"
    PRIORITY = 10
    SCOPE = "viewer"
    _registered = False

    @classmethod
    def register(cls):
        cls._registered = True


class _FakeGroupB(PluginBase):
    NAME = "FakeB"
    PRIORITY = 20
    SCOPE = "tray"
    _registered = False

    @classmethod
    def register(cls):
        cls._registered = True


class _FakeGroupStar(PluginBase):
    NAME = "FakeStar"
    PRIORITY = 5
    SCOPE = "*"
    _registered = False

    @classmethod
    def register(cls):
        cls._registered = True


class _SharedName1(PluginBase):
    NAME = "Shared"
    PRIORITY = 10
    SCOPE = "viewer"
    _registered = False

    @classmethod
    def register(cls):
        cls._registered = True


class _SharedName2(PluginBase):
    NAME = "Shared"
    PRIORITY = 20
    SCOPE = "viewer"
    _registered = False

    @classmethod
    def register(cls):
        cls._registered = True


@pytest.fixture(autouse=True)
def _reset_flags():
    for cls in (_FakeGroup, _FakeGroupB, _FakeGroupStar, _SharedName1, _SharedName2):
        cls._registered = False
    yield


class TestCommandGroupRegistry:
    def test_register_and_list_all(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.register(_FakeGroupB)
        listed = reg.list_all()
        assert len(listed) == 2
        assert listed[0] is _FakeGroupB
        assert listed[1] is _FakeGroup

    def test_duplicate_register_ignored(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.register(_FakeGroup)
        assert len(reg.list_all()) == 1

    def test_activate_filters_by_scope(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.register(_FakeGroupB)
        reg.register(_FakeGroupStar)
        reg.activate("viewer")
        assert _FakeGroup._registered is True
        assert _FakeGroupStar._registered is True
        assert _FakeGroupB._registered is False

    def test_activate_tray_scope(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.register(_FakeGroupB)
        reg.register(_FakeGroupStar)
        reg.activate("tray")
        assert _FakeGroup._registered is False
        assert _FakeGroupB._registered is True
        assert _FakeGroupStar._registered is True

    def test_activate_does_not_double_register(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.activate("viewer")
        assert _FakeGroup._registered is True
        _FakeGroup._registered = False
        reg.activate("viewer")
        assert _FakeGroup._registered is False

    def test_names_dedup(self):
        reg = CommandGroupRegistry()
        reg.register(_SharedName1)
        reg.register(_SharedName2)
        names = reg.names()
        assert names.count("Shared") == 1

    def test_list_all_sorted_by_priority(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroupStar)
        reg.register(_FakeGroupB)
        reg.register(_FakeGroup)
        listed = reg.list_all()
        priorities = [c.PRIORITY for c in listed]
        assert priorities == sorted(priorities, reverse=True)

    def test_set_order_changes_sort(self):
        reg = CommandGroupRegistry()
        reg.register(_FakeGroup)
        reg.register(_FakeGroupB)
        reg.set_order(["FakeA", "FakeB"])
        listed = reg.list_all()
        assert listed[0] is _FakeGroup

    def test_set_order_forwards_to_menu_hub(self):
        from wafer.core.commands.command.menu import MenuHub

        hub = MenuHub.instance()
        saved = list(hub._menu_order)
        try:
            reg = CommandGroupRegistry()
            reg.set_order(["X", "Y"])
            assert hub._menu_order == ["X", "Y"]
        finally:
            hub._menu_order = saved

    def test_activate_ignores_set_order(self):
        order = []

        class _P10(PluginBase):
            NAME = "P10"
            PRIORITY = 10
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                order.append("P10")

        class _P20(PluginBase):
            NAME = "P20"
            PRIORITY = 20
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                order.append("P20")

        reg = CommandGroupRegistry()
        reg.register(_P10)
        reg.register(_P20)
        reg.set_order(["P20", "P10"])
        reg.activate("viewer")
        assert order == ["P10", "P20"]

    def test_activate_error_does_not_block_others(self):
        class _Broken(PluginBase):
            NAME = "Broken"
            PRIORITY = 100
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                raise RuntimeError("boom")

        reg = CommandGroupRegistry()
        reg.register(_Broken)
        reg.register(_FakeGroup)
        reg.activate("viewer")
        assert _FakeGroup._registered is True

    def test_activate_order_is_priority_ascending(self):
        order = []

        class _Low(PluginBase):
            NAME = "Low"
            PRIORITY = 10
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                order.append("Low")

        class _High(PluginBase):
            NAME = "High"
            PRIORITY = 1000
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                order.append("High")

        class _Mid(PluginBase):
            NAME = "Mid"
            PRIORITY = 50
            SCOPE = "viewer"

            @classmethod
            def register(cls):
                order.append("Mid")

        reg = CommandGroupRegistry()
        reg.register(_High)
        reg.register(_Low)
        reg.register(_Mid)
        reg.activate("viewer")
        assert order == ["Low", "Mid", "High"]

from wafer.plugin.registry import PluginRegistry, BasePlugin


class _Dummy(BasePlugin):
    NAME = "dummy_discard"


def test_discard_instance_hands_out_a_fresh_object():
    registry = PluginRegistry()
    registry.register(_Dummy)

    first = registry.instance("dummy_discard")
    assert registry.instance("dummy_discard") is first

    registry.discard_instance("dummy_discard")
    second = registry.instance("dummy_discard")

    assert second is not first
    assert isinstance(second, _Dummy)


def test_discard_instance_is_safe_for_unknown_name():
    PluginRegistry().discard_instance("never_registered")

from wafer.plugin.kinds import (
    PLUGIN_KIND_IMAGE_LOADER,
    PLUGIN_KIND_KEY_VALUE_PANEL,
    PLUGIN_KIND_PARSER,
    PLUGIN_KINDS,
    plugin_kind_label,
)
from wafer.plugin.loader import _get_registry_map


def test_all_loader_registry_keys_have_kind_metadata():
    assert set(_get_registry_map().values()) == set(PLUGIN_KINDS)


def test_short_title_case_labels():
    assert plugin_kind_label(PLUGIN_KIND_IMAGE_LOADER) == "Loader"
    assert plugin_kind_label(PLUGIN_KIND_KEY_VALUE_PANEL) == "Data"
    assert plugin_kind_label(PLUGIN_KIND_PARSER) == "Parser"
    assert plugin_kind_label("unknown_kind") == "Unknown Kind"

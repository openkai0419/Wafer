from wafer.plugin.kinds import (
    ORDERABLE_PLUGIN_KIND_KEYS,
    PLUGIN_KIND_COMMAND,
    PLUGIN_KIND_FILTER,
    PLUGIN_KIND_GRID,
    PLUGIN_KIND_IMAGE_LOADER,
    PLUGIN_KIND_LAYOUT,
    PLUGIN_KIND_META_PANEL,
    PLUGIN_KIND_PARSER,
    PLUGIN_KIND_RENAME_SOURCE,
    PLUGIN_KIND_SORT,
    PLUGIN_KIND_TAG_PANEL,
    PLUGIN_KIND_VIEWER,
    PLUGIN_KINDS,
    plugin_kind_color,
    plugin_kind_label,
)
from wafer.plugin.loader import _get_registry_map


def test_all_loader_registry_keys_have_kind_metadata():
    assert set(_get_registry_map().values()) == set(PLUGIN_KINDS)


def test_short_title_case_labels():
    assert plugin_kind_label(PLUGIN_KIND_IMAGE_LOADER) == "Loader"
    assert plugin_kind_label(PLUGIN_KIND_META_PANEL) == "Meta"
    assert plugin_kind_label(PLUGIN_KIND_TAG_PANEL) == "Tag"
    assert plugin_kind_label(PLUGIN_KIND_PARSER) == "Parser"
    assert plugin_kind_label("unknown_kind") == "Unknown Kind"


def test_orderable_kind_order_is_stable():
    assert ORDERABLE_PLUGIN_KIND_KEYS == (
        PLUGIN_KIND_GRID,
        PLUGIN_KIND_VIEWER,
        PLUGIN_KIND_FILTER,
        PLUGIN_KIND_SORT,
        PLUGIN_KIND_LAYOUT,
        PLUGIN_KIND_RENAME_SOURCE,
        PLUGIN_KIND_COMMAND,
    )

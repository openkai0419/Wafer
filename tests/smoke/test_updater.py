from wafer.builtins.registration import _discover_builtins, _import_builtin_modules
from wafer.builtins.updater.service import build_update_info
from wafer.plugin.loader import _get_registry_map


def test_updater_builtin_is_discoverable():
    registry_map = _get_registry_map()
    found = []
    for module in _import_builtin_modules():
        found.extend(_discover_builtins(module, registry_map))

    panels = {cls.NAME for key, cls in found if key == "panel"}
    commands = {cls.__name__ for key, cls in found if key == "command"}

    assert "updater" in panels
    assert "UpdateCommands" in commands


def test_updater_service_builds_smoke_result_without_network():
    release = {
        "tag_name": "v0.6.19",
        "html_url": "https://github.com/openkai0419/Wafer/releases/tag/v0.6.19",
        "published_at": "2026-05-01T00:00:00Z",
        "body": "body",
        "assets": [],
    }

    info = build_update_info(release, "# Release Notes", current_version="0.6.18")

    assert info.latest_version == "0.6.19"
    assert info.is_newer is True
    assert info.release_notes == "# Release Notes"

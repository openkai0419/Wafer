from __future__ import annotations

from wafer.plugin import PluginConfig

DEFAULT_PALETTE_SLOTS = 6
MIN_PALETTE_SLOTS = 1
MAX_PALETTE_SLOTS = 30
APP_SETTINGS_KEY = "color/palette_slots"

color_config = PluginConfig(
    "color",
    {
        "palette_slots": DEFAULT_PALETTE_SLOTS,
    },
)


def normalize_palette_slots(value) -> int:
    try:
        slots = int(value)
    except (TypeError, ValueError):
        slots = DEFAULT_PALETTE_SLOTS
    return max(MIN_PALETTE_SLOTS, min(MAX_PALETTE_SLOTS, slots))


def plugin_palette_slots(settings: dict | None = None) -> int:
    source = settings if settings is not None else color_config.to_dict()
    return normalize_palette_slots(source.get("palette_slots", DEFAULT_PALETTE_SLOTS))


def palette_slots(settings: dict | None = None) -> int:
    if settings is not None:
        return plugin_palette_slots(settings)
    from ._qt_settings import ColorSettings

    return ColorSettings.instance().palette_slots()


def palette_keys(slots: int | None = None) -> tuple[str, ...]:
    count = palette_slots({"palette_slots": slots}) if slots is not None else palette_slots()
    return tuple(f"palette.{i}" for i in range(1, count + 1))

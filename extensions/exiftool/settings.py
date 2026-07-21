from wafer.plugin import PluginConfig, KeyFilter, MODE_BLACKLIST, MODE_WHITELIST

exiftool_config = PluginConfig("exiftool", {"filter_mode": MODE_BLACKLIST, "filter_keys": [], "migrated": False})


def migrate_legacy_filter() -> None:
    cfg = exiftool_config.load()
    if cfg.get("migrated"):
        return
    mode = cfg.get("filter_mode", MODE_BLACKLIST)
    if mode not in (MODE_BLACKLIST, MODE_WHITELIST):
        mode = MODE_BLACKLIST
    keys = cfg.get("filter_keys") or []
    if (keys or mode != MODE_BLACKLIST) and not KeyFilter.get("exiftool")[1]:
        KeyFilter.set_keys("exiftool", mode, keys)
    exiftool_config.save(migrated=True)

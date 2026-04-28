from wafer.plugin import PluginConfig


MODE_BLACKLIST = "blacklist"
MODE_WHITELIST = "whitelist"

SORT_NAME = 0
SORT_COUNT = 1


exiftool_config = PluginConfig(
    "exiftool",
    {
        "filter_mode": MODE_BLACKLIST,
        "filter_keys": [],
        "sort_mode": SORT_COUNT,
        "sort_ascending": False,
    },
)


def read_filter_config() -> tuple[str, set[str]]:
    cfg = exiftool_config.load()
    mode = cfg.get("filter_mode", MODE_BLACKLIST)
    if mode not in (MODE_BLACKLIST, MODE_WHITELIST):
        mode = MODE_BLACKLIST
    keys = cfg.get("filter_keys") or []
    return mode, set(keys)


def write_filter_config(mode: str, keys) -> None:
    exiftool_config.save_and_notify("exiftool", filter_mode=mode, filter_keys=sorted(keys))


def read_sort_config() -> tuple[int, bool]:
    cfg = exiftool_config.load()
    mode = cfg.get("sort_mode", SORT_COUNT)
    if mode not in (SORT_NAME, SORT_COUNT):
        mode = SORT_COUNT
    return mode, bool(cfg.get("sort_ascending", False))


def write_sort_config(mode: int, ascending: bool) -> None:
    exiftool_config.save(sort_mode=int(mode), sort_ascending=bool(ascending))

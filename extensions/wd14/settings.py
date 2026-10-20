from wafer.plugin import PluginConfig

from ._downloader import DEFAULT_MODEL


def parse_blacklist(raw: str) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


wd14_config = PluginConfig(
    "wd14",
    {
        "model": DEFAULT_MODEL,
        "general_threshold": 0.057,
        "character_threshold": 0.8,
        "enable_rating": True,
        "rating_mode": "top",
        "enable_character": True,
        "enable_tags": True,
        "enable_blacklist": True,
        "tag_blacklist": "",
    },
)

from wafer.plugin import PluginConfig

wd14_config = PluginConfig(
    "wd14",
    {
        "general_threshold": 0.057,
        "character_threshold": 0.8,
        "enable_rating": True,
        "enable_rating_score": True,
        "enable_character": True,
        "enable_tags": True,
    },
)

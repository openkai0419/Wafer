from wafer.plugin import PluginConfig

florence_config = PluginConfig(
    "florence",
    {
        "model_variant": "base",
        "enable_caption": True,
        "enable_detailed": True,
        "enable_more_detailed": True,
        "max_new_tokens": 1024,
        "num_beams": 3,
    },
)

TASK_MAP = {
    "enable_caption": "<CAPTION>",
    "enable_detailed": "<DETAILED_CAPTION>",
    "enable_more_detailed": "<MORE_DETAILED_CAPTION>",
}

TAG_MAP = {
    "<CAPTION>": "caption",
    "<DETAILED_CAPTION>": "detailed",
    "<MORE_DETAILED_CAPTION>": "more_detailed",
}


def enabled_tasks(settings: dict) -> list[str]:
    return [task for key, task in TASK_MAP.items() if settings.get(key, True)]

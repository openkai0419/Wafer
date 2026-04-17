from wafer.plugin import PluginConfig

blip_config = PluginConfig(
    "blip",
    {
        "min_length": 5,
        "max_length": 50,
        "num_beams": 3,
    },
)

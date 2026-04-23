from enum import Enum


class ExtensionBadge(Enum):
    PREFERRED = "preferred"
    HEAVY = "heavy"
    EXTERNAL = "external"


KNOWN_EXTENSIONS: dict[str, ExtensionBadge | None] = {
    "image": ExtensionBadge.PREFERRED,
    "video": ExtensionBadge.PREFERRED,
    "animated": ExtensionBadge.PREFERRED,
    "exiftool": None,
    "ffmpeg": None,
    "text_generation": None,
    "additional_filters": None,
    "additional_layout": None,
    "ai_tagger": ExtensionBadge.HEAVY,
    "florence": ExtensionBadge.HEAVY,
}


def resolve_badge(folder_name: str) -> ExtensionBadge | None:
    if folder_name not in KNOWN_EXTENSIONS:
        return ExtensionBadge.EXTERNAL
    return KNOWN_EXTENSIONS[folder_name]


def badge_sort_key(folder_name: str) -> int:
    badge = resolve_badge(folder_name)
    if badge == ExtensionBadge.PREFERRED:
        return 0
    if badge is None:
        return 1
    if badge == ExtensionBadge.HEAVY:
        return 2
    return 3

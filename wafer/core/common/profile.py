import re
import sys
from functools import lru_cache

PROFILE_ARG = "--profile"
PROFILE_PREFIX = "debug-"
TOOLS_PROFILE = f"{PROFILE_PREFIX}tools"
_PROFILE_PATTERN = re.compile(r"^debug-[A-Za-z0-9_-]+$")


def validate_profile_name(name: str) -> str:
    if not isinstance(name, str) or not _PROFILE_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid profile name {name!r}: must match {_PROFILE_PATTERN.pattern}")
    return name


def profile_from_args(argv: list[str]) -> str | None:
    if PROFILE_ARG not in argv:
        return None
    index = argv.index(PROFILE_ARG)
    value = argv[index + 1] if index + 1 < len(argv) else ""
    return validate_profile_name(value)


@lru_cache(maxsize=1)
def current_profile() -> str | None:
    return profile_from_args(sys.argv)


def profile_label(profile: str | None) -> str:
    return "" if profile is None else f"[{profile}] "


def app_user_model_id(base: str, profile: str | None) -> str:
    return base if profile is None else f"{base}.{profile}"


def profile_args(profile: str | None) -> list[str]:
    return [] if profile is None else [PROFILE_ARG, profile]

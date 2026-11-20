import re
import sys
from functools import lru_cache

PROFILE_ARG = "--profile"
_PROFILE_ASSIGN = f"{PROFILE_ARG}="
PROFILE_PREFIX = "debug-"
TOOLS_PROFILE = f"{PROFILE_PREFIX}tools"
_PROFILE_PATTERN = re.compile(r"^debug-[A-Za-z0-9_-]+$")


def validate_profile_name(name: str) -> str:
    if not isinstance(name, str) or not _PROFILE_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid profile name {name!r}: must match {_PROFILE_PATTERN.pattern}")
    return name


def same_profile(a: str | None, b: str | None) -> bool:
    return (a or "").casefold() == (b or "").casefold()


def split_profile_args(argv: list[str]) -> tuple[str | None, list[str]]:
    args = list(argv)
    values: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == PROFILE_ARG:
            values.append(args[index + 1] if index + 1 < len(args) else "")
            index += 2
            continue
        if arg.startswith(_PROFILE_ASSIGN):
            values.append(arg[len(_PROFILE_ASSIGN):])
        else:
            rest.append(arg)
        index += 1
    if not values:
        return None, rest
    if len(values) > 1:
        raise ValueError(f"{PROFILE_ARG} was given more than once: {values!r}")
    return validate_profile_name(values[0]), rest


def profile_from_args(argv: list[str]) -> str | None:
    return split_profile_args(argv)[0]


@lru_cache(maxsize=1)
def current_profile() -> str | None:
    return profile_from_args(sys.argv)


def profile_label(profile: str | None) -> str:
    return "" if profile is None else f"[{profile}] "


def app_user_model_id(base: str, profile: str | None) -> str:
    return base if profile is None else f"{base}.{profile}"


def profile_args(profile: str | None) -> list[str]:
    return [] if profile is None else [PROFILE_ARG, profile]

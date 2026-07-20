from collections.abc import Iterable

from ...core.lang.manager import t
from ...plugin.badges import ExtensionBadge


PREFERRED_BADGE_TOOLTIP = "Install Recommended for general use"
HEAVY_BADGE_TOOLTIP = "This extension is marked as HEAVY. This may:\n- use large amount of GPU\n- take long time to install"
EXTERNAL_BADGE_TOOLTIP = "Community / third-party extension"

HEAVY_INSTALL_TITLE = "Install HEAVY Extension"
HEAVY_WARNING_TITLE = "HEAVY Extension"
HEAVY_MULTI_WARNING_HEADER = "Multiple HEAVY extensions are enabled:"
HEAVY_MULTI_WARNING_FOOTER = "This may cause high GPU usage or instability."

PARSER_REQUIREMENT_HEADER = "Parser '{parser}' on '{db}' requires a collector:"

BADGE_TOOLTIPS: dict[ExtensionBadge, str] = {
    ExtensionBadge.PREFERRED: PREFERRED_BADGE_TOOLTIP,
    ExtensionBadge.HEAVY: HEAVY_BADGE_TOOLTIP,
    ExtensionBadge.EXTERNAL: EXTERNAL_BADGE_TOOLTIP,
}


def badge_tooltip_text(badge: ExtensionBadge | None) -> str:
    if badge is None:
        return ""
    tooltip = BADGE_TOOLTIPS.get(badge, "")
    return t(tooltip) if tooltip else ""


def heavy_install_title() -> str:
    return t(HEAVY_INSTALL_TITLE)


def heavy_install_confirm_text() -> str:
    return f"{t(HEAVY_BADGE_TOOLTIP)}\n{t('Continue?')}"


def heavy_warning_title() -> str:
    return t(HEAVY_WARNING_TITLE)


def heavy_multi_warning_text(folder_names: Iterable[str | None]) -> str:
    folders = "\n".join(f"- {folder}" for folder in folder_names if folder)
    return f"{t(HEAVY_MULTI_WARNING_HEADER)}\n{folders}\n{t(HEAVY_MULTI_WARNING_FOOTER)}"


def _required_lines(required: dict[str, list[str]]) -> str:
    return "\n".join(f"- {collector} ({', '.join(keys)})" for collector, keys in required.items())


def required_collectors_text(required: dict[str, list[str]]) -> str:
    if not required:
        return ""
    parts = [f"{collector} ({', '.join(keys)})" for collector, keys in required.items()]
    return f"{t('Requires')}: {', '.join(parts)}"


def parser_requirement_title(enabled_available: bool) -> str:
    return t("Enable Required Collector?") if enabled_available else t("Required Collector Unavailable")


def parser_requirement_text(parser_name: str, db_name: str, required: dict[str, list[str]], missing: list[str]) -> str:
    text = f"{t(PARSER_REQUIREMENT_HEADER).format(parser=parser_name, db=db_name)}\n{_required_lines(required)}"
    if missing:
        text += f"\n\n{t('Enable these extensions first:')}\n" + "\n".join(f"- {name}" for name in missing)
    return text


def parser_requirement_question_text(parser_name: str, db_name: str, required: dict[str, list[str]]) -> str:
    return f"{parser_requirement_text(parser_name, db_name, required, [])}\n{t('Do you want to enable the collector?')}"

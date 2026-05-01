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

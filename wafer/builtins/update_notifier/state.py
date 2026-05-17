from __future__ import annotations

from datetime import UTC, datetime

from ...core.app_settings import app_settings


AUTO_CHECK_ENABLED_KEY = "update/auto_check_enabled"
LAST_CHECKED_VERSION_KEY = "update/last_checked_version"
SKIPPED_VERSION_KEY = "update/skipped_version"
LAST_RESULT_VERSION_KEY = "update/last_result_version"
LAST_CHECK_AT_KEY = "update/last_check_at"


def is_auto_check_enabled() -> bool:
    value = app_settings.get(AUTO_CHECK_ENABLED_KEY, True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def set_auto_check_enabled(enabled: bool) -> None:
    app_settings.save_immediate(AUTO_CHECK_ENABLED_KEY, bool(enabled))


def skipped_version() -> str:
    return str(app_settings.get(SKIPPED_VERSION_KEY, "") or "")


def skip_version(version: str) -> None:
    app_settings.save_immediate(SKIPPED_VERSION_KEY, str(version or ""))


def record_latest_result(version: str) -> None:
    now = datetime.now(UTC).isoformat()
    app_settings.set(LAST_CHECKED_VERSION_KEY, str(version or ""))
    app_settings.set(LAST_RESULT_VERSION_KEY, str(version or ""))
    app_settings.set(LAST_CHECK_AT_KEY, now)
    app_settings.commit()

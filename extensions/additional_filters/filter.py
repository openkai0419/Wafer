from __future__ import annotations

import time
from calendar import monthrange
from datetime import datetime, timezone, UTC

from wafer.plugin import BaseFilterPlugin
from wafer.utils.profiling import profiler

_KNOWN_DATE_KEYS = frozenset({"modified", "created", "collected"})
_DATE_HINTS = ("date", "time")
_TODAY = "today"

_UNIT_SECONDS = {
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
}


def is_date_key(key: str) -> bool:
    if key in _KNOWN_DATE_KEYS:
        return True
    lower = key.lower()
    return any(h in lower for h in _DATE_HINTS)


def _resolve_date_value(val: str, end_of_day: bool = False) -> float | None:
    if not val:
        return None
    if val == _TODAY:
        dt = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.timestamp()
    return _date_str_to_epoch(val, end_of_day=end_of_day)


def _preset_to_epoch(value: float, unit: str, ref_time: float | None = None) -> float:
    base = ref_time if ref_time is not None else time.time()
    if unit == "months":
        dt = datetime.fromtimestamp(base, tz=UTC)
        months_back = int(value)
        y = dt.year
        m = dt.month - months_back
        while m <= 0:
            m += 12
            y -= 1
        d = min(dt.day, monthrange(y, m)[1])
        start = datetime(y, m, d, dt.hour, dt.minute, dt.second, tzinfo=UTC)
        return start.timestamp()
    if unit == "years":
        dt = datetime.fromtimestamp(base, tz=UTC)
        y = dt.year - int(value)
        m = dt.month
        d = min(dt.day, monthrange(y, m)[1])
        start = datetime(y, m, d, dt.hour, dt.minute, dt.second, tzinfo=UTC)
        return start.timestamp()
    secs = _UNIT_SECONDS.get(unit, 86400)
    return base - value * secs


def _date_str_to_epoch(date_str: str, end_of_day: bool = False) -> float | None:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%Y/%m/%d")
        dt = dt.replace(tzinfo=UTC)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.timestamp()
    except ValueError:
        return None


def _resolve_preset_ref(ref_str: str) -> float:
    if not ref_str or ref_str == _TODAY:
        return time.time()
    epoch = _date_str_to_epoch(ref_str, end_of_day=True)
    return epoch if epoch is not None else time.time()


class DateRangeFilter(BaseFilterPlugin):
    NAME = "date_range"
    DISPLAY_NAME = "Datetime"
    PRIORITY = 85
    DEFAULT_ENABLED = True

    @classmethod
    def create_widget(cls, parent=None):
        from .widget import DateRangeWidget

        return DateRangeWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

    @classmethod
    def inheritable_params(cls, params):
        return {"target_key": params.get("target_key", "modified")}

    @classmethod
    def bind_key_store(cls, widget, key_store):
        prev = getattr(widget, "_bound_key_store", None)
        if prev is not None:
            prev.updated.disconnect(widget._on_key_store_updated)
        widget._bound_key_store = key_store
        key_store.updated.connect(widget._on_key_store_updated)
        if key_store.data:
            widget._on_key_store_updated(key_store.data)

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        target_key = params.get("target_key", "modified")
        mode = params.get("mode", "preset")

        if mode == "preset":
            value = params.get("preset_value", 7)
            unit = params.get("preset_unit", "days")
            try:
                value = float(value)
            except (ValueError, TypeError):
                return None, []
            if value <= 0:
                return None, []
            ref = _resolve_preset_ref(params.get("preset_ref", _TODAY))
            threshold = _preset_to_epoch(value, unit, ref_time=ref)
            sql = 'SELECT path FROM meta_info WHERE "key" = ? AND value_num BETWEEN ? AND ?'
            return sql, [target_key, threshold, ref]

        if mode == "range":
            range_from = params.get("range_from", "")
            range_to = params.get("range_to", "")
            epoch_from = _resolve_date_value(range_from, end_of_day=True)
            epoch_to = _resolve_date_value(range_to, end_of_day=False)

            if epoch_from is not None and epoch_to is not None:
                lo, hi = min(epoch_from, epoch_to), max(epoch_from, epoch_to)
                sql = 'SELECT path FROM meta_info WHERE "key" = ? AND value_num BETWEEN ? AND ?'
                return sql, [target_key, lo, hi]
            if epoch_from is not None:
                sql = 'SELECT path FROM meta_info WHERE "key" = ? AND value_num <= ?'
                return sql, [target_key, epoch_from]
            if epoch_to is not None:
                sql = 'SELECT path FROM meta_info WHERE "key" = ? AND value_num >= ?'
                return sql, [target_key, epoch_to]

            return None, []

        return None, []

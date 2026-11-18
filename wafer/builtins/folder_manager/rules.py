import operator
from collections.abc import Sequence
from dataclasses import dataclass, field

from wafer.builtins.commands.folder_files import narrows
from wafer.core.logs import AppLogger
from wafer.plugin.query.handler import filter_registry

from .stats import FolderValues

METRICS = ("files", "all_files", "folders", "all_folders")
COUNT_METRICS = ("files", "all_files")
RULE_COLORS = ("#1D9E75", "#D85A30", "#378ADD", "#BA7517", "#7F77DD", "#D4537E")

COMPARATORS = {">=": operator.ge, "<=": operator.le, "==": operator.eq}
OPERATORS = tuple(COMPARATORS)


@dataclass
class Condition:
    metric: str
    op: str
    value: int

    def holds(self, values: FolderValues) -> bool:
        return COMPARATORS[self.op](getattr(values, self.metric), self.value)

    def to_dict(self) -> dict:
        return {"metric": self.metric, "op": self.op, "value": self.value}


@dataclass
class HighlightRule:
    name: str
    color: str
    enabled: bool = True
    bars: list[dict] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)

    def matches(self, values: FolderValues) -> bool:
        return bool(self.conditions) and all(condition.holds(values) for condition in self.conditions)

    def count_metric(self) -> str | None:
        used = {condition.metric for condition in self.conditions}
        return next((metric for metric in reversed(COUNT_METRICS) if metric in used), None)

    def counts_allow(self, files: int, all_files: int) -> bool:
        values = FolderValues(files, all_files, 0, 0)
        return all(condition.holds(values) for condition in self.conditions if condition.metric in COUNT_METRICS)

    def needs_files(self) -> bool:
        return not self.counts_allow(0, 0)

    def filter_entries(self) -> list[tuple]:
        entries = []
        for bar in self.bars:
            name = bar.get("filter")
            if name is None:
                AppLogger.warning(f"[FolderManager] rule '{self.name}': skipped a search bar without a filter")
                continue
            if not bar.get("enabled", True):
                continue
            filter_cls = filter_registry.get(name)
            if filter_cls is None:
                continue
            entries.append((filter_cls, dict(bar.get("params", {})), bar.get("op")))
        return entries

    def query_entries(self) -> list[tuple]:
        entries = self.filter_entries()
        return entries if narrows(entries) else []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "color": self.color,
            "enabled": self.enabled,
            "bars": [{**bar, "params": dict(bar.get("params", {}))} for bar in self.bars],
            "conditions": [condition.to_dict() for condition in self.conditions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HighlightRule":
        name = data["name"]
        color = data["color"]
        if not isinstance(name, str) or not isinstance(color, str):
            raise TypeError(f"rule name and color must be text: {name!r}, {color!r}")
        return cls(
            name=name,
            color=color,
            enabled=bool(data.get("enabled", True)),
            bars=read_bars(name, data.get("bars", [])),
            conditions=read_conditions(name, data.get("conditions", [])),
        )


def read_bars(rule_name: str, items) -> list[dict]:
    if not isinstance(items, list):
        AppLogger.warning(f"[FolderManager] rule '{rule_name}': skipped its query, which is not a list: {items!r}")
        return []
    bars = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("params", {}), dict):
            AppLogger.warning(f"[FolderManager] rule '{rule_name}': skipped search bar {item!r}")
            continue
        bars.append(item)
    return bars


def read_conditions(rule_name: str, items) -> list[Condition]:
    if not isinstance(items, list):
        AppLogger.warning(f"[FolderManager] rule '{rule_name}': skipped its conditions, which are not a list: {items!r}")
        return []
    conditions = []
    for item in items:
        if not isinstance(item, dict):
            AppLogger.warning(f"[FolderManager] rule '{rule_name}': skipped condition {item!r}")
            continue
        if item.get("metric") not in METRICS or item.get("op") not in OPERATORS:
            continue
        try:
            value = int(item["value"])
        except (KeyError, TypeError, ValueError) as exc:
            AppLogger.warning(f"[FolderManager] rule '{rule_name}': skipped condition {item!r}: {exc!r}")
            continue
        conditions.append(Condition(item["metric"], item["op"], value))
    return conditions


def default_rules() -> list[HighlightRule]:
    return [
        HighlightRule(
            "Mixed",
            RULE_COLORS[0],
            conditions=[Condition("files", ">=", 1), Condition("folders", ">=", 1)],
        )
    ]


def new_rule(existing: Sequence[HighlightRule]) -> HighlightRule:
    names = {rule.name for rule in existing}
    number = 1
    while f"Rule {number}" in names:
        number += 1
    used = {rule.color for rule in existing}
    color = next((c for c in RULE_COLORS if c not in used), RULE_COLORS[0])
    return HighlightRule(f"Rule {number}", color, conditions=[Condition("files", ">=", 1)])

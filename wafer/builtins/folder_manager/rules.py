import operator
from collections.abc import Sequence
from dataclasses import dataclass, field

from wafer.plugin.query.handler import filter_registry

from .stats import FolderValues

METRICS = ("files", "all_files", "folders", "all_folders")
COUNT_METRICS = ("files", "all_files")
OPERATORS = (">=", "<=", "==")
RULE_COLORS = ("#1D9E75", "#D85A30", "#378ADD", "#BA7517", "#7F77DD", "#D4537E")

COMPARATORS = {">=": operator.ge, "<=": operator.le, "==": operator.eq}


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

    def shows_count(self) -> bool:
        return any(condition.metric in COUNT_METRICS for condition in self.conditions)

    def filter_entries(self) -> list[tuple]:
        entries = []
        for bar in self.bars:
            if not bar.get("enabled", True):
                continue
            filter_cls = filter_registry.get(bar["filter"])
            if filter_cls is None:
                continue
            entries.append((filter_cls, bar.get("params", {}), bar.get("op")))
        return entries

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "color": self.color,
            "enabled": self.enabled,
            "bars": self.bars,
            "conditions": [condition.to_dict() for condition in self.conditions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HighlightRule":
        conditions = [
            Condition(item["metric"], item["op"], int(item["value"]))
            for item in data.get("conditions", [])
            if item.get("metric") in METRICS and item.get("op") in OPERATORS
        ]
        return cls(
            name=data["name"],
            color=data["color"],
            enabled=data.get("enabled", True),
            bars=list(data.get("bars", [])),
            conditions=conditions,
        )


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

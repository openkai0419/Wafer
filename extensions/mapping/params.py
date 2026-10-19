from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from typing import Any

from wafer.core.logs import AppLogger


@dataclass(frozen=True, slots=True)
class ParamSpec:
    label: str
    description: str
    minimum: float
    maximum: float
    step: float = 1.0


def param(default, *, label: str, description: str, minimum: float, maximum: float, step: float = 1.0):
    return field(default=default, metadata={"spec": ParamSpec(label, description, minimum, maximum, step)})


AUTO_GROUP_MIN = 5
AUTO_GROUP_DIVISOR = 500
AUTO_STRICTNESS_MAX = 10
MIN_GROUP_SIZE = 2
AUTO_NEIGHBORS_MIN = 15
AUTO_NEIGHBORS_SHARE = 0.005
MIN_NEIGHBORS = 2
MAX_NEIGHBORS = 1000
TRAIN_LIMIT = 10000
FLOAT_DIGITS = 6
RESIDUE_DIGITS = 12


class ParamSet:
    def normalized(self):
        changes: dict[str, Any] = {}
        for f in fields(self):
            spec: ParamSpec = f.metadata["spec"]
            current = getattr(self, f.name)
            if not math.isfinite(current):
                changes[f.name] = f.default
                continue
            value = min(max(current, spec.minimum), spec.maximum)
            changes[f.name] = round(value) if isinstance(f.default, int) else float(f"{round(float(value), RESIDUE_DIGITS):.{FLOAT_DIGITS}g}")
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        changes: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            try:
                value = float(data[f.name])
                if not math.isfinite(value):
                    raise ValueError("non-finite value")
                changes[f.name] = type(f.default)(value)
            except (TypeError, ValueError, OverflowError) as e:
                AppLogger.warning(f"[Mapping] Ignored invalid saved value {f.name}={data[f.name]!r}", exc=e)
        return replace(cls(), **changes).normalized()


@dataclass(frozen=True)
class TrainParams(ParamSet):
    neighbors: float = param(
        1.0,
        label="Neighbors",
        description="How many nearby files shape the layout, as a multiple of about 0.5% of the training files (at most 1000). Lower shows small clusters, higher the overall structure.",
        minimum=0.25,
        maximum=4.0,
        step=0.25,
    )
    train_limit: int = param(
        TRAIN_LIMIT,
        label="Training files",
        description="Learn the layout from this many random files and place the rest next to their most similar ones. 0 = learn from every file (slow on large databases).",
        minimum=0,
        maximum=10_000_000,
        step=5000,
    )
    min_dist: float = param(
        0.1,
        label="Spacing",
        description="How tightly points are packed on the map. Lower makes dense clusters, higher spreads points evenly. Groups do not change.",
        minimum=0.0,
        maximum=1.0,
        step=0.05,
    )
    seed: int = param(42, label="Random seed", description="Change to try a different layout.", minimum=0, maximum=9999)

    def resolved_neighbors(self, count: int) -> int:
        return min(MAX_NEIGHBORS, max(MIN_NEIGHBORS, round(max(AUTO_NEIGHBORS_MIN, count * AUTO_NEIGHBORS_SHARE) * self.neighbors)))


@dataclass(frozen=True)
class ViewParams(ParamSet):
    outlier_percent: float = param(
        1.0,
        label="Outliers (%)",
        description="Share of far points marked as outliers and left outside the first view. Higher zooms the first view into the center.",
        minimum=0.0,
        maximum=20.0,
        step=0.5,
    )
    subgroup_size: float = param(
        0.05,
        label="Group size",
        description="Split the base groups from Settings into smaller ones, as a share of their size. 1 = the base groups.",
        minimum=2**-10,
        maximum=1.0,
        step=0.25,
    )
    point_size: float = param(3.0, label="Point size", description="Size of the dots in pixels.", minimum=1.0, maximum=16.0, step=1.0)
    image_spacing: float = param(0.01, label="Image spacing", description="Space between images, relative to their size. Lower lets them overlap more.", minimum=0.01, maximum=2.0, step=0.05)
    max_images: int = param(300, label="Image limit", description="Most images shown at once. Other files stay as dots.", minimum=0, maximum=2000, step=50)
    hover_size: int = param(256, label="Hover size", description="Size of the enlarged image shown under the cursor. 0 turns it off.", minimum=0, maximum=1024, step=32)


@dataclass(frozen=True)
class Grouping(ParamSet):
    size: float = param(
        1.0,
        label="Group size",
        description="Smallest group in the whole space, as a multiple of the automatic size (1 in 500 files, at least 5). Lower makes more, smaller groups.",
        minimum=0.25,
        maximum=16.0,
        step=0.25,
    )
    strictness: float = param(
        1.0,
        label="Strictness",
        description="How crowded files must be to form a group, as a multiple of the automatic value. Lower leaves fewer files without a group.",
        minimum=0.25,
        maximum=16.0,
        step=0.25,
    )
    fine: int = param(0, label="Fine groups", description="Split large groups into the smaller crowds inside them.", minimum=0, maximum=1)

    def cluster_options(self, count: int, share: float = 1.0) -> tuple[int, int, str]:
        automatic = max(AUTO_GROUP_MIN, count // AUTO_GROUP_DIVISOR)
        size = max(MIN_GROUP_SIZE, round(max(MIN_GROUP_SIZE, round(automatic * self.size)) * share))
        samples = max(1, round(min(size, AUTO_STRICTNESS_MAX) * self.strictness))
        return size, samples, "leaf" if self.fine else "eom"


def param_specs(cls: type[ParamSet]) -> list[tuple[str, ParamSpec, int | float]]:
    return [(f.name, f.metadata["spec"], f.default) for f in fields(cls)]

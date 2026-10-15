from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from typing import Any

from wafer.core.logs import AppLogger

STAGES = ("encode", "reduce", "layout", "cluster", "view")


@dataclass(frozen=True, slots=True)
class ParamSpec:
    stage: str
    label: str
    description: str
    minimum: float
    maximum: float
    step: float = 1.0


def param(default, *, stage: str, label: str, description: str, minimum: float, maximum: float, step: float = 1.0):
    return field(default=default, metadata={"spec": ParamSpec(stage, label, description, minimum, maximum, step)})


@dataclass(frozen=True)
class MapParams:
    ngram_min: int = param(
        2, stage="encode", label="Text: min characters", description="Compare text in chunks of at least this many characters. Lower tolerates spelling variations.", minimum=1, maximum=6
    )
    ngram_max: int = param(
        4, stage="encode", label="Text: max characters", description="Compare text in chunks of at most this many characters. Higher is more sensitive to word differences.", minimum=1, maximum=8
    )
    svd_dims: int = param(
        50, stage="reduce", label="Text summary size", description="How many dimensions text is summarized into. Higher keeps finer differences but is slower.", minimum=2, maximum=300
    )
    n_neighbors: int = param(
        15, stage="layout", label="Neighbors", description="How many nearby files shape the layout. Lower shows small clusters, higher the overall structure.", minimum=2, maximum=200
    )
    min_dist: float = param(
        0.1, stage="layout", label="Spacing", description="How tightly points are packed. Lower makes dense clusters, higher spreads points evenly.", minimum=0.0, maximum=1.0, step=0.05
    )
    cluster_dims: int = param(10, stage="layout", label="Grouping dimensions", description="Dimensions used for grouping. Usually no need to change.", minimum=2, maximum=50)
    seed: int = param(42, stage="layout", label="Random seed", description="Change to try a different layout.", minimum=0, maximum=9999)
    min_cluster_size: int = param(
        0, stage="cluster", label="Min group size", description="Smallest number of files in a group. Higher gives fewer, larger groups. 0 = automatic.", minimum=0, maximum=1000
    )
    min_samples: int = param(0, stage="cluster", label="Noise strictness", description="Higher marks more files as noise (gray). 0 = same as min group size.", minimum=0, maximum=1000)
    clip_percent: float = param(
        1.0, stage="view", label="Outlier clip (%)", description="Share of points pushed to the edge as outliers. Higher spreads the center.", minimum=0.0, maximum=20.0, step=0.5
    )
    thumbnail_zoom: float = param(2.0, stage="view", label="Thumbnail zoom", description="Zoom level at which points turn into thumbnails.", minimum=1.0, maximum=20.0, step=0.5)
    image_spacing: float = param(0.01, stage="view", label="Image spacing", description="Space between images, relative to their size. Lower lets them overlap more.", minimum=0.01, maximum=2.0, step=0.05)
    max_images: int = param(300, stage="view", label="Image limit", description="Most images shown at once. Other files stay as dots.", minimum=0, maximum=2000, step=50)
    label_terms: int = param(3, stage="view", label="Label words", description="Number of words in each group label.", minimum=1, maximum=10)
    hover_size: int = param(256, stage="view", label="Hover size", description="Size of the enlarged image shown under the cursor. 0 turns it off.", minimum=0, maximum=1024, step=32)

    def values_for(self, stage: str) -> tuple:
        return tuple(getattr(self, f.name) for f in fields(self) if f.metadata["spec"].stage == stage)

    def normalized(self) -> MapParams:
        changes: dict[str, Any] = {}
        for f in fields(self):
            spec: ParamSpec = f.metadata["spec"]
            current = getattr(self, f.name)
            if not math.isfinite(current):
                changes[f.name] = f.default
                continue
            value = min(max(current, spec.minimum), spec.maximum)
            changes[f.name] = round(value) if isinstance(f.default, int) else float(value)
        changes["ngram_max"] = max(changes["ngram_max"], changes["ngram_min"])
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MapParams:
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

    def resolved_min_cluster_size(self, count: int) -> int:
        return self.min_cluster_size or max(5, count // 100)

    def resolved_min_samples(self, count: int) -> int:
        return self.min_samples or self.resolved_min_cluster_size(count)


def param_specs() -> list[tuple[str, ParamSpec, int | float]]:
    return [(f.name, f.metadata["spec"], f.default) for f in fields(MapParams)]


def changed_stage(old: MapParams, new: MapParams) -> str | None:
    for stage in STAGES:
        if old.values_for(stage) != new.values_for(stage):
            return stage
    return None

from __future__ import annotations

import json
import os
import pickle
import time
import zipfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np

from wafer.core.common.paths import resolve_cache_path, setting_db_path
from wafer.core.db.path_values import PathValue
from wafer.core.db.setting_db import SettingDB
from wafer.core.logs import AppLogger

from . import projection
from .encoders import ENCODERS, BaseEncoder, expand_group_keys, feature_input
from .params import MapParams
from .session import OUTPUT_PREFIX, FeatureSpec, MapError

PRESET_KEY = "mapping.preset"
COORD_COLUMNS = 4
K_NEIGHBORS = 10
STATUS_FILE = "status.json"
PATH_SEPARATOR = "\n"


class SpaceLoadError(Exception):
    pass


@dataclass
class Preset:
    features: list[FeatureSpec]
    params: MapParams
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"features": [f.to_dict() for f in self.features], "params": self.params.to_dict(), "version": self.version}

    @classmethod
    def from_dict(cls, data: Any) -> Preset | None:
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            return None
        features = [spec for spec in (FeatureSpec.from_dict(item) for item in data["features"]) if spec is not None]
        try:
            version = int(data.get("version", 0))
        except (TypeError, ValueError):
            version = 0
        return cls(features, MapParams.from_dict(data.get("params") or {}), max(version, 0))

    def value_keys(self) -> list[str]:
        keys: list[str] = []
        for feature in self.features:
            keys.extend(expand_group_keys(feature.key) if ENCODERS[feature.encoder].KEY_GROUP else [feature.key])
        return list(dict.fromkeys(keys))

    def trigger_keys(self) -> tuple[str, ...]:
        return ("file_hash", *self.value_keys())


def settings_db(db_name: str) -> SettingDB:
    return SettingDB(setting_db_path(db_name))


def load_preset(db_name: str) -> Preset | None:
    return Preset.from_dict(settings_db(db_name).get_setting(PRESET_KEY))


def save_preset(db_name: str, preset: Preset) -> None:
    settings_db(db_name).set_setting(PRESET_KEY, preset.to_dict())


def model_dir(db_name: str) -> Path:
    return Path(resolve_cache_path(f"mapping/{db_name}"))


@dataclass
class SpaceStatus:
    state: str
    version: int
    trained: int = 0
    built_at: float = 0.0
    error: str = ""
    sources_at_training: int = 0


def read_status(directory: Path) -> SpaceStatus:
    try:
        data = json.loads((directory / STATUS_FILE).read_text("utf-8"))
        return SpaceStatus(**{f.name: data[f.name] for f in fields(SpaceStatus) if f.name in data})
    except FileNotFoundError:
        return SpaceStatus("none", 0)
    except (OSError, ValueError, TypeError) as e:
        AppLogger.warning(f"[Mapping] Unreadable space status in {directory}", exc=e)
        return SpaceStatus("none", 0)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def write_status(directory: Path, status: SpaceStatus) -> None:
    write_atomic(directory / STATUS_FILE, json.dumps(asdict(status)).encode("utf-8"))


def encode_paths(paths: list[str]) -> np.ndarray:
    return np.frombuffer(PATH_SEPARATOR.join(paths).encode("utf-8"), dtype=np.uint8)


def decode_paths(blob: np.ndarray) -> list[str]:
    text = blob.tobytes().decode("utf-8")
    return text.split(PATH_SEPARATOR) if text else []


class SpaceModel:
    def __init__(self, preset, encoders, reducers, scales, train_paths, matrix, coords, built_at):
        self.preset = preset
        self.version = preset.version
        self.encoders: list[BaseEncoder] = encoders
        self.reducers: list[projection.BlockReducer] = reducers
        self.scales: list[projection.BlockScale] = scales
        self.train_paths: list[str] = train_paths
        self.train_index = {path: i for i, path in enumerate(train_paths)}
        self.matrix = matrix
        self.coords = coords
        self.built_at = built_at
        self.neighbours = None

    @classmethod
    def fit(cls, preset: Preset, values: dict[str, dict[str, PathValue]], *, cancelled=lambda: False) -> SpaceModel:
        paths = list(values)
        encoders, reducers, blocks = [], [], []
        has_value = np.zeros(len(paths), dtype=bool)
        params = preset.params.normalized()
        for feature in preset.features:
            if cancelled():
                raise MapError("Cancelled")
            encoder_cls = ENCODERS[feature.encoder]
            encoder = encoder_cls(feature.options)
            inputs = [feature_input(values[path], feature.key, encoder_cls) for path in paths]
            raw = encoder.fit_transform(inputs, params)
            reducer = projection.BlockReducer(encoder.summary_dims(), params.seed)
            present = encoder.present(inputs)
            blocks.append((feature.label(), reducer.fit_transform(raw), present, feature.weight))
            encoders.append(encoder)
            reducers.append(reducer)
            has_value |= present
        active = np.flatnonzero(has_value)
        if active.size < 3:
            raise MapError("Not enough files have values for the selected keys.")
        combined, _stats, scales = projection.combine_blocks([(label, dense[active], present[active], weight) for label, dense, present, weight in blocks], params.seed)
        neighbors = params.resolved_neighbors(active.size)
        display = projection.embed(combined, 2, neighbors, params.min_dist, params.seed)
        if cancelled():
            raise MapError("Cancelled")
        grouping = projection.embed(combined, 2, neighbors, projection.GROUPING_MIN_DIST, params.seed)
        coords = np.hstack([display, grouping])
        return cls(preset, encoders, reducers, scales, [paths[i] for i in active], combined.astype(np.float16), coords.astype(np.float32), time.time())

    def coords_for(self, path: str) -> tuple[float, ...] | None:
        index = self.train_index.get(path)
        return None if index is None else tuple(float(value) for value in self.coords[index])

    def place(self, entries: list[dict[str, PathValue]]) -> np.ndarray:
        parts = []
        has_value = np.zeros(len(entries), dtype=bool)
        for feature, encoder, reducer in zip(self.preset.features, self.encoders, self.reducers):
            encoder_cls = ENCODERS[feature.encoder]
            inputs = [feature_input(entry, feature.key, encoder_cls) for entry in entries]
            present = encoder.present(inputs)
            parts.append((reducer.transform(encoder.transform(inputs)), present))
            has_value |= present
        output = np.full((len(entries), COORD_COLUMNS), np.nan, dtype=np.float32)
        rows = np.flatnonzero(has_value)
        if rows.size == 0:
            return output
        query = projection.apply_block_scales([(dense[rows], present[rows]) for dense, present in parts], self.scales)
        if self.neighbours is None:
            from sklearn.neighbors import NearestNeighbors

            self.neighbours = NearestNeighbors(n_neighbors=min(K_NEIGHBORS, len(self.train_paths))).fit(self.matrix.astype(np.float32))
        distances, indices = self.neighbours.kneighbors(query)
        weights = 1.0 / (distances + 1e-6)
        output[rows] = (self.coords[indices] * weights[..., None]).sum(axis=1) / weights.sum(axis=1, keepdims=True)
        return output

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for encoder in self.encoders:
            encoder.compact()
        stem = f"model-v{self.version}"
        arrays = directory / f"{stem}.npz.tmp"
        with open(arrays, "wb") as handle:
            np.savez(handle, train_paths=encode_paths(self.train_paths), matrix=self.matrix, coords=self.coords)
        os.replace(arrays, directory / f"{stem}.npz")
        state = {"preset": self.preset.to_dict(), "encoders": self.encoders, "reducers": self.reducers, "scales": self.scales, "built_at": self.built_at}
        write_atomic(directory / f"{stem}.pkl", pickle.dumps(state))
        for stale in directory.glob("model-v*.*"):
            if stale.name.startswith(stem + "."):
                continue
            try:
                stale.unlink(missing_ok=True)
            except OSError as e:
                AppLogger.warning(f"[Mapping] Could not remove old model file {stale}", exc=e)

    @classmethod
    def load(cls, directory: Path, current: Preset) -> SpaceModel | None:
        stem = directory / f"model-v{current.version}"
        if not stem.with_suffix(".pkl").exists() or not stem.with_suffix(".npz").exists():
            return None
        try:
            state = pickle.loads(stem.with_suffix(".pkl").read_bytes())
            preset = Preset.from_dict(state["preset"])
            if preset is None:
                raise ValueError("invalid preset in model")
            if preset.to_dict() != current.to_dict():
                AppLogger.info(f"[Mapping] The saved space model v{current.version} in {directory} was built from other settings; it will be retrained")
                return None
            with np.load(stem.with_suffix(".npz")) as arrays:
                train_paths = decode_paths(arrays["train_paths"])
                matrix, coords = arrays["matrix"], arrays["coords"]
            encoders, reducers, scales = state["encoders"], state["reducers"], state["scales"]
            if not len(train_paths) == len(matrix) == len(coords):
                raise ValueError("model arrays have different row counts")
            if coords.ndim != 2 or coords.shape[1] != COORD_COLUMNS:
                raise ValueError("model was built without grouping coordinates")
            if not len(preset.features) == len(encoders) == len(reducers) == len(scales):
                raise ValueError("model blocks do not match the preset features")
            return cls(preset, encoders, reducers, scales, train_paths, matrix, coords, float(state["built_at"]))
        except (OSError, zipfile.BadZipFile, pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError, KeyError, ValueError, TypeError, MemoryError) as e:
            raise SpaceLoadError(str(e)) from e

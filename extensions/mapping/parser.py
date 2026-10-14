from __future__ import annotations

import threading
import time

import numpy as np

from wafer.core.common.paths import data_db_path
from wafer.core.db.path_values import fetch_path_values
from wafer.core.logs import AppLogger
from wafer.plugin import BaseParserPlugin, ParserResult

from .session import SPACE_KEYS
from .space import OUTPUT_PREFIX, Preset, SpaceLoadError, SpaceModel, SpaceStatus, load_preset, model_dir, write_status

IDLE_TIMEOUT = 60.0
PRESET_TTL = 5.0
UNREAD = object()


class MappingParser(BaseParserPlugin):
    NAME = "mapping"
    DISPLAY_NAME = "Mapping"
    PRIORITY = 10
    DEFAULT_ENABLED = True
    DEFAULT_ENABLED_PER_DB = False
    TRIGGER_KEYS = ("file_hash",)
    BATCH_SIZE = 600
    MAX_WORKERS = 1
    MAX_TIMEOUT = 3600.0

    def __init__(self):
        self.lock = threading.Lock()
        self.model: SpaceModel | None = None
        self.blocked: tuple[int, bool] | None = None
        self.stopping = threading.Event()
        self.preset: Preset | None = None
        self.preset_loaded = 0.0
        self.last_used = 0.0
        self.idle_timer: threading.Timer | None = None

    @classmethod
    def trigger_keys(cls, db_name: str) -> tuple[str, ...]:
        preset = load_preset(db_name) if db_name else None
        return preset.trigger_keys() if preset and preset.features else cls.TRIGGER_KEYS

    def current_preset(self) -> Preset | None:
        if self.preset is None or time.monotonic() - self.preset_loaded >= PRESET_TTL:
            self.preset = load_preset(self.db_name)
            self.preset_loaded = time.monotonic()
        return self.preset

    def process(self, path, file_info, metadata):
        preset = self.current_preset()
        if preset is None or not preset.features:
            return ParserResult(source=path, status=True)
        with self.lock:
            try:
                model = self.ensure_model(preset)
                if model is None:
                    return ParserResult(source=path, status=self.blocked == (preset.version, True))
                point = self.position(model, path)
            finally:
                self.touch()
        if point is UNREAD:
            return ParserResult(source=path, status=False)
        if point is None:
            return ParserResult(source=path, status=True, delete_meta_keys=list(SPACE_KEYS))
        return ParserResult(source=path, status=True, meta_info={"x": repr(point[0]), "y": repr(point[1]), "model": str(model.version)})

    def ensure_model(self, preset: Preset) -> SpaceModel | None:
        if self.model is not None and self.model.preset.to_dict() == preset.to_dict():
            return self.model
        if self.blocked is not None and self.blocked[0] == preset.version:
            return None
        directory = model_dir(self.db_name)
        try:
            self.model = SpaceModel.load(directory, preset)
        except SpaceLoadError as e:
            AppLogger.warning(f"[Mapping] Cannot read the space model for {self.db_name}; retrain from Mapping Space", exc=e)
            write_status(directory, SpaceStatus("unreadable", preset.version, error=str(e)))
            self.blocked = (preset.version, True)
            return None
        if self.model is None:
            self.model = self.train(preset, directory)
        return self.model

    def train(self, preset: Preset, directory) -> SpaceModel | None:
        started = time.perf_counter()
        paths: list[str] = []
        try:
            write_status(directory, SpaceStatus("training", preset.version))
            paths = [row[0] for row in self.query_db("SELECT source FROM sources")]
            values = fetch_path_values(data_db_path(self.db_name), paths, keys=preset.value_keys())
            model = SpaceModel.fit(preset, values, cancelled=self.stopping.is_set)
            model.save(directory)
        except Exception as e:
            if self.stopping.is_set():
                AppLogger.info(f"[Mapping] Training the space for {self.db_name} was interrupted; it restarts on the next run")
                return None
            AppLogger.error(f"[Mapping] Training the space failed for {self.db_name}", exc=e)
            self.blocked = (preset.version, False)
            write_status(directory, SpaceStatus("failed", preset.version, error=str(e)))
            return None
        write_status(directory, SpaceStatus("ready", preset.version, trained=len(model.train_paths), built_at=model.built_at, sources_at_training=len(paths)))
        AppLogger.info(f"[Mapping] Trained space v{preset.version} for {self.db_name}: {len(model.train_paths)} files in {time.perf_counter() - started:.1f}s")
        return model

    def position(self, model: SpaceModel, path: str):
        rows = self.query_db("SELECT value FROM meta_info WHERE path = ? AND key = ?", (path, f"{OUTPUT_PREFIX}.model"))
        stored = rows[0][0] if rows else None
        if stored != str(model.version):
            trained = model.coords_for(path)
            if trained is not None:
                return trained
        entry = fetch_path_values(data_db_path(self.db_name), [path], keys=model.preset.value_keys()).get(path)
        if entry is None:
            return UNREAD
        point = model.place([entry])[0]
        return None if np.isnan(point).any() else (float(point[0]), float(point[1]))

    def touch(self):
        self.last_used = time.monotonic()
        if self.idle_timer is None:
            self.arm(IDLE_TIMEOUT)

    def arm(self, delay: float):
        if self.stopping.is_set():
            return
        if self.idle_timer is not None:
            self.idle_timer.cancel()
        self.idle_timer = threading.Timer(delay, self.release_if_idle)
        self.idle_timer.daemon = True
        self.idle_timer.start()

    def release_if_idle(self):
        with self.lock:
            remaining = IDLE_TIMEOUT - (time.monotonic() - self.last_used)
            if remaining > 0:
                if self.idle_timer is threading.current_thread():
                    self.arm(remaining)
                return
            if self.idle_timer is threading.current_thread():
                self.idle_timer = None
            if self.model is None:
                return
            self.model = None
        AppLogger.info("[Mapping] Space model released (idle timeout)")

    def shutdown(self):
        self.stopping.set()
        if self.idle_timer is not None:
            self.idle_timer.cancel()
            self.idle_timer = None
        super().shutdown()

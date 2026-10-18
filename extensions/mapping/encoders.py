from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, ClassVar

import numpy as np

from wafer.core.db.path_values import PathValue
from wafer.core.logs import AppLogger


PALETTE_KEY = "color.palette"
PALETTE_MAX_SLOTS = 30
PALETTE_BINS = (4, 8, 8)
PALETTE_RANGE = ((0.0, 100.0), (-80.0, 80.0), (-80.0, 80.0))
SEPARATORS = {"comma": r",", "newline": r"[\r\n]+", "semicolon": r";", "pipe": r"\|", "space": r"\s+"}
AUTO_SEPARATORS = ("comma", "newline", "semicolon", "pipe")
_WEIGHTED_TOKEN = re.compile(r"^\((.+):\s*([0-9]*\.?[0-9]+)\)$")
_WRAPPERS = str.maketrans("", "", "{}[]()")
_PATH_SPLIT = re.compile(r"[\\/]+")


@dataclass(frozen=True, slots=True)
class OptionSpec:
    name: str
    label: str
    description: str
    default: str
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int = 0
    maximum: int = 0

    @property
    def numeric(self) -> bool:
        return self.maximum > self.minimum


SUMMARY_DIMS = 50
TEXT_MAX_CHARS = 12
SUMMARY_OPTION = OptionSpec(
    "summary",
    "Detail",
    "How many dimensions this key is summarized into. Higher keeps finer differences, is slower, and makes the key count a little more.",
    str(SUMMARY_DIMS),
    minimum=2,
    maximum=300,
)


class BaseEncoder(ABC):
    NAME: ClassVar[str]
    DISPLAY_NAME: ClassVar[str]
    DESCRIPTION: ClassVar[str]
    OPTIONS: ClassVar[tuple[OptionSpec, ...]] = ()
    KEY_GROUP: ClassVar[bool] = False
    AUTO_DETECT: ClassVar[bool] = True

    def __init__(self, options: dict[str, str] | None = None):
        self.options = {spec.name: spec.default for spec in self.OPTIONS}
        self.options.update(options or {})

    @classmethod
    def detect(cls, values: Sequence[PathValue]) -> float:
        return 0.0

    def present(self, inputs: Sequence[Any]) -> np.ndarray:
        return np.array([item is not None for item in inputs], dtype=bool)

    @classmethod
    def number_option(cls, options: dict[str, str], name: str) -> int:
        spec = next(option for option in cls.OPTIONS if option.name == name)
        try:
            value = int(options.get(name, spec.default))
        except (TypeError, ValueError) as e:
            AppLogger.warning(f"[Mapping] Ignored invalid option {name}={options.get(name)!r}", exc=e)
            value = int(spec.default)
        return min(max(value, spec.minimum), spec.maximum)

    @classmethod
    def summary_dims(cls, options: dict[str, str]) -> int:
        return cls.number_option(options, SUMMARY_OPTION.name) if SUMMARY_OPTION in cls.OPTIONS else SUMMARY_DIMS

    @abstractmethod
    def fit_transform(self, inputs: Sequence[Any]): ...

    @abstractmethod
    def transform(self, inputs: Sequence[Any]): ...


def value_input(value: PathValue | None) -> PathValue | None:
    if value is None or (not value.text.strip() and value.number is None):
        return None
    return value


def group_values(entry: dict[str, PathValue], prefix: str) -> list[PathValue] | None:
    marker = prefix + "."
    slots = []
    for key, value in entry.items():
        suffix = key[len(marker) :] if key.startswith(marker) else ""
        if suffix.isdigit() and value.number is not None and math.isfinite(value.number):
            slots.append((int(suffix), value))
    return [value for _, value in sorted(slots, key=lambda slot: slot[0])] or None


def expand_group_keys(prefix: str) -> list[str]:
    return [f"{prefix}.{n}" for n in range(1, PALETTE_MAX_SLOTS + 1)]


def feature_input(entry: dict[str, PathValue], key: str, encoder: type[BaseEncoder]):
    return group_values(entry, key) if encoder.KEY_GROUP else value_input(entry.get(key))


class NumericEncoder(BaseEncoder):
    NAME = "numeric"
    DISPLAY_NAME = "Number"
    DESCRIPTION = "Compares how close the numbers are (dates, sizes, ...)."
    OPTIONS = (
        OptionSpec(
            "scale",
            "Compare by",
            "Rank: by order, robust to uneven values. Difference: the raw difference. Magnitude: by orders of magnitude.",
            "rank",
            (("rank", "Rank"), ("linear", "Difference"), ("log", "Magnitude")),
        ),
    )

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.reference = np.zeros(0, dtype=np.float64)
        self.positions = np.zeros(0, dtype=np.float64)
        self.low, self.high = 0.0, 1.0

    @classmethod
    def detect(cls, values):
        if not values:
            return 0.0
        numeric = sum(1 for value in values if value.number is not None)
        return 0.95 if numeric / len(values) >= 0.9 else 0.0

    def present(self, inputs):
        return np.array([item is not None and item.number is not None and np.isfinite(item.number) for item in inputs], dtype=bool)

    def fit_transform(self, inputs):
        present = self.present(inputs)
        values = self.scaled(np.array([item.number for item, ok in zip(inputs, present) if ok], dtype=np.float64))
        self.reference, counts = np.unique(values, return_counts=True)
        average_rank = np.cumsum(counts) - (counts - 1) / 2
        self.positions = (average_rank - 1) / max(values.size - 1, 1)
        if self.reference.size:
            self.low, self.high = float(self.reference[0]), float(self.reference[-1])
        return self.transform(inputs)

    def scaled(self, numbers: np.ndarray) -> np.ndarray:
        if self.options["scale"] == "log":
            return np.sign(numbers) * np.log1p(np.abs(numbers))
        return numbers

    def transform(self, inputs):
        present = self.present(inputs)
        output = np.zeros((len(inputs), 1), dtype=np.float32)
        if not present.any() or self.reference.size == 0:
            return output
        values = self.scaled(np.array([item.number for item, ok in zip(inputs, present) if ok], dtype=np.float64))
        if self.options["scale"] == "rank":
            output[present, 0] = np.interp(values, self.reference, self.positions)
        elif self.reference.size == 1:
            output[present, 0] = 0.0
        else:
            output[present, 0] = np.clip((values - self.low) / (self.high - self.low), 0.0, 1.0)
        return output


def detect_separator(texts: Sequence[str]) -> str:
    texts = [text for text in texts if text.strip()]
    if not texts:
        return "space"
    for name in AUTO_SEPARATORS:
        hits = sum(1 for text in texts if re.search(SEPARATORS[name], text))
        if hits >= len(texts) * 0.5:
            return name
    return "space"


@lru_cache(maxsize=65536)
def normalize_token(raw: str) -> tuple[str, float]:
    token = raw.strip()
    weight = 1.0
    match = _WEIGHTED_TOKEN.match(token)
    if match:
        token, weight = match.group(1), float(match.group(2))
    weight *= 1.05 ** (token.count("{") - token.count("[")) * 1.1 ** token.count("(")
    token = re.sub(r"\s+", " ", token.translate(_WRAPPERS).replace("_", " ")).strip().lower()
    return token, (weight if token else 1.0)


class TokenSetEncoder(BaseEncoder):
    NAME = "token_set"
    DISPLAY_NAME = "Tags"
    DESCRIPTION = "Compares how many separated words overlap. Rare words count more."
    OPTIONS = (
        OptionSpec(
            "separator",
            "Separator",
            "How words are split. Use Text for sentences without spaces, such as Japanese.",
            "auto",
            (("auto", "Auto"), ("comma", ","), ("newline", "New line"), ("semicolon", ";"), ("pipe", "|"), ("space", "Space"), ("custom", "Regex")),
        ),
        OptionSpec("pattern", "Regex", "Regular expression used when the separator is Regex.", ""),
        SUMMARY_OPTION,
    )

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.pattern = SEPARATORS["comma"]
        self.vectorizer = None
        self.tfidf = None

    @classmethod
    def detect(cls, values):
        texts = [value.text for value in values if value.text.strip()]
        return 0.8 if texts and detect_separator(texts) != "space" else 0.0

    def separator_pattern(self, texts: Sequence[str]) -> str:
        name = self.options["separator"]
        if name == "custom":
            pattern = self.options.get("pattern", "")
            try:
                re.compile(pattern)
            except re.error as e:
                AppLogger.warning(f"[Mapping] Invalid separator regex {pattern!r}; using auto", exc=e)
                pattern = ""
            if pattern:
                return pattern
            name = "auto"
        if name not in SEPARATORS:
            name = detect_separator(texts)
        return SEPARATORS[name]

    def documents(self, texts: Sequence[str]) -> list[dict[str, float]]:
        documents = []
        for text in texts:
            tokens: dict[str, float] = {}
            for raw in re.split(self.pattern, text):
                if not raw:
                    continue
                token, weight = normalize_token(raw)
                if token:
                    tokens[token] = max(tokens.get(token, 0.0), weight)
            documents.append(tokens)
        return documents

    def fit_transform(self, inputs):
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.feature_extraction.text import TfidfTransformer

        texts = [item.text if item is not None else "" for item in inputs]
        self.pattern = self.separator_pattern(texts)
        documents = self.documents(texts)
        if not any(documents):
            self.vectorizer, self.tfidf = None, None
            return np.zeros((len(inputs), 1), dtype=np.float32)
        self.vectorizer = DictVectorizer(dtype=np.float32)
        self.tfidf = TfidfTransformer()
        return self.tfidf.fit_transform(self.vectorizer.fit_transform(documents)).tocsr()

    def transform(self, inputs):
        if self.vectorizer is None:
            return np.zeros((len(inputs), 1), dtype=np.float32)
        texts = [item.text if item is not None else "" for item in inputs]
        return self.tfidf.transform(self.vectorizer.transform(self.documents(texts))).tocsr()


def folder_prefixes(text: str) -> tuple[str, ...]:
    parts = [part for part in _PATH_SPLIT.split(text.strip()) if part][:-1]
    return tuple("/".join(parts[: depth + 1]) for depth in range(len(parts)))


class PathEncoder(TokenSetEncoder):
    NAME = "path"
    DISPLAY_NAME = "Folders"
    DESCRIPTION = "Compares the folders in a path, ignoring the file name. Files in the same or nearby folders come closer."
    OPTIONS = (SUMMARY_OPTION,)

    @classmethod
    def detect(cls, values):
        texts = [value.text.strip() for value in values if value.text.strip()]
        nested = sum(1 for text in texts if _PATH_SPLIT.search(text) and "," not in text and "\n" not in text)
        return 0.85 if texts and nested >= len(texts) * 0.9 else 0.0

    def separator_pattern(self, texts):
        return _PATH_SPLIT.pattern

    def documents(self, texts):
        return [dict.fromkeys(folder_prefixes(text), 1.0) for text in texts]


class TextEncoder(BaseEncoder):
    NAME = "text"
    DISPLAY_NAME = "Text"
    DESCRIPTION = "Compares how similar the character sequences are. Works with any language or separator."
    OPTIONS = (
        OptionSpec("min_chars", "Min chars", "Compare text in chunks of at least this many characters. Lower tolerates spelling variations.", "2", minimum=1, maximum=TEXT_MAX_CHARS),
        OptionSpec("max_chars", "Max chars", "Compare text in chunks of at most this many characters. Higher is more sensitive to word differences.", "4", minimum=1, maximum=TEXT_MAX_CHARS),
        SUMMARY_OPTION,
    )

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.vectorizer = None

    @classmethod
    def detect(cls, values):
        return 0.5 if any(value.text.strip() for value in values) else 0.0

    def fit_transform(self, inputs):
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [item.text if item is not None else "" for item in inputs]
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=self.ngram_range(),
            sublinear_tf=True,
            max_features=100_000,
            dtype=np.float32,
        )
        try:
            matrix = vectorizer.fit_transform(texts).tocsr()
        except ValueError as e:
            AppLogger.warning("[Mapping] Text key has no usable characters", exc=e)
            self.vectorizer = None
            return np.zeros((len(inputs), 1), dtype=np.float32)
        self.vectorizer = vectorizer
        return matrix

    def ngram_range(self) -> tuple[int, int]:
        low, high = self.number_option(self.options, "min_chars"), self.number_option(self.options, "max_chars")
        return min(low, high), max(low, high)

    def transform(self, inputs):
        if self.vectorizer is None:
            return np.zeros((len(inputs), 1), dtype=np.float32)
        return self.vectorizer.transform([item.text if item is not None else "" for item in inputs]).tocsr()


class CategoryEncoder(BaseEncoder):
    NAME = "category"
    DISPLAY_NAME = "Category"
    DESCRIPTION = "Only checks whether the values are exactly the same."
    OPTIONS = (SUMMARY_OPTION,)

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.codes: dict[str, int] = {}

    @classmethod
    def detect(cls, values):
        texts = [value.text.strip() for value in values if value.text.strip()]
        if len(texts) < 2:
            return 0.0
        return 0.7 if len(set(texts)) <= max(2, len(texts) * 0.2) else 0.0

    def fit_transform(self, inputs):
        values = {item.text.strip() for item in inputs if item is not None}
        self.codes = {value: i for i, value in enumerate(sorted(value for value in values if value))}
        return self.transform(inputs)

    def transform(self, inputs):
        from scipy import sparse

        values = [item.text.strip() if item is not None else "" for item in inputs]
        rows = [i for i, value in enumerate(values) if value in self.codes]
        columns = [self.codes[values[i]] for i in rows]
        return sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, columns)), shape=(len(inputs), max(len(self.codes), 1)))


_RGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]],
    dtype=np.float32,
)
_WHITE = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    color = rgb.astype(np.float32) / 255.0
    linear = np.where(color <= 0.04045, color / 12.92, ((color + 0.055) / 1.055) ** 2.4)
    xyz = linear @ _RGB_TO_XYZ.T / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def packed_lab(numbers: np.ndarray) -> np.ndarray:
    packed = np.asarray(numbers, dtype=np.float64).astype(np.int64) & 0xFFFFFF
    rgb = np.stack([(packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF], axis=-1).astype(np.uint8)
    return rgb_to_lab(rgb)


def soft_bins(labs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    indices, weights = np.zeros((len(labs), 1), dtype=np.int64), np.ones((len(labs), 1), dtype=np.float64)
    for channel, ((low, high), bins) in enumerate(zip(PALETTE_RANGE, PALETTE_BINS)):
        position = (np.clip(labs[:, channel].astype(np.float64), low, high) - low) / (high - low) * bins - 0.5
        base = np.floor(position)
        fraction = position - base
        channel_bins = np.stack([np.clip(base, 0, bins - 1), np.clip(base + 1, 0, bins - 1)], axis=1).astype(np.int64)
        channel_weights = np.stack([1.0 - fraction, fraction], axis=1)
        indices = (indices[:, :, None] * bins + channel_bins[:, None, :]).reshape(len(labs), -1)
        weights = (weights[:, :, None] * channel_weights[:, None, :]).reshape(len(labs), -1)
    return indices, weights


class PaletteEncoder(BaseEncoder):
    NAME = "palette"
    DISPLAY_NAME = "Color palette"
    DESCRIPTION = "Compares the dominant colors found by the Color collector."
    KEY_GROUP = True
    AUTO_DETECT = False

    def fit_transform(self, inputs):
        return self.transform(inputs)

    def transform(self, inputs):
        output = np.zeros((len(inputs), int(np.prod(PALETTE_BINS))), dtype=np.float64)
        rows, ranks, numbers = [], [], []
        for row, slots in enumerate(inputs):
            if not slots:
                continue
            weights = 1.0 / np.arange(1, len(slots) + 1)
            rows += [row] * len(slots)
            ranks.append(weights / weights.sum())
            numbers += [slot.number for slot in slots]
        if rows:
            indices, shares = soft_bins(packed_lab(np.array(numbers)))
            np.add.at(output, (np.array(rows)[:, None], indices), np.concatenate(ranks)[:, None] * shares)
        return np.sqrt(output).astype(np.float32)


ENCODERS: dict[str, type[BaseEncoder]] = {cls.NAME: cls for cls in (NumericEncoder, TokenSetEncoder, PathEncoder, TextEncoder, CategoryEncoder, PaletteEncoder)}


def auto_encoders() -> list[type[BaseEncoder]]:
    return [cls for cls in ENCODERS.values() if cls.AUTO_DETECT]


def detect_encoder(values: Sequence[PathValue]) -> str:
    return max(auto_encoders(), key=lambda cls: cls.detect(values)).NAME

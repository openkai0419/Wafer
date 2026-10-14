from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import numpy as np

from wafer.core.db.path_values import PathValue
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger

from .params import MapParams

PALETTE_KEY = "color.palette"
PALETTE_MAX_SLOTS = 30
PALETTE_BINS = (4, 8, 8)
PALETTE_RANGE = ((0.0, 100.0), (-80.0, 80.0), (-80.0, 80.0))
SEPARATORS = {"comma": r",", "newline": r"[\r\n]+", "semicolon": r";", "pipe": r"\|", "space": r"\s+"}
AUTO_SEPARATORS = ("comma", "newline", "semicolon", "pipe")
TIMESTAMP_RANGE = (9.0e8, 4.2e9)
_WEIGHTED_TOKEN = re.compile(r"^\((.+):\s*([0-9]*\.?[0-9]+)\)$")
_WRAPPERS = str.maketrans("", "", "{}[]()")
_WORD_SPLIT = re.compile(r"[\s,.;:!?、。\uff0c\uff0e・/|()\[\]{}\"'「」『』【】]+")


@dataclass(frozen=True, slots=True)
class OptionSpec:
    name: str
    label: str
    description: str
    default: str
    choices: tuple[tuple[str, str], ...] = ()


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

    @abstractmethod
    def fit_transform(self, inputs: Sequence[Any], params: MapParams): ...

    @abstractmethod
    def transform(self, inputs: Sequence[Any]): ...

    @abstractmethod
    def describe(self, members: np.ndarray, params: MapParams) -> list[str]: ...

    def compact(self) -> None:
        return None


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


def top_lift_terms(matrix, members: np.ndarray, names, count: int) -> list[str]:
    if matrix is None or matrix.shape[1] == 0 or len(members) == 0:
        return []
    inside = np.asarray(matrix[members].mean(axis=0)).ravel()
    overall = np.asarray(matrix.mean(axis=0)).ravel()
    lift = inside - overall
    return [str(names[i]) for i in np.argsort(-lift, kind="stable")[:count] if lift[i] > 0]


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
        self.numbers = np.zeros(0, dtype=np.float64)
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

    def fit_transform(self, inputs, params):
        present = self.present(inputs)
        self.numbers = np.array([item.number if ok else np.nan for item, ok in zip(inputs, present)], dtype=np.float64)
        values = self.scaled(self.numbers[present])
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

    def compact(self):
        self.numbers = np.zeros(0, dtype=np.float64)

    def describe(self, members, params):
        if self.numbers.size == 0:
            return []
        numbers = self.numbers[members]
        numbers = numbers[np.isfinite(numbers)]
        if numbers.size == 0:
            return []
        low, high = float(numbers.min()), float(numbers.max())
        if TIMESTAMP_RANGE[0] <= low and high <= TIMESTAMP_RANGE[1]:
            start = datetime.fromtimestamp(low).strftime("%Y-%m-%d")
            end = datetime.fromtimestamp(high).strftime("%Y-%m-%d")
            return [start if start == end else f"{start} \u2013 {end}"]
        return [f"{low:g}" if low == high else f"{low:g} \u2013 {high:g}"]


def detect_separator(texts: Sequence[str]) -> str:
    texts = [text for text in texts if text.strip()]
    if not texts:
        return "space"
    for name in AUTO_SEPARATORS:
        hits = sum(1 for text in texts if re.search(SEPARATORS[name], text))
        if hits >= len(texts) * 0.5:
            return name
    return "space"


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
    )

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.pattern = SEPARATORS["comma"]
        self.vectorizer = None
        self.tfidf = None
        self.matrix = None
        self.names = []

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

    def fit_transform(self, inputs, params):
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.feature_extraction.text import TfidfTransformer

        texts = [item.text if item is not None else "" for item in inputs]
        self.pattern = self.separator_pattern(texts)
        documents = self.documents(texts)
        if not any(documents):
            self.vectorizer, self.tfidf, self.matrix, self.names = None, None, None, []
            return np.zeros((len(inputs), 1), dtype=np.float32)
        self.vectorizer = DictVectorizer(dtype=np.float32)
        self.tfidf = TfidfTransformer()
        self.matrix = self.tfidf.fit_transform(self.vectorizer.fit_transform(documents)).tocsr()
        self.names = self.vectorizer.get_feature_names_out()
        return self.matrix

    def transform(self, inputs):
        if self.vectorizer is None:
            return np.zeros((len(inputs), 1), dtype=np.float32)
        texts = [item.text if item is not None else "" for item in inputs]
        return self.tfidf.transform(self.vectorizer.transform(self.documents(texts))).tocsr()

    def compact(self):
        self.matrix, self.names = None, []

    def describe(self, members, params):
        return top_lift_terms(self.matrix, members, self.names, params.label_terms)


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD_SPLIT.split(text) if len(word) > 1]


class TextEncoder(BaseEncoder):
    NAME = "text"
    DISPLAY_NAME = "Text"
    DESCRIPTION = "Compares how similar the character sequences are. Works with any language or separator."

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.texts: list[str] = []
        self.vectorizer = None
        self.words_matrix = None
        self.word_names = []

    @classmethod
    def detect(cls, values):
        return 0.5 if any(value.text.strip() for value in values) else 0.0

    def fit_transform(self, inputs, params):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.texts = [item.text if item is not None else "" for item in inputs]
        self.words_matrix = None
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(params.ngram_min, params.ngram_max),
            sublinear_tf=True,
            max_features=100_000,
            dtype=np.float32,
        )
        try:
            matrix = vectorizer.fit_transform(self.texts).tocsr()
        except ValueError as e:
            AppLogger.warning("[Mapping] Text key has no usable characters", exc=e)
            self.vectorizer = None
            return np.zeros((len(inputs), 1), dtype=np.float32)
        self.vectorizer = vectorizer
        return matrix

    def transform(self, inputs):
        if self.vectorizer is None:
            return np.zeros((len(inputs), 1), dtype=np.float32)
        return self.vectorizer.transform([item.text if item is not None else "" for item in inputs]).tocsr()

    def compact(self):
        self.texts = []
        self.words_matrix, self.word_names = None, []

    def describe(self, members, params):
        from scipy import sparse
        from sklearn.feature_extraction.text import CountVectorizer

        if not self.texts:
            return []
        if self.words_matrix is None:
            vectorizer = CountVectorizer(analyzer=_words, binary=True, dtype=np.float32)
            try:
                self.words_matrix = vectorizer.fit_transform(self.texts).tocsr()
                self.word_names = vectorizer.get_feature_names_out()
            except ValueError as e:
                AppLogger.warning("[Mapping] Text key has no words to label groups", exc=e)
                self.words_matrix = sparse.csr_matrix((len(self.texts), 0), dtype=np.float32)
                self.word_names = []
        return top_lift_terms(self.words_matrix, members, self.word_names, params.label_terms)


class CategoryEncoder(BaseEncoder):
    NAME = "category"
    DISPLAY_NAME = "Category"
    DESCRIPTION = "Only checks whether the values are exactly the same."

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.values: list[str] = []
        self.codes: dict[str, int] = {}

    @classmethod
    def detect(cls, values):
        texts = [value.text.strip() for value in values if value.text.strip()]
        if len(texts) < 2:
            return 0.0
        return 0.7 if len(set(texts)) <= max(2, len(texts) * 0.2) else 0.0

    def fit_transform(self, inputs, params):
        self.values = [item.text.strip() if item is not None else "" for item in inputs]
        self.codes = {value: i for i, value in enumerate(sorted({v for v in self.values if v}))}
        return self.transform(inputs)

    def transform(self, inputs):
        from scipy import sparse

        values = [item.text.strip() if item is not None else "" for item in inputs]
        rows = [i for i, value in enumerate(values) if value in self.codes]
        columns = [self.codes[values[i]] for i in rows]
        return sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, columns)), shape=(len(inputs), max(len(self.codes), 1)))

    def compact(self):
        self.values = []

    def describe(self, members, params):
        if not self.values:
            return []
        counts = Counter(self.values[i] for i in members if self.values[i])
        return [counts.most_common(1)[0][0]] if counts else []


BRIGHT_L, DARK_L = 65.0, 35.0
COLOR_NAMES = (
    ("red", (53.0, 80.0, 67.0)),
    ("orange", (67.0, 43.0, 74.0)),
    ("yellow", (97.0, -21.0, 94.0)),
    ("green", (46.0, -52.0, 50.0)),
    ("cyan", (91.0, -48.0, -14.0)),
    ("blue", (32.0, 79.0, -108.0)),
    ("purple", (30.0, 58.0, -36.0)),
    ("pink", (84.0, 24.0, 4.0)),
    ("brown", (37.0, 24.0, 43.0)),
    ("white", (100.0, 0.0, 0.0)),
    ("gray", (54.0, 0.0, 0.0)),
    ("black", (0.0, 0.0, 0.0)),
)
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


def unpack_rgb(value: float) -> tuple[int, int, int]:
    packed = int(value) & 0xFFFFFF
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def soft_bin_weights(lab: np.ndarray) -> list[tuple[int, float]]:
    coords = []
    for value, (low, high), bins in zip(lab, PALETTE_RANGE, PALETTE_BINS):
        position = (min(max(float(value), low), high) - low) / (high - low) * bins - 0.5
        base = math.floor(position)
        fraction = position - base
        coords.append([(min(max(base, 0), bins - 1), 1.0 - fraction), (min(max(base + 1, 0), bins - 1), fraction)])
    weights = []
    for i, wi in coords[0]:
        for j, wj in coords[1]:
            for k, wk in coords[2]:
                weights.append(((i * PALETTE_BINS[1] + j) * PALETTE_BINS[2] + k, wi * wj * wk))
    return weights


class PaletteEncoder(BaseEncoder):
    NAME = "palette"
    DISPLAY_NAME = "Color palette"
    DESCRIPTION = "Compares the dominant colors found by the Color collector."
    KEY_GROUP = True
    AUTO_DETECT = False

    def __init__(self, options: dict[str, str] | None = None):
        super().__init__(options)
        self.first_colors = np.zeros((0, 3), dtype=np.float32)

    def fit_transform(self, inputs, params):
        nan = (np.nan, np.nan, np.nan)
        self.first_colors = np.array(
            [rgb_to_lab(np.array([unpack_rgb(slots[0].number)], dtype=np.uint8))[0] if slots else nan for slots in inputs],
            dtype=np.float32,
        ).reshape(-1, 3)
        return self.transform(inputs)

    def transform(self, inputs):
        output = np.zeros((len(inputs), int(np.prod(PALETTE_BINS))), dtype=np.float32)
        for row, slots in enumerate(inputs):
            if not slots:
                continue
            ranks = np.array([1.0 / (i + 1) for i in range(len(slots))])
            ranks /= ranks.sum()
            labs = rgb_to_lab(np.array([unpack_rgb(slot.number) for slot in slots], dtype=np.uint8))
            for lab, weight in zip(labs, ranks):
                for index, share in soft_bin_weights(lab):
                    output[row, index] += weight * share
        return np.sqrt(output)

    def compact(self):
        self.first_colors = np.zeros((0, 3), dtype=np.float32)

    def describe(self, members, params):
        if self.first_colors.shape[0] == 0:
            return []
        colors = self.first_colors[members]
        colors = colors[np.isfinite(colors).all(axis=1)]
        if colors.size == 0:
            return []
        mean = colors.mean(axis=0)
        name = min(COLOR_NAMES, key=lambda item: float(np.sum((np.array(item[1]) - mean) ** 2)))[0]
        terms = [t(name)]
        if mean[0] >= BRIGHT_L:
            terms.append(t("bright"))
        elif mean[0] <= DARK_L:
            terms.append(t("dark"))
        return terms


ENCODERS: dict[str, type[BaseEncoder]] = {cls.NAME: cls for cls in (NumericEncoder, TokenSetEncoder, TextEncoder, CategoryEncoder, PaletteEncoder)}


def auto_encoders() -> list[type[BaseEncoder]]:
    return [cls for cls in ENCODERS.values() if cls.AUTO_DETECT]


def detect_encoder(values: Sequence[PathValue]) -> str:
    return max(auto_encoders(), key=lambda cls: cls.detect(values)).NAME

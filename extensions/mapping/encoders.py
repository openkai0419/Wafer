from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Literal

import numpy as np

from wafer.core.db.path_values import PathValue
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger

from .params import MapParams
from .projection import median_pair_distance

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
    INPUT: ClassVar[Literal["value", "image"]] = "value"
    OPTIONS: ClassVar[tuple[OptionSpec, ...]] = ()

    def __init__(self, options: dict[str, str] | None = None):
        self.options = {spec.name: spec.default for spec in self.OPTIONS}
        self.options.update(options or {})

    @classmethod
    def detect(cls, values: Sequence[PathValue]) -> float:
        return 0.0

    def present(self, inputs: Sequence[Any]) -> np.ndarray:
        return np.array([item is not None for item in inputs], dtype=bool)

    @abstractmethod
    def encode(self, inputs: Sequence[Any], params: MapParams): ...

    @abstractmethod
    def describe(self, members: np.ndarray, params: MapParams) -> list[str]: ...


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

    @classmethod
    def detect(cls, values):
        if not values:
            return 0.0
        numeric = sum(1 for value in values if value.number is not None)
        return 0.95 if numeric / len(values) >= 0.9 else 0.0

    def present(self, inputs):
        return np.array([item is not None and item.number is not None and np.isfinite(item.number) for item in inputs], dtype=bool)

    def encode(self, inputs, params):
        present = self.present(inputs)
        self._numbers = np.array([item.number if ok else np.nan for item, ok in zip(inputs, present)], dtype=np.float64)
        output = np.zeros((len(inputs), 1), dtype=np.float32)
        numbers = self._numbers[present]
        if numbers.size == 0:
            return output
        scale = self.options["scale"]
        if scale == "rank":
            from scipy.stats import rankdata

            output[present, 0] = (rankdata(numbers) - 1) / max(numbers.size - 1, 1)
            return output
        if scale == "log":
            numbers = np.sign(numbers) * np.log1p(np.abs(numbers))
        low, high = numbers.min(), numbers.max()
        output[present, 0] = (numbers - low) / (high - low) if high > low else 0.0
        return output

    def describe(self, members, params):
        numbers = self._numbers[members]
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

    def encode(self, inputs, params):
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.feature_extraction.text import TfidfTransformer

        texts = [item.text if item is not None else "" for item in inputs]
        pattern = self.separator_pattern(texts)
        documents = []
        for text in texts:
            tokens: dict[str, float] = {}
            for raw in re.split(pattern, text):
                if not raw:
                    continue
                token, weight = normalize_token(raw)
                if token:
                    tokens[token] = max(tokens.get(token, 0.0), weight)
            documents.append(tokens)
        if not any(documents):
            self._matrix, self._names = None, []
            return np.zeros((len(inputs), 1), dtype=np.float32)
        vectorizer = DictVectorizer(dtype=np.float32)
        self._matrix = TfidfTransformer().fit_transform(vectorizer.fit_transform(documents)).tocsr()
        self._names = vectorizer.get_feature_names_out()
        return self._matrix

    def describe(self, members, params):
        return top_lift_terms(self._matrix, members, self._names, params.label_terms)


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD_SPLIT.split(text) if len(word) > 1]


class TextEncoder(BaseEncoder):
    NAME = "text"
    DISPLAY_NAME = "Text"
    DESCRIPTION = "Compares how similar the character sequences are. Works with any language or separator."

    @classmethod
    def detect(cls, values):
        return 0.5 if any(value.text.strip() for value in values) else 0.0

    def encode(self, inputs, params):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._texts = [item.text if item is not None else "" for item in inputs]
        self._words_matrix = None
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(params.ngram_min, params.ngram_max),
            sublinear_tf=True,
            max_features=100_000,
            dtype=np.float32,
        )
        try:
            return vectorizer.fit_transform(self._texts).tocsr()
        except ValueError as e:
            AppLogger.warning("[Mapping] Text key has no usable characters", exc=e)
            return np.zeros((len(inputs), 1), dtype=np.float32)

    def describe(self, members, params):
        from scipy import sparse
        from sklearn.feature_extraction.text import CountVectorizer

        if self._words_matrix is None:
            vectorizer = CountVectorizer(analyzer=_words, binary=True, dtype=np.float32)
            try:
                self._words_matrix = vectorizer.fit_transform(self._texts).tocsr()
                self._word_names = vectorizer.get_feature_names_out()
            except ValueError as e:
                AppLogger.warning("[Mapping] Text key has no words to label groups", exc=e)
                self._words_matrix = sparse.csr_matrix((len(self._texts), 0), dtype=np.float32)
                self._word_names = []
        return top_lift_terms(self._words_matrix, members, self._word_names, params.label_terms)


class CategoryEncoder(BaseEncoder):
    NAME = "category"
    DISPLAY_NAME = "Category"
    DESCRIPTION = "Only checks whether the values are exactly the same."

    @classmethod
    def detect(cls, values):
        texts = [value.text.strip() for value in values if value.text.strip()]
        if len(texts) < 2:
            return 0.0
        return 0.7 if len(set(texts)) <= max(2, len(texts) * 0.2) else 0.0

    def encode(self, inputs, params):
        from scipy import sparse

        self._values = [item.text.strip() if item is not None else "" for item in inputs]
        codes = {value: i for i, value in enumerate(sorted({v for v in self._values if v}))}
        rows = [i for i, value in enumerate(self._values) if value]
        columns = [codes[self._values[i]] for i in rows]
        return sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, columns)), shape=(len(inputs), max(len(codes), 1)))

    def describe(self, members, params):
        counts = Counter(self._values[i] for i in members if self._values[i])
        return [counts.most_common(1)[0][0]] if counts else []


HIST_BINS = (4, 8, 8)
HIST_RANGE = ((0.0, 100.0), (-80.0, 80.0), (-80.0, 80.0))
LAB_SCALE = np.array([100.0, 128.0, 128.0], dtype=np.float32)
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


def block_mean(image: np.ndarray, grid: int) -> np.ndarray:
    height, width = image.shape[:2]
    if height < grid or width < grid:
        image = np.repeat(np.repeat(image, -(-grid // height), axis=0), -(-grid // width), axis=1)
        height, width = image.shape[:2]
    rows = np.linspace(0, height, grid + 1).astype(int)
    columns = np.linspace(0, width, grid + 1).astype(int)
    sums = np.add.reduceat(np.add.reduceat(image.astype(np.float64), rows[:-1], axis=0), columns[:-1], axis=1)
    return sums / np.outer(np.diff(rows), np.diff(columns))[..., None]


def lab_histogram(lab: np.ndarray) -> np.ndarray:
    pixels = lab.reshape(-1, 3)
    low = [r[0] for r in HIST_RANGE]
    high = [r[1] - 1e-3 for r in HIST_RANGE]
    histogram, _ = np.histogramdd(np.clip(pixels, low, high), bins=HIST_BINS, range=HIST_RANGE)
    return np.sqrt(histogram.ravel() / max(len(pixels), 1))


class ImageColorEncoder(BaseEncoder):
    NAME = "image_color"
    DISPLAY_NAME = "Image color & layout"
    DESCRIPTION = "Compares the colors and rough layout of the images."
    INPUT = "image"

    def encode(self, inputs, params):
        count, grid = len(inputs), params.image_grid
        layout = np.zeros((count, grid * grid * 3), dtype=np.float32)
        histogram = np.zeros((count, int(np.prod(HIST_BINS))), dtype=np.float32)
        self._means = np.zeros((count, 3), dtype=np.float32)
        for i, image in enumerate(inputs):
            if image is None:
                continue
            lab = rgb_to_lab(image[..., :3])
            layout[i] = (block_mean(lab, grid) / LAB_SCALE).ravel()
            histogram[i] = lab_histogram(lab)
            self._means[i] = lab.reshape(-1, 3).mean(axis=0)
        present = self.present(inputs)
        layout /= median_pair_distance(layout[present])
        histogram /= median_pair_distance(histogram[present])
        return np.hstack([layout * params.image_balance, histogram * (1.0 - params.image_balance)])

    def describe(self, members, params):
        if len(members) == 0:
            return []
        mean = self._means[members].mean(axis=0)
        name = min(COLOR_NAMES, key=lambda item: float(np.sum((np.array(item[1]) - mean) ** 2)))[0]
        terms = [t(name)]
        if mean[0] >= BRIGHT_L:
            terms.append(t("bright"))
        elif mean[0] <= DARK_L:
            terms.append(t("dark"))
        return terms


ENCODERS: dict[str, type[BaseEncoder]] = {cls.NAME: cls for cls in (NumericEncoder, TokenSetEncoder, TextEncoder, CategoryEncoder, ImageColorEncoder)}


def value_encoders() -> list[type[BaseEncoder]]:
    return [cls for cls in ENCODERS.values() if cls.INPUT == "value"]


def detect_encoder(values: Sequence[PathValue]) -> str:
    return max(value_encoders(), key=lambda cls: cls.detect(values)).NAME

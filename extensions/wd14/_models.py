import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from ._downloader import DEFAULT_MODEL, MODELS_DIR

SPEC_FILE = "tagger.json"
CATEGORIES = ("rating", "general", "character", "copyright", "artist", "meta")
NAMED_CATEGORIES = ("character", "copyright", "artist")

DANBOORU_CATEGORY_IDS = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta", 9: "rating"}
CATEGORY_ALIASES = {"style": "artist", "series": "copyright"}
RATING_ALIASES = {"g": "general", "s": "sensitive", "q": "questionable", "e": "explicit"}
PAD_COLORS = {"white": (255, 255, 255), "black": (0, 0, 0)}


@dataclass(frozen=True)
class TaggerSpec:
    name: str
    model_path: Path
    tags_path: Path
    channels: str = "BGR"
    mean: tuple[float, ...] | None = None
    std: tuple[float, ...] | None = None
    pad: tuple[int, int, int] | None = (255, 255, 255)
    size: int | None = None
    multiple_of: int = 1
    resample: str = "lanczos"
    output: str | None = None
    category_ids: dict[int, str] = field(default_factory=lambda: dict(DANBOORU_CATEGORY_IDS))


def model_dir(name: str) -> Path:
    path = MODELS_DIR / name
    if path.parent != MODELS_DIR:
        raise ValueError(f"Invalid model name: {name}")
    return path


def list_models() -> list[str]:
    names = {DEFAULT_MODEL}
    if MODELS_DIR.is_dir():
        names.update(p.name for p in MODELS_DIR.iterdir() if (p / SPEC_FILE).is_file() or (p / "model.onnx").is_file())
    return sorted(names)


def load_spec(name: str) -> TaggerSpec:
    folder = model_dir(name)
    raw = {}
    spec_path = folder / SPEC_FILE
    if spec_path.is_file():
        raw = json.loads(spec_path.read_text(encoding="utf-8"))

    model_path = folder / raw.get("model", "model.onnx")
    tags_path = folder / raw.get("tags", "selected_tags.csv")
    for path in (model_path, tags_path):
        if not path.is_file():
            raise FileNotFoundError(f"Tagger '{name}' is missing {path.name}. Put it in {folder} or set its file name in {SPEC_FILE}")

    pad = raw.get("pad", "white")
    category_ids = dict(DANBOORU_CATEGORY_IDS)
    category_ids.update({int(k): normalize_category(v) for k, v in raw.get("categories", {}).items()})
    return TaggerSpec(
        name=name,
        model_path=model_path,
        tags_path=tags_path,
        channels=raw.get("channels", "BGR").upper(),
        mean=tuple(raw["mean"]) if "mean" in raw else None,
        std=tuple(raw["std"]) if "std" in raw else None,
        pad=PAD_COLORS[pad] if isinstance(pad, str) else tuple(pad) if pad else None,
        size=raw.get("size"),
        multiple_of=raw.get("multiple_of", 1),
        resample=raw.get("resample", "lanczos"),
        output=raw.get("output"),
        category_ids=category_ids,
    )


def normalize_category(value: str | int, category_ids: dict[int, str] = DANBOORU_CATEGORY_IDS) -> str:
    if isinstance(value, int) or str(value).lstrip("-").isdigit():
        return category_ids.get(int(value), "general")
    value = CATEGORY_ALIASES.get(value.lower(), value.lower())
    return value if value in CATEGORIES else "general"


def normalize_rating(name: str) -> str:
    for prefix in ("rating:", "rating_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return RATING_ALIASES.get(name, name)


def load_tags(spec: TaggerSpec) -> tuple[list[str], list[str]]:
    if spec.tags_path.suffix.lower() == ".json":
        names, raw_categories = _read_json_tags(spec.tags_path)
    else:
        names, raw_categories = _read_csv_tags(spec.tags_path)
    categories = [normalize_category(c, spec.category_ids) for c in raw_categories]
    names = [normalize_rating(n) if c == "rating" else n.replace(" ", "_") for n, c in zip(names, categories)]
    return names, categories


def _read_csv_tags(path: Path) -> tuple[list[str], list]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [row["name"] for row in rows], [row.get("category") or 0 for row in rows]


def _read_json_tags(path: Path) -> tuple[list[str], list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names = data["idx2tag"]
    tag_categories = data.get("tag2category", {})
    return list(names), [tag_categories.get(name, 0) for name in names]

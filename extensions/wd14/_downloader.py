import os
from pathlib import Path

from wafer.core.common.downloader import lib_needs_download, write_lib_version
from wafer.core.logs import AppLogger

DEFAULT_MODEL = "wd-swinv2-tagger-v3"
DEFAULT_REPO = "SmilingWolf/wd-swinv2-tagger-v3"

MODELS_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "lib" / "models"


def ensure_default_model(version: str = "") -> Path:
    model_dir = MODELS_DIR / DEFAULT_MODEL
    model_path = model_dir / "model.onnx"
    tags_path = model_dir / "selected_tags.csv"

    if not lib_needs_download(str(model_dir), version, str(model_path), str(tags_path)):
        write_lib_version(str(model_dir), version)
        AppLogger.debug(f"WD14 model already exists: {model_dir}")
        return model_dir

    from huggingface_hub import snapshot_download

    AppLogger.info(f"Downloading WD14 model {DEFAULT_REPO} to {model_dir} ...")
    snapshot_download(
        repo_id=DEFAULT_REPO,
        local_dir=str(model_dir),
        allow_patterns=["*.onnx", "*.csv"],
    )

    if not model_path.exists():
        raise FileNotFoundError(f"model.onnx not found after download: {model_path}")
    if not tags_path.exists():
        raise FileNotFoundError(f"selected_tags.csv not found after download: {tags_path}")

    write_lib_version(str(model_dir), version)
    AppLogger.info(f"WD14 model download complete: {model_dir}")
    return model_dir

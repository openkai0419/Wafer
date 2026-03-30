import os
from pathlib import Path

from wafer.utils.logs import AppLogger

KNOWN_MODELS = {
    'wd-swinv2-tagger-v3': 'SmilingWolf/wd-swinv2-tagger-v3',
    'wd-vit-tagger-v3': 'SmilingWolf/wd-vit-tagger-v3',
    'wd-convnext-tagger-v3': 'SmilingWolf/wd-convnext-tagger-v3',
    'wd-eva02-large-tagger-v3': 'SmilingWolf/wd-eva02-large-tagger-v3',
}

DEFAULT_MODEL = 'wd-swinv2-tagger-v3'

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
_MODELS_DIR = os.path.join(_LIB_DIR, 'models')


def ensure_model(model_key: str = DEFAULT_MODEL) -> Path:
    if model_key not in KNOWN_MODELS:
        raise ValueError(f"Unknown model: {model_key}. Available: {list(KNOWN_MODELS)}")

    model_dir = Path(_MODELS_DIR) / model_key
    model_path = model_dir / 'model.onnx'
    tags_path = model_dir / 'selected_tags.csv'

    if model_path.exists() and tags_path.exists():
        AppLogger.debug(f"WD14 model already exists: {model_dir}")
        return model_dir

    from huggingface_hub import snapshot_download

    repo_id = KNOWN_MODELS[model_key]
    AppLogger.info(f"Downloading WD14 model {repo_id} to {model_dir} ...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(model_dir),
        allow_patterns=["*.onnx", "*.csv"],
    )

    if not model_path.exists():
        raise FileNotFoundError(f"model.onnx not found after download: {model_path}")
    if not tags_path.exists():
        raise FileNotFoundError(f"selected_tags.csv not found after download: {tags_path}")

    AppLogger.info(f"WD14 model download complete: {model_dir}")
    return model_dir

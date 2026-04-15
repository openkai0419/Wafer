import os
from pathlib import Path

from wafer.utils.logs import AppLogger

MODEL_REPO = "Salesforce/blip-image-captioning-large"
DEFAULT_MODEL = "blip-large"

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_MODELS_DIR = os.path.join(_LIB_DIR, "models")


def ensure_model(model_key: str = DEFAULT_MODEL) -> Path:
    model_dir = (Path(_MODELS_DIR) / model_key).resolve()
    if not str(model_dir).startswith(str(Path(_MODELS_DIR).resolve())):
        raise ValueError(f"Invalid model key: {model_key}")

    config_path = model_dir / "config.json"
    if config_path.exists():
        AppLogger.debug(f"BLIP model already exists: {model_dir}")
        return model_dir

    from huggingface_hub import snapshot_download

    AppLogger.info(f"Downloading BLIP model {MODEL_REPO} to {model_dir} ...")
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=str(model_dir),
        ignore_patterns=["*.msgpack", "*.h5", "*.bin", "flax_model.*", "tf_model.*"],
    )

    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found after download: {config_path}")

    AppLogger.info(f"BLIP model download complete: {model_dir}")
    return model_dir

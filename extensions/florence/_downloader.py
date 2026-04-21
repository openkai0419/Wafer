import os
from pathlib import Path

from wafer.utils.logs import AppLogger

MODELS = {
    "base": ("microsoft/Florence-2-base", "ceaf371f01ef66192264811b390bccad475a4f02"),
    "large": ("microsoft/Florence-2-large", "00d2f1570b00c6dea5df998f5635db96840436bc"),
}
DEFAULT_VARIANT = "base"

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
_MODELS_DIR = os.path.join(_LIB_DIR, "models")


def ensure_model(variant: str = DEFAULT_VARIANT) -> Path:
    if variant not in MODELS:
        raise ValueError(f"Unknown variant: {variant}. Expected one of {list(MODELS.keys())}")

    model_dir = (Path(_MODELS_DIR) / f"florence-2-{variant}").resolve()
    if not str(model_dir).startswith(str(Path(_MODELS_DIR).resolve())):
        raise ValueError(f"Invalid variant: {variant}")

    config_path = model_dir / "config.json"
    if config_path.exists():
        AppLogger.debug(f"Florence-2 model already exists: {model_dir}")
        return model_dir

    from huggingface_hub import snapshot_download

    repo, revision = MODELS[variant]
    AppLogger.info(f"Downloading Florence-2 model {repo} (rev={revision[:8]}) to {model_dir} ...")
    snapshot_download(
        repo_id=repo,
        local_dir=str(model_dir),
        revision=revision,
        ignore_patterns=["*.msgpack", "*.h5", "flax_model.*", "tf_model.*"],
    )

    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found after download: {config_path}")

    AppLogger.info(f"Florence-2 model download complete: {model_dir}")
    return model_dir

## AI Tagger Extension

Tags illustrations with Danbooru-style taggers (ONNX). The model is selectable.

### Features
- **Model selection** — Pick any model in `lib/models/` from the settings panel. Preview switches instantly
- **Categories** — rating / character / copyright / artist / general / meta, when the model provides them
- **GPU Acceleration** — Uses CUDA when available, falls back to CPU

### Adding a model
Put a folder in `extensions/wd14/lib/models/<name>/` with:
- `model.onnx` (keep `model.onnx.data` next to it if the model has one)
- `selected_tags.csv` (`name`, `category` columns), or a JSON vocab with `idx2tag` / `tag2category`
- `tagger.json` when the model is not WD v3 style (NHWC, BGR, 0–255, white pad)

`tagger.json` keys (all optional):

| key | default | meaning |
|---|---|---|
| `model` / `tags` | `model.onnx` / `selected_tags.csv` | file names |
| `channels` | `BGR` | `RGB` or `BGR` |
| `mean` / `std` | none (0–255) | normalize `(x/255 - mean) / std` |
| `pad` | `white` | `white`, `black`, `[r, g, b]`, or `null` (keep aspect) |
| `size` | from ONNX | needed for dynamic input |
| `multiple_of` | 1 | side rounding when `pad` is `null` |
| `resample` | `lanczos` | `bicubic`, `bilinear`, `lanczos` |
| `categories` | Danbooru ids | id → category overrides, e.g. `{"5": "general"}` |

Logits are detected and passed through sigmoid automatically.

### Tested models

| name | download | tagger.json |
|---|---|---|
| wd-swinv2-tagger-v3 (default) | [SmilingWolf/wd-swinv2-tagger-v3](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3) | none |
| wd-eva02-large-tagger-v3 | [SmilingWolf/wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) | none |
| wd-eva02-tagger-2026-canary | [Misaka41Z/wd-eva02-tagger-2026-canary-onnx-v2](https://huggingface.co/Misaka41Z/wd-eva02-tagger-2026-canary-onnx-v2) (ONNX of [ashen-sensored/wd-eva02-tagger-2026-canary](https://huggingface.co/ashen-sensored/wd-eva02-tagger-2026-canary)) | `{"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5], "resample": "bicubic"}` |
| pixai-tagger-v1.0 | [Mexes/pixai-tagger-v1.0-onnx-fp32-fp16-int8](https://huggingface.co/Mexes/pixai-tagger-v1.0-onnx-fp32-fp16-int8) (`model_fp16.onnx` → `model.onnx`; ONNX of [pixai-labs/pixai-tagger-v1.0](https://huggingface.co/pixai-labs/pixai-tagger-v1.0)) | `{"channels": "RGB", "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5], "pad": "black", "resample": "bilinear"}` |
| kagami-24k | [Redstonexs/kagami-24k](https://huggingface.co/Redstonexs/kagami-24k) (`onnx/model_prob.onnx` → `model.onnx`) | `{"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5], "resample": "bicubic"}` |
| taggerine (DINOv3) | [silveroxides/tagger-experiment-onnx](https://huggingface.co/silveroxides/tagger-experiment-onnx) (`tagger/model.onnx` + `.data`, fp32) and the vocab from [lodestones/taggerine](https://huggingface.co/lodestones/taggerine) | `{"tags": "tagger_vocab_with_categories_and_alias_updated.json", "channels": "RGB", "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225], "pad": null, "size": 512, "multiple_of": 16, "categories": {"5": "general", "7": "meta"}}` |

Thresholds differ by model. Tune them in the preview.

### License

The Python source in this directory is licensed under **LGPL-2.1-or-later** (see the project root `LICENSE`).

| Component | Source | License |
|---|---|---|
| WD SwinV2 Tagger v3 model | https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3 | **Apache-2.0** (by SmilingWolf) |
| `numpy` | PyPI | BSD-3-Clause |
| `pillow` | PyPI | MIT-CMU / HPND |
| `huggingface_hub` | PyPI | Apache-2.0 |
| `onnxruntime-gpu` | PyPI | MIT |
| `nvidia-cudnn-cu12` | PyPI | **NVIDIA cuDNN License** (proprietary EULA; redistribution permitted under specific terms — see https://docs.nvidia.com/deeplearning/cudnn/sla/) |

Only the default model is downloaded automatically (on first run, into `lib/`, gitignored). Other models are placed by the user and follow their own licenses.

Note on training data: these models are trained on publicly available booru images. Downstream users should be aware of their own jurisdiction's rules regarding the source dataset.

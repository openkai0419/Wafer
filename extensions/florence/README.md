## Florence-2 Extension

Image captioning and tagging powered by the Florence-2 vision-language model.

### Features
- **Caption Generation** — Produces natural-language descriptions for images
- **Tag Extraction** — Stores results as searchable tags in the database
- **GPU Acceleration** — Uses CUDA when available, falls back to CPU
- **Settings Panel** — Per-database enable/disable and model configuration

### Notes
The model weights are downloaded from Hugging Face on first run. GPU inference requires a compatible CUDA/cuDNN environment.

### License

The Python source in this directory is licensed under **Apache-2.0** (see the project root `LICENSE`).

| Component | Source | License |
|---|---|---|
| Florence-2-base model | https://huggingface.co/microsoft/Florence-2-base | **MIT** (© Microsoft Corporation) |
| `torch`, `torchvision` | PyPI | BSD-3-Clause |
| `transformers` | PyPI | Apache-2.0 |
| `timm` | PyPI | Apache-2.0 |
| `safetensors` | PyPI | Apache-2.0 |
| `huggingface_hub` | PyPI | Apache-2.0 |
| `einops` | PyPI | MIT |
| `pillow` | PyPI | MIT-CMU / HPND |

The model files are downloaded from Hugging Face on first run and cached under `lib/models/` (gitignored). They are not redistributed in this repository. The upstream `LICENSE`, `README.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md` are downloaded together with the weights and remain in the cache directory.

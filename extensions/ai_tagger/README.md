## AI Tagger Extension

image tagging using WD14 tagger, especially for illustrations.

### Features
- **Batch Processing** — Tags images in batches of 150 for efficient throughput
- **GPU Acceleration** — Uses CUDA when available, falls back to CPU
- **Caching** — LRU cache (5 000 entries) to skip already-tagged images

### Notes
The model is downloaded from Hugging Face on first run. GPU inference requires a compatible CUDA/cuDNN environment.

### link
- [wd-swinv2-tagger-v3](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3)

### License

The Python source in this directory is licensed under **Apache-2.0** (see the project root `LICENSE`).

| Component | Source | License |
|---|---|---|
| WD SwinV2 Tagger v3 model | https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3 | **Apache-2.0** (by SmilingWolf) |
| `numpy` | PyPI | BSD-3-Clause |
| `pillow` | PyPI | MIT-CMU / HPND |
| `huggingface_hub` | PyPI | Apache-2.0 |
| `onnxruntime-gpu` | PyPI | MIT |
| `nvidia-cudnn-cu12` | PyPI | **NVIDIA cuDNN License** (proprietary EULA; redistribution permitted under specific terms — see https://docs.nvidia.com/deeplearning/cudnn/sla/) |

The model files are downloaded from Hugging Face on first run and cached under `lib/` (gitignored). They are not redistributed in this repository.

Note on training data: WD14 was trained on publicly available Danbooru images. The model weights themselves are Apache-2.0, but downstream users should be aware of their own jurisdiction's rules regarding the source dataset.

## AI Tagger Extension

Automatic image tagging using WD14 Tagger (ONNX).

### Features
- **Batch Processing** — Tags images in batches of 150 for efficient throughput
- **GPU Acceleration** — Uses CUDA when available, falls back to CPU
- **Caching** — LRU cache (5 000 entries) to skip already-tagged images

### Notes
The model is downloaded from Hugging Face on first run. GPU inference requires a compatible CUDA/cuDNN environment.

### link
- [wd-swinv2-tagger-v3](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3)
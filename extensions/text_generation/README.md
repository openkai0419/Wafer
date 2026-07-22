## Text Generation Extension

Extracts generation parameters embedded in AI-generated images.

### Parsers
- **NovelAI** — Parses EXIF Comment JSON to recover prompt, steps, sampler, seed, CFG, model and nested fields
- **WebUI** — Parses Stable Diffusion WebUI / Forge infotext (PNG `parameters` or EXIF UserComment). Extracts prompt, negative prompt and the `Key: value` parameter line. `Size` is split into `width`/`height`; quoted JSON values (e.g. `Hashes`) are expanded recursively
- **ComfyUI** — Extracts workflow data from video comments

### Notes
All parsers are disabled by default. Enable them in Plugin Manager to activate.


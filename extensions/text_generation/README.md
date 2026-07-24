## Text Generation Extension

Extracts generation parameters embedded in AI-generated images.

### Parsers
- **NovelAI** — Parses EXIF Comment JSON to recover prompt, steps, sampler, seed, CFG, model and nested fields
- **WebUI** — Parses Stable Diffusion WebUI / Forge infotext (PNG `parameters` or EXIF UserComment). Extracts prompt, negative prompt and the `Key: value` parameter line. `Size` is split into `width`/`height`; quoted JSON values (e.g. `Hashes`) are expanded recursively
- **ComfyUI** — Reconstructs the node graph embedded by ComfyUI across images (PNG/WebP), audio (FLAC/MP3/Opus) and video (native + VideoHelperSuite `comment`). Each node's widget inputs are flattened as `{class_type}#{index}/{input}: value`, where `{index}` is the position among same-class nodes ordered by node id, so keys stay stable regardless of the actual node ids. Connections are skipped and the raw `workflow` graph is kept as-is

### Notes
All parsers are disabled by default. Enable them in Plugin Manager to activate.


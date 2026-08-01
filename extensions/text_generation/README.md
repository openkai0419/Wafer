## Text Generation Extension

Extracts generation parameters embedded in AI-generated images.

### Parsers
- **NovelAI** — Parses EXIF Comment JSON to recover prompt, steps, sampler, seed, CFG, model and nested fields
- **WebUI** — Parses Stable Diffusion WebUI / Forge infotext (PNG `parameters` or EXIF UserComment). Extracts prompt, negative prompt and the `Key: value` parameter line. `Size` is split into `width`/`height`; quoted JSON values (e.g. `Hashes`) are expanded recursively
- **ComfyUI** — Reconstructs the node graph embedded by ComfyUI across images (PNG/WebP), audio (FLAC/MP3/Opus) and video (native + VideoHelperSuite `comment`). Each node's widget inputs are flattened as `{class_type}#{index}/{input}: value`, where `{index}` is the position among same-class nodes ordered by node id, so keys stay stable regardless of the actual node ids. Connections are skipped and the raw `workflow` graph is kept as-is

### Panels
- **ComfyUI Workflow** — Shows the ComfyUI `comfyui` metadata as a searchable key/value list with a drag handle on top. Drag the handle onto a running ComfyUI window to load the original workflow (exported on demand as a `.json` temp file)

### Notes
All parsers are disabled by default. Enable them in Plugin Manager to activate.


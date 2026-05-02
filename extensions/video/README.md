## Video Extension

Video playback powered by mpv with OpenGL rendering.

### Supported Formats
MP4, MKV, WebM, AVI, MOV, WMV, FLV, M4V, TS, MPG, MPEG

### Features
- **Playback Controls** — Volume, speed, loop, pause-in-background
- **Grid Thumbnails** — Video thumbnail extraction for grid view
- **State Persistence** — Remembers volume, speed, fit mode and other settings

### Notes
Requires mpv. The library is downloaded automatically on first launch.

### License

The Python source in this directory is licensed under **LGPL-2.1-or-later** (see the project root `LICENSE`).

This extension downloads `libmpv-2.dll` at first launch and links to it via `ctypes` through the `python-mpv` binding. The DLL is **not** redistributed in this repository (`lib/` is gitignored).

| Component | Source | License |
|---|---|---|
| `libmpv-2.dll` | https://mpv.io/ (typical Windows builds) | **GPL-2.0+** by default; some builds may be configured as **LGPL-2.1+**. Full text of GPLv2 in `THIRD_PARTY_LICENSE`. |
| `python-mpv` (`python-mpv==1.0.8`) | https://github.com/jaseg/python-mpv | Inherits libmpv's license: GPL-2.0+ or LGPL-2.1+. |
| `7zr.exe` | https://www.7-zip.org/ | LGPL-2.1+ |
| `py7zr` (Python dependency) | https://pypi.org/project/py7zr/ | LGPL-2.1+ |

`libmpv` is loaded as a dynamic library at runtime. Users redistributing a build that statically embeds a GPL-licensed `libmpv` together with this extension must comply with the corresponding GPL terms.

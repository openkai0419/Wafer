## FFmpeg Extension

Media metadata extraction for video and audio files using ffprobe.

### Supported Formats
MP4, MKV, WebM, AVI, MOV, WMV, FLV, TS, M4V, MPG, MPEG, MP3, FLAC, WAV, OGG, M4A, AAC, WMA, OPUS

### Features
- **Stream Probing** — Duration, resolution, codec, bitrate, frame rate and audio channel info via ffprobe
- **Metadata Panel** — Key-value display alongside other metadata extensions

### Notes
The ffmpeg binary is downloaded automatically on first launch.

### License

The Python source in this directory is licensed under **LGPL-2.1-or-later** (see the project root `LICENSE`).

This extension downloads and invokes **FFmpeg / ffprobe** binaries at first launch. The binaries are **not** redistributed in this repository (`lib/` is gitignored).

| Component | Source | License |
|---|---|---|
| `ffmpeg.exe`, `ffprobe.exe` (essentials build) | https://www.gyan.dev/ffmpeg/builds/ | **GPL-3.0** (gyan.dev release essentials/full builds are statically linked with GPL components such as libx264/libx265/libxvid). Full text in `THIRD_PARTY_LICENSE`. |
| `7zr.exe` (used only to extract the FFmpeg archive) | https://www.7-zip.org/ | LGPL-2.1+ |
| `py7zr` (runtime dependency provided by Wafer core) | https://pypi.org/project/py7zr/ | LGPL-2.1+ |

FFmpeg / ffprobe run as separate subprocesses; only their textual output is consumed. No FFmpeg source or object code is statically linked into the extension.

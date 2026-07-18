<div align="center">

# Wafer

![Wafer Screenshot](_docs/wafer_screenshot.png)

[![License](https://img.shields.io/badge/License-LGPL_2.1_or_later-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)
[![Release](https://img.shields.io/github/v/release/openkai0419/Wafer?style=flat-square)](https://github.com/openkai0419/Wafer/releases/latest)
[![Release Date](https://img.shields.io/github/release-date/openkai0419/Wafer?style=flat-square)](https://github.com/openkai0419/Wafer/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/openkai0419/Wafer/total?style=flat-square)](https://github.com/openkai0419/Wafer/releases)

[日本語はこちら](README.jp.md)

</div>

Wafer is a file viewer built on **PySide6**, **SQLite**, and **ZMQ**.
It collects local files in the background so large file sets can be browsed, searched, and filtered quickly.
Viewing, metadata, AI analysis, search, layouts, and archive support are added through extensions.

Platform: Windows

## Installation And Data

### From Zip

1. Open the [Releases](https://github.com/openkai0419/Wafer/releases/latest) page
2. Download `Wafer-vX.X.X.zip`
3. Extract the zip to any folder (SSD recommended)
4. Run `Wafer.exe`

A bundled Python environment is included. No Python installation is required.

### With Git

#### Requirements

- Python 3.11+
- Windows (currently the only tested OS)

#### Setup

```bash
git clone https://github.com/openkai0419/Wafer.git
cd Wafer

# Create venv and install dependencies
setup.bat

# Run the app
main.bat
# Or
python main.py
```

### Updates

Use the **Update** panel to download and apply the latest version, then restart.

### Uninstall

On Windows, application data such as databases, settings, logs, and caches is stored under `C:/Users/[username]/AppData/Local/Wafer` by default.

- **Portable (zip)**: Run `Uninstaller.exe` in the application folder.
- **From source**: Run `cleanup.bat`, then delete the cloned repository folder.

## Tray And Viewer

Wafer mainly uses two user-visible processes: `Tray` and `Viewer`.

| Type | Role |
|---|---|
| `Tray` | Resident manager for Viewer windows, databases, background work, and restarts. |
| `Viewer` | Window for browsing and searching files. Multiple Viewer windows can be opened. |

While Tray is running, file changes are detected and the database stays up to date.

## Code Design

Wafer uses a **common foundation + extensions** design.

- **`wafer/`** is the common foundation. It provides file collection, databases, search, rendering, process coordination, and plugin registration.
- **`extensions/`** contains independent folder-based extensions for image/video support, metadata extraction, AI analysis, search filters, layouts, and more.

The foundation stays shared while format-specific features live in extensions.

## Extensions

Extensions add more than display formats. They can extend collection, search, rendering, UI, and archive handling.
Features can be added by placing Python files under the `extensions` folder.

| Extension point | What it adds | Representative extensions |
|---|---|---|
| Viewer / Grid | File rendering, thumbnails, and viewer behavior | `image`, `animated`, `video` |
| Metadata & AI Collection | EXIF, video/audio metadata, colors, tags, captions, and other searchable or displayable data | `exiftool`, `ffmpeg`, `color`, `wd14`, `florence` |
| Search / Filter | Additional ways to search and narrow results, such as date ranges, regular expressions, and color distance | `additional_filters`, `color` |
| Layout / UI | Grid layouts, settings panels, and supporting UI | `additional_layout`, extension settings panels |
| Archive Support | Treat archive contents as logical child paths and delegate rendering to existing plugins | `zip` |

## Plugin Manager

`Plugin Manager` manages extension states and collection or analysis assignments.

- **Extensions**: Install extensions and switch them on or off. Restart is required after switching them.
- **Collectors**: Choose which Database stores metadata collection and AI analysis results.

## License

This project is licensed under the [GNU Lesser General Public License v2.1 or later](LICENSE).

All Python source code in this repository (`wafer/`, `extensions/`) is licensed under LGPL-2.1-or-later.
If you distribute modified versions of this project, you must provide the corresponding source code for your modifications under LGPL-2.1-or-later and keep clear change notices.

Some extensions use runtime-downloaded third-party binaries or models. These are not redistributed in this repository and are governed by their own licenses.
See each extension's `README.md` and `THIRD_PARTY_LICENSE` file, if present, for details.

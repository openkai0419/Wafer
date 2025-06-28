# private_rep
image viewer and metadata finder

## Overview
This project provides a simple image viewer and a background image collector. The viewer is built with **PySide6** and allows browsing images with metadata. The collector watches specified folders and indexes images for the viewer.

## Dependencies
Install required packages with `pip`:

```bash
pip install -r requirements.txt
```

Main packages include:
- PySide6
- watchdog
- psutil
- numpy
- opencv-python

## How to Run
1. Install Python 3.10 or later.
2. Install the dependencies as shown above.
3. Launch the GUI viewer with:

```bash
python main.py
```

When the viewer starts, it automatically launches the image collector as a separate process. The collector places an icon in the system tray and begins watching the configured folders.

To run only the collector (without the GUI), execute:

```bash
python collector.py
```

The collector will remain in the system tray. Use its context menu to exit when finished.

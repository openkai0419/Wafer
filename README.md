# private_rep
image viewer and metadata finder

## Overview
This project provides a simple image viewer and a background image collector. The viewer is built with **PySide6** and allows browsing images with metadata. The collector watches specified folders and indexes images for the viewer.

## setup
1.install python
my python version is currently 3.10. version testing and checking is not done yet
2.run setup.bat
3.run main.py for testing in dev
4.run buld.bat to build .exe

## os
I hope to support multiple os support,
but too lazy for testing other os.
please feel free to test and fix code for mac and linux.

## files
Using platformdirs for data files, so it will by normally placed at AppData/Local
_resources directory will is free open to replace images for each users

## translations
not yet
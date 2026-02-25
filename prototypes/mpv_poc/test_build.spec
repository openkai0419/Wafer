# -*- mode: python ; coding: utf-8 -*-
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(SPEC))
DLL_PATH = os.path.join(SCRIPT_DIR, 'libmpv-2.dll')

if not os.path.exists(DLL_PATH):
    raise FileNotFoundError(f'libmpv-2.dll not found at {DLL_PATH}')

a = Analysis(
    [os.path.join(SCRIPT_DIR, 'test_embed.py')],
    pathex=[],
    binaries=[(DLL_PATH, '.')],
    datas=[],
    hiddenimports=['mpv'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mpv_test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='mpv_test',
)

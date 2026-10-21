import os
import sys
import subprocess

from ..logs import AppLogger
from ..common.paths import containing_dir
from ..common.virtual_paths import is_virtual_path

_explorer_argtypes_set = False


def _reject_virtual_path(path: str, operation: str) -> bool:
    if is_virtual_path(str(path)):
        AppLogger.warning(f"[{operation}] virtual path rejected: {path} (file ops must target source files)")
        return True
    return False


def show_in_explorer(path: str, *, show_first_if_folder: bool = False) -> None:
    if not path:
        return
    if _reject_virtual_path(path, "reveal"):
        return
    p, open_folder_only = _resolve_show_path(path, show_first_if_folder)
    if not p:
        return
    if sys.platform.startswith("win"):
        if open_folder_only:
            _open_folder_windows(p)
            return
        if not _show_in_explorer_windows(p):
            _fallback_windows(p)
        return
    _fallback_posix(p)


def _resolve_show_path(path: str, show_first_if_folder: bool) -> tuple[str | None, bool]:
    p = os.path.normpath(os.path.abspath(str(path)))
    if not os.path.exists(p):
        return None, False
    if not (show_first_if_folder and os.path.isdir(p)):
        return p, False
    first = first_entry(p)
    if first:
        return first, False
    return p, True


def _fallback_windows(path: str) -> None:
    try:
        subprocess.Popen(["explorer", "/select,", path])
    except Exception as e:
        AppLogger.warning(f"explorer failed: {path}", exc=e)


def _open_folder_windows(path: str) -> None:
    try:
        subprocess.Popen(["explorer", path])
    except Exception as e:
        AppLogger.warning(f"explorer failed: {path}", exc=e)


def _fallback_posix(path: str) -> None:
    try:
        subprocess.Popen(["xdg-open", containing_dir(path)])
    except Exception as e:
        AppLogger.warning(f"xdg-open failed: {path}", exc=e)


def _setup_explorer_argtypes():
    global _explorer_argtypes_set
    if _explorer_argtypes_set:
        return
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    HRESULT = ctypes.c_long
    shell32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, wintypes.LPVOID, ctypes.POINTER(wintypes.LPVOID), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    shell32.SHParseDisplayName.restype = HRESULT
    shell32.SHOpenFolderAndSelectItems.argtypes = [wintypes.LPVOID, wintypes.UINT, ctypes.POINTER(wintypes.LPVOID), wintypes.DWORD]
    shell32.SHOpenFolderAndSelectItems.restype = HRESULT
    _explorer_argtypes_set = True


def _show_in_explorer_windows(path: str) -> bool:
    import ctypes
    from ctypes import wintypes

    try:
        _setup_explorer_argtypes()
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        COINIT_APARTMENTTHREADED = 2
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        try:
            pidl = wintypes.LPVOID()
            wide = ctypes.c_wchar_p(path)
            hr = shell32.SHParseDisplayName(wide, None, ctypes.byref(pidl), 0, None)
            if hr != 0 or not pidl:
                AppLogger.warning(f"SHParseDisplayName failed: {path} ({int(hr)})")
                return False
            try:
                hr = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
                if hr != 0:
                    AppLogger.warning(f"SHOpenFolderAndSelectItems failed: {path} ({int(hr)})")
                return hr == 0
            finally:
                ole32.CoTaskMemFree(pidl)
        finally:
            ole32.CoUninitialize()
    except Exception as e:
        AppLogger.warning(f"SHOpenFolderAndSelectItems failed: {path}", exc=e)
        return False


def first_entry(path: str) -> str | None:
    if not path:
        return None
    base = os.path.normpath(os.path.abspath(str(path)))
    if not os.path.isdir(base):
        return None
    try:
        with os.scandir(base) as it:
            for entry in it:
                return entry.path
    except OSError:
        return None
    return None


def open_file(path: str) -> None:
    if not path:
        return
    if _reject_virtual_path(path, "open"):
        return
    from PySide6 import QtCore, QtGui

    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


_BATCH_SUFFIXES = (".bat", ".cmd")


def _batch_command_line(program: str, targets: list[str]) -> str | None:
    expanded = [p for p in targets if "%" in p]
    if expanded:
        AppLogger.warning(f"[open_with] a batch file can't receive names containing '%': {expanded[0]}. Rename the file or choose an .exe program.")
        return None
    quoted = " ".join(f'"{arg}"' for arg in (os.path.normpath(program), *targets))
    return f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /v:off /s /c "{quoted}"'


def open_with(program: str, paths: list[str]) -> bool:
    targets = [os.path.normpath(p) for p in paths if p and not _reject_virtual_path(p, "open_with")]
    if not targets:
        return False
    if not program or not os.path.isfile(program):
        AppLogger.warning(f"[open_with] program not found: {program!r}. Set the program in the Open With options.")
        return False
    command = [program, *targets]
    if program.lower().endswith(_BATCH_SUFFIXES):
        command = _batch_command_line(program, targets)
        if command is None:
            return False
    try:
        subprocess.Popen(command)
    except OSError as e:
        AppLogger.warning(f"[open_with] failed to start {program}", exc=e)
        return False
    AppLogger.info(f"[open_with] {os.path.basename(program)}: {len(targets)} files")
    return True


def make_directory(path: str) -> str | None:
    if _reject_virtual_path(path, "mkdir"):
        return None
    os.makedirs(path, exist_ok=True)
    return path

import os
import sys
import subprocess

from afterimages.utils.logs import AppLogger

_explorer_argtypes_set = False


def show_in_explorer(path: str, *, show_first_if_folder: bool = False) -> None:
    if not path:
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
        target = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(["xdg-open", target])
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


def _first_scandir(path: str, *, files_only: bool = False) -> str | None:
    if not path:
        return None
    base = os.path.normpath(os.path.abspath(str(path)))
    if not os.path.isdir(base):
        return None
    try:
        with os.scandir(base) as it:
            for entry in it:
                if files_only:
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                return entry.path
    except OSError:
        return None
    return None


def first_file(path: str) -> str | None:
    return _first_scandir(path, files_only=True)


def first_entry(path: str) -> str | None:
    return _first_scandir(path)

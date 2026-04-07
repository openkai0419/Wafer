from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from ctypes import HRESULT, POINTER, Structure, byref, c_char_p, c_int, c_uint, c_void_p, c_wchar_p, windll
from pathlib import Path

from ...utils.logs import AppLogger

GWL_WNDPROC = -4
COINIT_APARTMENTTHREADED = 2

CMF_NORMAL = 0x00000000
CMF_EXPLORE = 0x00000004
CMF_CANRENAME = 0x00000010
CMF_EXTENDEDVERBS = 0x00000100

TPM_RETURNCMD = 0x0100
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002

WM_INITMENUPOPUP = 0x0117
WM_DRAWITEM = 0x002B
WM_MEASUREITEM = 0x002C
WM_MENUCHAR = 0x0120

CMIC_MASK_UNICODE = 0x00004000
CMIC_MASK_PTINVOKE = 0x20000000
SEE_MASK_INVOKEIDLIST = 0x0000000C

SW_SHOWNORMAL = 1
S_OK = 0


class _GUID(Structure):
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


class _CMINVOKECOMMANDINFOEX(Structure):
    _fields_ = [
        ("cbSize", c_uint),
        ("fMask", c_uint),
        ("hwnd", wt.HWND),
        ("lpVerb", c_void_p),
        ("lpParameters", c_char_p),
        ("lpDirectory", c_char_p),
        ("nShow", c_int),
        ("dwHotKey", wt.DWORD),
        ("hIcon", wt.HANDLE),
        ("lpTitle", c_char_p),
        ("lpVerbW", c_wchar_p),
        ("lpParametersW", c_wchar_p),
        ("lpDirectoryW", c_wchar_p),
        ("lpTitleW", c_wchar_p),
        ("ptInvoke", wt.POINT),
    ]


_argtypes_set = False
_iids_initialized = False

_IID_IShellFolder: _GUID
_IID_IContextMenu: _GUID
_IID_IContextMenu2: _GUID
_IID_IContextMenu3: _GUID

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, c_uint, wt.WPARAM, wt.LPARAM)


def _make_guid(d1, d2, d3, *d4):
    return _GUID(d1, d2, d3, (ctypes.c_byte * 8)(*d4))


def _ensure_iids():
    global _iids_initialized, _IID_IShellFolder, _IID_IContextMenu, _IID_IContextMenu2, _IID_IContextMenu3
    if _iids_initialized:
        return
    _IID_IShellFolder = _make_guid(0x000214E6, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
    _IID_IContextMenu = _make_guid(0x000214E4, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
    _IID_IContextMenu2 = _make_guid(0x000214F4, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
    _IID_IContextMenu3 = _make_guid(0xBCFCE0A0, 0xEC17, 0x11D0, 0x8D, 0x10, 0x00, 0xA0, 0xC9, 0x0F, 0x27, 0x19)
    _iids_initialized = True


def _ensure_argtypes():
    global _argtypes_set
    if _argtypes_set:
        return
    shell32 = windll.shell32
    ole32 = windll.ole32
    user32 = windll.user32

    shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p), wt.DWORD, POINTER(wt.DWORD)]
    shell32.SHParseDisplayName.restype = HRESULT

    shell32.SHBindToParent.argtypes = [c_void_p, c_void_p, POINTER(c_void_p), POINTER(c_void_p)]
    shell32.SHBindToParent.restype = HRESULT

    shell32.ILFree.argtypes = [c_void_p]
    shell32.ILFree.restype = None

    shell32.ILFindLastID.argtypes = [c_void_p]
    shell32.ILFindLastID.restype = c_void_p

    shell32.SHGetDesktopFolder.argtypes = [POINTER(c_void_p)]
    shell32.SHGetDesktopFolder.restype = HRESULT

    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wt.HMENU

    user32.DestroyMenu.argtypes = [wt.HMENU]
    user32.DestroyMenu.restype = wt.BOOL

    user32.TrackPopupMenu.argtypes = [wt.HMENU, c_uint, c_int, c_int, c_int, wt.HWND, c_void_p]
    user32.TrackPopupMenu.restype = wt.BOOL

    user32.SetWindowLongPtrW.argtypes = [wt.HWND, c_int, ctypes.c_longlong]
    user32.SetWindowLongPtrW.restype = ctypes.c_longlong

    user32.GetWindowLongPtrW.argtypes = [wt.HWND, c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_longlong

    user32.CallWindowProcW.argtypes = [ctypes.c_longlong, wt.HWND, c_uint, wt.WPARAM, wt.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_longlong

    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL

    ole32.CoInitializeEx.argtypes = [c_void_p, wt.DWORD]
    ole32.CoInitializeEx.restype = HRESULT

    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    _argtypes_set = True


def _vt(obj: int, index: int, restype, *argtypes):
    vtable_ptr = ctypes.cast(obj, POINTER(POINTER(c_void_p)))
    func_addr = vtable_ptr[0][index]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(func_addr)


def _release(obj: int):
    if obj:
        _vt(obj, 2, ctypes.c_ulong)(obj)


def _query_interface(obj: int, iid) -> int:
    out = c_void_p()
    hr = _vt(obj, 0, HRESULT, c_void_p, POINTER(c_void_p))(obj, byref(iid), byref(out))
    if hr != S_OK or not out.value:
        return 0
    return out.value


_ISF_GetUIObjectOf = 10
_ICM_QueryContextMenu = 3
_ICM_InvokeCommand = 4
_ICM2_HandleMenuMsg = 6
_ICM3_HandleMenuMsg2 = 7


def show_shell_context_menu(paths: list[str], hwnd: int, x: int, y: int) -> bool:
    if not sys.platform.startswith("win"):
        return False
    if not paths:
        return False

    _ensure_iids()
    _ensure_argtypes()

    abs_paths = [str(Path(p).resolve()) for p in paths]

    parents = {str(Path(p).parent) for p in abs_paths}
    same_dir = len(parents) == 1
    parent_dir = str(Path(abs_paths[0]).parent) if same_dir else None

    shell32 = windll.shell32
    ole32 = windll.ole32
    user32 = windll.user32

    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)

    full_pidls: list[int] = []
    folder_obj = 0
    desktop_obj = 0
    cm_obj = 0
    cm3_obj = 0
    cm2_obj = 0
    hmenu = None
    old_wndproc = 0
    wndproc_ref = None

    try:
        for p in abs_paths:
            pidl = c_void_p()
            hr = shell32.SHParseDisplayName(p, None, byref(pidl), 0, None)
            if hr != S_OK:
                AppLogger.warning(f"SHParseDisplayName failed: {p} (0x{hr & 0xFFFFFFFF:08X})")
                return False
            full_pidls.append(pidl.value)

        if same_dir:
            folder_ptr = c_void_p()
            child_pidl_ptr = c_void_p()
            hr = shell32.SHBindToParent(full_pidls[0], byref(_IID_IShellFolder), byref(folder_ptr), byref(child_pidl_ptr))
            if hr != S_OK:
                AppLogger.warning(f"SHBindToParent failed: (0x{hr & 0xFFFFFFFF:08X})")
                return False
            folder_obj = folder_ptr.value

            child_pidls = []
            for fp in full_pidls:
                child = shell32.ILFindLastID(fp)
                if not child:
                    AppLogger.warning("ILFindLastID returned NULL")
                    return False
                child_pidls.append(child)
        else:
            desktop_ptr = c_void_p()
            hr = shell32.SHGetDesktopFolder(byref(desktop_ptr))
            if hr != S_OK:
                AppLogger.warning(f"SHGetDesktopFolder failed: (0x{hr & 0xFFFFFFFF:08X})")
                return False
            desktop_obj = desktop_ptr.value
            folder_obj = desktop_obj

            child_pidls = list(full_pidls)

        cidl = len(child_pidls)
        apidl = (c_void_p * cidl)(*child_pidls)

        cm_ptr = c_void_p()
        reserved = c_uint(0)
        hr = _vt(
            folder_obj,
            _ISF_GetUIObjectOf,
            HRESULT,
            wt.HWND,
            c_uint,
            POINTER(c_void_p),
            c_void_p,
            POINTER(c_uint),
            POINTER(c_void_p),
        )(folder_obj, hwnd, cidl, apidl, byref(_IID_IContextMenu), byref(reserved), byref(cm_ptr))
        if hr != S_OK:
            AppLogger.warning(f"GetUIObjectOf failed: (0x{hr & 0xFFFFFFFF:08X})")
            return False
        cm_obj = cm_ptr.value

        cm3_obj = _query_interface(cm_obj, _IID_IContextMenu3)
        if not cm3_obj:
            cm2_obj = _query_interface(cm_obj, _IID_IContextMenu2)

        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            AppLogger.warning("CreatePopupMenu failed")
            return False

        flags = CMF_NORMAL | CMF_EXPLORE | CMF_CANRENAME
        hr = _vt(
            cm_obj,
            _ICM_QueryContextMenu,
            HRESULT,
            wt.HMENU,
            c_uint,
            c_uint,
            c_uint,
            c_uint,
        )(cm_obj, hmenu, 0, 1, 0x7FFF, flags)
        if hr < 0:
            AppLogger.warning(f"QueryContextMenu failed: (0x{hr & 0xFFFFFFFF:08X})")
            return False

        handler = cm3_obj or cm2_obj
        if handler:
            original_wndproc = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)

            def subclass_proc(h, msg, wp, lp):
                if msg in (WM_INITMENUPOPUP, WM_DRAWITEM, WM_MEASUREITEM, WM_MENUCHAR):
                    try:
                        if cm3_obj:
                            result = wt.LPARAM()
                            _vt(cm3_obj, _ICM3_HandleMenuMsg2, HRESULT, c_uint, wt.WPARAM, wt.LPARAM, POINTER(wt.LPARAM))(cm3_obj, msg, wp, lp, byref(result))
                            if msg == WM_MENUCHAR:
                                return result.value
                            return 0
                        elif cm2_obj:
                            _vt(cm2_obj, _ICM2_HandleMenuMsg, HRESULT, c_uint, wt.WPARAM, wt.LPARAM)(cm2_obj, msg, wp, lp)
                            return 0
                    except OSError:
                        pass
                return user32.CallWindowProcW(original_wndproc, h, msg, wp, lp)

            wndproc_ref = WNDPROC(subclass_proc)
            old_wndproc = original_wndproc
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(wndproc_ref, c_void_p).value)

        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu,
            TPM_RETURNCMD | TPM_LEFTALIGN | TPM_RIGHTBUTTON,
            x,
            y,
            0,
            hwnd,
            None,
        )

        if old_wndproc:
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, old_wndproc)
            old_wndproc = 0

        if cmd:
            ci = _CMINVOKECOMMANDINFOEX()
            ci.cbSize = ctypes.sizeof(_CMINVOKECOMMANDINFOEX)
            ci.fMask = SEE_MASK_INVOKEIDLIST | CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE
            ci.hwnd = hwnd
            ci.lpVerb = c_void_p(cmd - 1)
            ci.lpVerbW = ctypes.cast(c_void_p(cmd - 1), c_wchar_p)
            ci.nShow = SW_SHOWNORMAL
            ci.ptInvoke = wt.POINT(x, y)
            ci.lpDirectory = parent_dir.encode("utf-8") if parent_dir else None
            ci.lpDirectoryW = parent_dir if parent_dir else None

            hr = _vt(
                cm_obj,
                _ICM_InvokeCommand,
                HRESULT,
                POINTER(_CMINVOKECOMMANDINFOEX),
            )(cm_obj, byref(ci))
            if hr != S_OK:
                AppLogger.warning(f"InvokeCommand failed: (0x{hr & 0xFFFFFFFF:08X})")
                return False

            return True

        return False

    except Exception as e:
        AppLogger.warning(f"shell_context_menu failed: {abs_paths}", exc=e)
        return False

    finally:
        if old_wndproc:
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, old_wndproc)
        if hmenu:
            user32.DestroyMenu(hmenu)
        _release(cm3_obj)
        _release(cm2_obj)
        if desktop_obj:
            _release(desktop_obj)
        for fp in full_pidls:
            shell32.ILFree(fp)
        ole32.CoUninitialize()

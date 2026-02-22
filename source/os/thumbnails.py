import io
import os
import sys
from PIL import Image

from ..common.logs import AppLogger


_IShellItemImageFactory = None
_shell_argtypes_set = False


def _get_shell_item_factory_class():
    global _IShellItemImageFactory, _shell_argtypes_set
    if _IShellItemImageFactory is None:
        import ctypes
        from ctypes import POINTER, c_long, c_void_p, c_wchar_p, windll
        from ctypes.wintypes import HANDLE, SIZE, UINT
        from comtypes import COMMETHOD, GUID, IUnknown

        HRESULT = c_long

        class IShellItemImageFactory(IUnknown):
            _iid_ = GUID('{bcc18b79-ba16-442f-80c4-8a59c30c463b}')
            _methods_ = [COMMETHOD([], HRESULT, 'GetImage', (['in'], SIZE, 'size'), (['in'], UINT, 'flags'), (['out'], POINTER(HANDLE), 'phbm'))]

        _IShellItemImageFactory = IShellItemImageFactory

        if not _shell_argtypes_set:
            shell32 = windll.shell32
            shell32.SHCreateItemFromParsingName.argtypes = [c_wchar_p, c_void_p, POINTER(GUID), POINTER(c_void_p)]
            shell32.SHCreateItemFromParsingName.restype = HRESULT
            _shell_argtypes_set = True

    return _IShellItemImageFactory


_GPS_BESTEFFORT = 0x40
_DIMENSION_KEYS = None


def _get_dimension_keys():
    global _DIMENSION_KEYS
    if _DIMENSION_KEYS is None:
        from win32com.propsys import pscon
        _DIMENSION_KEYS = [
            (pscon.PKEY_Image_HorizontalSize, pscon.PKEY_Image_VerticalSize),
            (pscon.PKEY_Video_FrameWidth, pscon.PKEY_Video_FrameHeight),
        ]
    return _DIMENSION_KEYS


def _get_dimensions_from_property_store(abs_path: str) -> tuple[int, int] | None:
    from win32com.propsys import propsys
    try:
        store = propsys.SHGetPropertyStoreFromParsingName(
            abs_path, None, _GPS_BESTEFFORT, propsys.IID_IPropertyStore
        )
    except Exception as e:
        AppLogger.debug(f'PropertyStore open failed: {abs_path} ({e})')
        return None
    for w_key, h_key in _get_dimension_keys():
        try:
            w = store.GetValue(w_key).GetValue()
            h = store.GetValue(h_key).GetValue()
            if w and h and isinstance(w, int) and isinstance(h, int):
                return (w, h)
        except Exception:
            continue
    return None


def _get_thumbnail_aspect_ratio(abs_path: str, size: int = 96) -> float | None:
    import ctypes
    from ctypes import POINTER, byref, c_void_p, cast, windll
    from ctypes.wintypes import SIZE

    factory_cls = _get_shell_item_factory_class()
    shell32 = windll.shell32
    gdi32 = windll.gdi32

    handle = c_void_p()
    hr = shell32.SHCreateItemFromParsingName(abs_path, None, byref(factory_cls._iid_), byref(handle))
    if hr != 0:
        return None
    factory = cast(handle, POINTER(factory_cls))
    try:
        hbitmap = factory.GetImage(SIZE(size, size), 0)
        if not hbitmap:
            return None
        try:
            import win32ui
            bmp = win32ui.CreateBitmapFromHandle(int(hbitmap))
            info = bmp.GetInfo()
            w, h = info['bmWidth'], info['bmHeight']
            if h > 0 and w > 0:
                return w / h
            return None
        finally:
            gdi32.DeleteObject(c_void_p(int(hbitmap)))
    finally:
        del factory


def get_aspect_ratios(paths: list[str]) -> dict[str, float]:
    if not paths:
        return {}
    if sys.platform.startswith('win'):
        return _get_aspect_ratios_windows(paths)
    return {}


def _get_aspect_ratios_windows(paths: list[str]) -> dict[str, float]:
    import pythoncom
    pythoncom.CoInitialize()
    try:
        result = {}
        for p in paths:
            abs_path = os.path.abspath(p)
            dims = _get_dimensions_from_property_store(abs_path)
            if dims:
                w, h = dims
                if h > 0:
                    result[p] = w / h
                continue
            ratio = _get_thumbnail_aspect_ratio(abs_path)
            if ratio:
                result[p] = ratio
        return result
    finally:
        pythoncom.CoUninitialize()


class FileThumbnailer:

    def __init__(self):
        self.platform = sys.platform
        if self.platform == 'darwin':
            from Cocoa import NSURL, NSWorkspace
            from Quartz import CGSizeMake, QLThumbnailImageCreate, kCFAllocatorDefault
            self._NSWorkspace = NSWorkspace
            self._NSURL = NSURL
            self._QLThumbnailImageCreate = QLThumbnailImageCreate
            self._kCFAllocatorDefault = kCFAllocatorDefault
            self._CGSizeMake = CGSizeMake
        elif self.platform.startswith('linux'):
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gio, Gtk
            self._Gio = Gio
            self._Gtk = Gtk
            self._warned_linux_thumb_query = False

    def get_file_dimensions(self, file_path: str) -> tuple[int, int] | None:
        if not os.path.exists(file_path):
            return None
        if self.platform.startswith('win'):
            return self._get_dimensions_windows(file_path)
        return None

    def _get_dimensions_windows(self, file_path: str) -> tuple[int, int] | None:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            return _get_dimensions_from_property_store(os.path.abspath(file_path))
        finally:
            pythoncom.CoUninitialize()

    def get_thumbnail(self, file_path, size=256):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'ファイルが存在しません: {file_path}')
        if self.platform.startswith('win'):
            return self._get_thumbnail_windows(file_path, size)
        elif self.platform == 'darwin':
            return self._get_thumbnail_mac(file_path, size)
        elif self.platform.startswith('linux'):
            return self._get_thumbnail_linux(file_path, size)
        else:
            raise NotImplementedError('未対応のプラットフォームです。')

    def _get_thumbnail_windows(self, file_path, size):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            return self._get_thumbnail_windows_inner(file_path, size)
        finally:
            pythoncom.CoUninitialize()

    def _get_thumbnail_windows_inner(self, file_path, size):
        import ctypes
        from ctypes import POINTER, byref, c_void_p, cast, windll
        from ctypes.wintypes import SIZE

        factory_cls = _get_shell_item_factory_class()
        shell32 = windll.shell32
        gdi32 = windll.gdi32

        abs_path = os.path.abspath(file_path)
        handle = c_void_p()
        hr = shell32.SHCreateItemFromParsingName(abs_path, None, byref(factory_cls._iid_), byref(handle))
        if hr != 0:
            AppLogger.warning(f'SHCreateItemFromParsingName に失敗しました: {file_path} (hr={hr})')
            return None
        factory = cast(handle, POINTER(factory_cls))
        try:
            hbitmap = factory.GetImage(SIZE(size, size), 0)
            if not hbitmap:
                AppLogger.warning(f'GetImage に失敗しました: {file_path}')
                return None
            try:
                import win32ui
                bmp = win32ui.CreateBitmapFromHandle(int(hbitmap))
                info = bmp.GetInfo()
                data = bmp.GetBitmapBits(True)
                return Image.frombuffer('RGBA', (info['bmWidth'], info['bmHeight']), data, 'raw', 'BGRA', 0, 1).copy()
            finally:
                gdi32.DeleteObject(c_void_p(int(hbitmap)))
        finally:
            del factory

    def _get_thumbnail_mac(self, file_path, size):
        try:
            url = self._NSURL.fileURLWithPath_(file_path)
            thumb = self._QLThumbnailImageCreate(self._kCFAllocatorDefault, url, self._CGSizeMake(size, size), None)
            if thumb:
                from Cocoa import NSBitmapImageRep
                rep = NSBitmapImageRep.alloc().initWithCGImage_(thumb)
                tiff = rep.TIFFRepresentation()
                return Image.open(io.BytesIO(bytes(tiff)))
        except Exception as e:
            AppLogger.warning(f'QuickLook 失敗: {file_path}', exc=e)
        ws = self._NSWorkspace.sharedWorkspace()
        icon = ws.iconForFile_(file_path)
        icon.setSize_((size, size))
        tiff = icon.TIFFRepresentation()
        if tiff:
            return Image.open(io.BytesIO(bytes(tiff)))
        return None

    def _get_thumbnail_linux(self, file_path, size):
        Gio = self._Gio
        Gtk = self._Gtk
        gfile = Gio.File.new_for_path(file_path)
        try:
            info = gfile.query_info('thumbnail::path', 0, None)
            thumb_path = info.get_attribute_byte_string('thumbnail::path')
            if thumb_path and os.path.exists(thumb_path):
                return Image.open(thumb_path)
        except Exception as e:
            if not self._warned_linux_thumb_query:
                self._warned_linux_thumb_query = True
                AppLogger.warning(f'Linux thumbnail query failed, fallback to icon: {file_path}', exc=e)
        try:
            info = gfile.query_info('standard::icon', 0, None)
            icon = info.get_icon()
            names = icon.get_names() if icon else []
            theme = Gtk.IconTheme.get_default()
            for name in names:
                icon_info = theme.lookup_icon(name, size, 0)
                if icon_info:
                    icon_path = icon_info.get_filename()
                    if icon_path:
                        return Image.open(icon_path)
        except Exception as e:
            AppLogger.warning(f'Linux fallback 失敗: {file_path}', exc=e)
        return None

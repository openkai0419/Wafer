import io
import os
import sys
from PIL import Image

class FileThumbnailer:

    def __init__(self):
        self.platform = sys.platform
        if self.platform.startswith('win'):
            import pythoncom
            pythoncom.CoInitialize()
            from ctypes import POINTER, c_long, c_void_p, c_wchar_p, windll
            from ctypes.wintypes import HANDLE, SIZE, UINT
            import win32ui
            HRESULT = c_long
            from comtypes import COMMETHOD, GUID, IUnknown

            class IShellItemImageFactory(IUnknown):
                _iid_ = GUID('{bcc18b79-ba16-442f-80c4-8a59c30c463b}')
                _methods_ = [COMMETHOD([], HRESULT, 'GetImage', (['in'], SIZE, 'size'), (['in'], UINT, 'flags'), (['out'], POINTER(HANDLE), 'phbm'))]
            self._IShellItemImageFactory = IShellItemImageFactory
            self._shell32 = windll.shell32
            self._gdi32 = windll.gdi32
            self._win32ui = win32ui
            self._shell32.SHCreateItemFromParsingName.argtypes = [c_wchar_p, c_void_p, POINTER(GUID), POINTER(c_void_p)]
            self._shell32.SHCreateItemFromParsingName.restype = HRESULT
        elif self.platform == 'darwin':
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
        from ctypes import POINTER, byref, c_void_p, cast
        from ctypes.wintypes import SIZE
        handle = c_void_p()
        hr = self._shell32.SHCreateItemFromParsingName(file_path, None, byref(self._IShellItemImageFactory._iid_), byref(handle))
        if hr != 0:
            print('SHCreateItemFromParsingName に失敗しました')
            return None
        factory = cast(handle, POINTER(self._IShellItemImageFactory))
        hbitmap = factory.GetImage(SIZE(size, size), 0)
        if not hbitmap:
            print('GetImage に失敗しました')
            return None
        bmp = self._win32ui.CreateBitmapFromHandle(int(hbitmap))
        info = bmp.GetInfo()
        data = bmp.GetBitmapBits(True)
        self._gdi32.DeleteObject(c_void_p(int(hbitmap)))
        img = Image.frombuffer('RGBA', (info['bmWidth'], info['bmHeight']), data, 'raw', 'BGRA', 0, 1).copy()
        return img

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
            print(f'QuickLook 失敗: {e}')
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
        except Exception:
            pass
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
            print(f'Linux fallback 失敗: {e}')
        return None
if __name__ == '__main__':
    thumb = FileThumbnailer()
    img = thumb.get_thumbnail('C:\\Users\\openk\\Downloads\\13.mp4', size=256 * 256)
    if img:
        img.show()
    else:
        print('サムネイルを取得できませんでした。')

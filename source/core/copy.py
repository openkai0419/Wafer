import os
import sys
import ctypes
import subprocess
import platform
import shutil
from pathlib import Path

if sys.platform.startswith("win"):
    import win32clipboard
    import win32con


class ClipboardFileSetter:
    """
    ファイルをOSのクリップボードにコピーまたは切り取りとして設定し、
    エクスプローラー/Finder/ファイルマネージャで「貼り付け (Paste)」できるようにするユーティリティ。
    """

    @staticmethod
    def set_files(files: list[str], cut: bool = False):
        norm_files = ClipboardFileSetter._normalize_files(files)
        system = platform.system()

        try:
            if system == "Windows":
                ClipboardFileSetter._set_windows(norm_files, cut)
            elif system == "Darwin":
                ClipboardFileSetter._set_macos(norm_files, cut)
            elif system == "Linux":
                ClipboardFileSetter._set_linux(norm_files, cut)
            else:
                raise NotImplementedError(f"Unsupported platform: {system}")
        except Exception as e:
            print(f"[ClipboardError] {e}")
            raise

    @staticmethod
    def _normalize_files(files: list[str]) -> list[str]:
        return [str(Path(f).resolve()) for f in files if Path(f).exists()]

    # ---------- Windows対応 ----------
    @staticmethod
    def _set_windows(files: list[str], cut: bool):
        file_list = '\0'.join(files) + '\0\0'
        encoded = file_list.encode('utf-16le')

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", ctypes.c_uint),
                ("pt_x", ctypes.c_int),
                ("pt_y", ctypes.c_int),
                ("fNC", ctypes.c_int),
                ("fWide", ctypes.c_int),
            ]

        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.pt_x = 0
        dropfiles.pt_y = 0
        dropfiles.fNC = 0
        dropfiles.fWide = 1

        total_size = ctypes.sizeof(dropfiles) + len(encoded)
        GHND = 0x0042  # GMEM_MOVEABLE | GMEM_ZEROINIT

        h_global = ctypes.windll.kernel32.GlobalAlloc(GHND, total_size)
        if not h_global:
            raise MemoryError("GlobalAlloc failed")

        locked_mem = ctypes.windll.kernel32.GlobalLock(h_global)
        if not locked_mem:
            ctypes.windll.kernel32.GlobalFree(h_global)
            raise MemoryError("GlobalLock failed")

        ctypes.memmove(locked_mem, ctypes.addressof(dropfiles), ctypes.sizeof(dropfiles))
        ctypes.memmove(locked_mem + ctypes.sizeof(dropfiles), encoded, len(encoded))
        ctypes.windll.kernel32.GlobalUnlock(h_global)

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            if not win32clipboard.SetClipboardData(win32con.CF_HDROP, h_global):
                ctypes.windll.kernel32.GlobalFree(h_global)
                raise RuntimeError("SetClipboardData failed for CF_HDROP")

            if cut:
                format_name = "Preferred DropEffect"
                fmt = win32clipboard.RegisterClipboardFormat(format_name)
                DROPEFFECT_MOVE = 2
                size = ctypes.sizeof(ctypes.c_ulong)
                h_global2 = ctypes.windll.kernel32.GlobalAlloc(GHND, size)
                if not h_global2:
                    raise MemoryError("GlobalAlloc failed for DropEffect")

                locked2 = ctypes.windll.kernel32.GlobalLock(h_global2)
                if not locked2:
                    ctypes.windll.kernel32.GlobalFree(h_global2)
                    raise MemoryError("GlobalLock failed for DropEffect")

                ctypes.memmove(locked2, ctypes.byref(ctypes.c_ulong(DROPEFFECT_MOVE)), size)
                ctypes.windll.kernel32.GlobalUnlock(h_global2)

                if not win32clipboard.SetClipboardData(fmt, h_global2):
                    ctypes.windll.kernel32.GlobalFree(h_global2)
                    raise RuntimeError("SetClipboardData failed for Preferred DropEffect")
        finally:
            win32clipboard.CloseClipboard()

    # ---------- macOS対応 ----------
    @staticmethod
    def _set_macos(files: list[str], cut: bool):
        if cut:
            print("[macOS] Finderはcut操作に対応していないため、コピーとして扱います。")

        quoted = ", ".join(f'POSIX file "{f}"' for f in files)
        script = f'tell application "Finder" to set the clipboard to {{{quoted}}}'
        subprocess.run(["osascript", "-e", script], check=True)

    # ---------- Linux対応 ----------
    @staticmethod
    def _set_linux(files: list[str], cut: bool):
        uris = [Path(f).absolute().as_uri() for f in files]
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

        if "KDE" in desktop:
            if cut:
                print("[KDE] 現在cut動作には未対応です（コピーとして扱います）")
            mime = "text/uri-list"
            data = "\n".join(uris)
        else:
            mime = "x-special/gnome-copied-files"
            header = "cut" if cut else "copy"
            data = f"{header}\n" + "\n".join(uris) + "\n\0"

        use_wayland = os.environ.get("WAYLAND_DISPLAY")
        cmd = []

        if use_wayland:
            if not shutil.which("wl-copy"):
                raise FileNotFoundError("Wayland環境: 'wl-copy' が見つかりません。インストールしてください。")
            # --type が使える場合は付ける
            help_text = subprocess.getoutput("wl-copy --help")
            if "--type" in help_text:
                cmd = ["wl-copy", "--type", mime]
            else:
                cmd = ["wl-copy"]
        else:
            if not shutil.which("xclip"):
                raise FileNotFoundError("X11環境: 'xclip' が見つかりません。インストールしてください。")
            cmd = ["xclip", "-selection", "clipboard", "-t", mime]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(input=data.encode("utf-8"))

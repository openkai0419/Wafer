import os
import sys
import ctypes
import shutil
import zipfile
import tempfile
import urllib.request


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DLL_NAME = 'libmpv-2.dll'
DLL_PATH = os.path.join(SCRIPT_DIR, DLL_NAME)

MPV_BOOTSTRAP_URL = (
    'https://sourceforge.net/projects/mpv-player-windows/'
    'files/libmpv/mpv-dev-x86_64-20250209-git-40da86f.7z/download'
)


def check_dll():
    if os.path.exists(DLL_PATH):
        print(f'[OK] {DLL_NAME} found at {DLL_PATH}')
        return True

    for p in os.environ.get('PATH', '').split(os.pathsep):
        candidate = os.path.join(p, DLL_NAME)
        if os.path.exists(candidate):
            print(f'[OK] {DLL_NAME} found in PATH: {candidate}')
            return True

    print(f'[NG] {DLL_NAME} not found.')
    return False


def try_load_dll():
    os.add_dll_directory(SCRIPT_DIR)
    try:
        dll = ctypes.CDLL(DLL_PATH)
        print(f'[OK] DLL loaded successfully: {DLL_PATH}')
        return dll
    except Exception as e:
        print(f'[NG] DLL load failed: {e}')
        return None


def try_import_mpv():
    os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
    os.add_dll_directory(SCRIPT_DIR)
    try:
        import mpv
        player = mpv.MPV()
        print(f'[OK] python-mpv import succeeded. mpv version: {player.mpv_version}')
        player.terminate()
        return True
    except Exception as e:
        print(f'[NG] python-mpv import failed: {e}')
        return False


def main():
    print('=== mpv DLL Verification ===')
    print(f'Script dir: {SCRIPT_DIR}')
    print(f'Python: {sys.executable}')
    print()

    if not check_dll():
        print()
        print(f'Please download libmpv DLL and place {DLL_NAME} in:')
        print(f'  {SCRIPT_DIR}')
        print()
        print('Download from:')
        print('  https://sourceforge.net/projects/mpv-player-windows/files/libmpv/')
        print('  -> mpv-dev-x86_64-*.7z -> extract mpv-2.dll')
        print()
        print('Or install mpv from https://mpv.io/installation/')
        print('and copy mpv-2.dll from the install directory.')
        return False

    print()
    print('--- DLL Load Test ---')
    dll = try_load_dll()
    if not dll:
        return False

    print()
    print('--- python-mpv Import Test ---')
    if not try_import_mpv():
        return False

    print()
    print('=== All checks passed! ===')
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

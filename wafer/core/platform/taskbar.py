# pyright: reportMissingImports=false
import sys

from ...constants import APP_ID, APP_NAME
from ...utils.logs import AppLogger
from ...utils.paths import get_launcher_path


def apply_window_identity(hwnd):
    if sys.platform != "win32" or not hwnd:
        return
    launcher = get_launcher_path()
    if launcher is None:
        return
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon

        store = propsys.SHGetPropertyStoreForWindow(int(hwnd), propsys.IID_IPropertyStore)
        launcher_path = str(launcher)
        values = {
            pscon.PKEY_AppUserModel_ID: APP_ID,
            pscon.PKEY_AppUserModel_RelaunchCommand: f'"{launcher_path}"',
            pscon.PKEY_AppUserModel_RelaunchDisplayNameResource: APP_NAME,
            pscon.PKEY_AppUserModel_RelaunchIconResource: f'"{launcher_path}",0',
        }
        for key, value in values.items():
            store.SetValue(key, propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
        store.Commit()
        AppLogger.info(f"taskbar identity set: relaunch -> {launcher_path}")
    except Exception as e:
        AppLogger.warning(f"failed to set taskbar relaunch identity: {e}")

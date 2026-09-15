_cached_dpi: float | None = None


def dpix(px, base_dpi=96):
    global _cached_dpi
    if _cached_dpi is None:
        from PySide6 import QtGui

        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return px
        _cached_dpi = screen.logicalDotsPerInch()
    return int(px * _cached_dpi / base_dpi)
